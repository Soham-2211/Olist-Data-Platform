"""Late-delivery model: training, registry, batch scoring, evaluation.

Scoring happens when an order is placed. Every feature in ml_features is
point-in-time correct, so the same table serves training and serving
(no training/serving skew).
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

from .config import get_logger

log = get_logger("ml")

CATEGORICAL = ["customer_state", "seller_state", "category", "payment_type"]
NUMERIC = [
    "distance_km", "same_state", "promised_days", "seller_handling_days_allowed",
    "n_items", "n_sellers", "n_products", "items_value", "freight_value", "freight_ratio",
    "total_weight_kg", "total_volume_l", "max_item_weight_kg", "installments", "n_payments",
    "customer_prior_orders", "purchase_dow", "purchase_hour", "purchase_month",
    "seller_prior_deliveries", "seller_prior_late_rate_smoothed", "seller_prior_avg_delay_days",
    "seller_orders_prev_30d", "state_deliveries_prev_30d", "state_late_rate_prev_30d",
]
FEATURES = CATEGORICAL + NUMERIC
LEAKY = ["leaky_seller_late_rate", "leaky_state_month_late_rate"]
EXCLUDED_STATUSES = ("canceled", "unavailable")


def load_features(con, with_leaky: bool = False) -> pd.DataFrame:
    sql = "SELECT * FROM ml_features"
    if with_leaky:
        sql = "SELECT f.*, l.leaky_seller_late_rate, l.leaky_state_month_late_rate FROM ml_features f " \
              "JOIN ml_leaky_features l USING (order_id)"
    df = pd.read_sql(sql, con, parse_dates=["purchased_at", "delivered_at", "estimated_delivery_date"])
    return df


def mature_labels(df: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    """Training rows whose label is already knowable at `cutoff`.

    An order's lateness is decided the moment its promised date passes: delivered
    by then -> on time, not delivered by then -> late. Using only *delivered*
    orders instead would bias recent labels toward fast deliveries.
    """
    end = cutoff + pd.Timedelta(days=1)
    d = df[(df["estimated_delivery_date"] < cutoff.normalize())
           & ~df["order_status"].isin(EXCLUDED_STATUSES)].copy()
    delivered_by_promise = d["delivered_at"].notna() & (d["delivered_at"] < end) & \
        (d["delivered_at"].dt.normalize() <= d["estimated_delivery_date"])
    d["label"] = (~delivered_by_promise).astype(int)
    return d


def make_hgb(params: dict, seed: int = 42, features=FEATURES, categorical=CATEGORICAL) -> Pipeline:
    numeric = [f for f in features if f not in categorical]
    pre = ColumnTransformer([
        ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=np.nan,
                               encoded_missing_value=np.nan, min_frequency=20), list(categorical)),
        ("num", "passthrough", numeric)])
    p = {k: v for k, v in params.items() if k != "max_iter"}
    clf = HistGradientBoostingClassifier(
        categorical_features=[True] * len(categorical) + [False] * len(numeric),
        max_iter=params.get("max_iter", 500), early_stopping=True, validation_fraction=0.15,
        n_iter_no_change=40, scoring="loss", random_state=seed, **p)
    return Pipeline([("pre", pre), ("clf", clf)])


def make_logreg(seed: int = 42) -> Pipeline:
    pre = ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=20), CATEGORICAL),
        ("num", Pipeline([("imp", SimpleImputer(strategy="median", add_indicator=True)),
                          ("sc", StandardScaler())]), NUMERIC)])
    return Pipeline([("pre", pre), ("clf", LogisticRegression(C=0.3, max_iter=3000, random_state=seed))])


def top_k_metrics(y, p, share: float) -> dict:
    y, p = np.asarray(y), np.asarray(p)
    k = max(1, int(round(len(p) * share)))
    idx = np.argsort(-p)[:k]
    caught = y[idx].sum()
    return {"precision_at_k": float(caught / k), "recall_at_k": float(caught / max(y.sum(), 1)),
            "lift_at_k": float((caught / k) / max(y.mean(), 1e-9))}


def evaluate(y, p, share: float) -> dict:
    y, p = np.asarray(y), np.asarray(p)
    out = {"n": int(len(y)), "late_rate": round(float(y.mean()), 4)}
    if 0 < y.sum() < len(y):
        out.update({"roc_auc": round(roc_auc_score(y, p), 4), "pr_auc": round(average_precision_score(y, p), 4),
                    "brier": round(brier_score_loss(y, p), 4)})
    out.update({k: round(v, 4) for k, v in top_k_metrics(y, p, share).items()})
    return out


# ---------------------------------------------------------------- registry
def register(con, models_dir: Path, model, version: str, policy: str, train: pd.DataFrame, info: dict) -> Path:
    con.execute("""CREATE TABLE IF NOT EXISTS meta_model_registry (
        version TEXT, policy TEXT, trained_at TEXT, train_rows INTEGER, train_late_rate REAL,
        data_fingerprint TEXT, path TEXT, info TEXT, PRIMARY KEY (version, policy))""")
    fp = hashlib.sha256(pd.util.hash_pandas_object(train[["order_id", "label"]], index=False).values.tobytes())
    path = models_dir / policy / f"{version}.joblib"
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "features": FEATURES, "version": version, "policy": policy}, path)
    con.execute("INSERT OR REPLACE INTO meta_model_registry VALUES (?,?,?,?,?,?,?,?)",
                (version, policy, time.strftime("%Y-%m-%dT%H:%M:%S"), len(train), float(train["label"].mean()),
                 fp.hexdigest()[:16], str(path), json.dumps(info)))
    return path


def train_at_cutoff(df: pd.DataFrame, cutoff: pd.Timestamp, params: dict, seed: int = 42):
    train = mature_labels(df, cutoff)
    model = make_hgb(params, seed).fit(train[FEATURES], train["label"])
    return model, train


def score_batch(con, model, df: pd.DataFrame, batch_id: str, version: str, policy: str) -> int:
    con.execute("""CREATE TABLE IF NOT EXISTS ml_predictions (
        order_id TEXT, batch_id TEXT, policy TEXT, model_version TEXT, p_late REAL, scored_at TEXT,
        PRIMARY KEY (order_id, policy))""")
    new = df[df["order_id"].isin(set(r[0] for r in con.execute(
        "SELECT order_id FROM silver_orders WHERE first_batch = ?", (batch_id,))))]
    if new.empty:
        return 0
    p = model.predict_proba(new[FEATURES])[:, 1]
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    rows = [(o, batch_id, policy, version, float(s), now) for o, s in zip(new["order_id"], p)]
    con.execute("BEGIN")
    con.executemany("INSERT OR REPLACE INTO ml_predictions VALUES (?,?,?,?,?,?)", rows)
    con.execute("COMMIT")
    return len(rows)


# ---------------------------------------------------------------- monitoring
def psi(expected: np.ndarray, actual: np.ndarray, bins: int = 10) -> float:
    expected, actual = expected[~np.isnan(expected)], actual[~np.isnan(actual)]
    if len(expected) == 0 or len(actual) == 0:
        return float("nan")
    edges = np.unique(np.quantile(expected, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 0.0
    e = np.histogram(np.clip(expected, edges[0], edges[-1]), edges)[0] / len(expected)
    a = np.histogram(np.clip(actual, edges[0], edges[-1]), edges)[0] / len(actual)
    e, a = np.clip(e, 1e-4, None), np.clip(a, 1e-4, None)
    return float(np.sum((a - e) * np.log(a / e)))
