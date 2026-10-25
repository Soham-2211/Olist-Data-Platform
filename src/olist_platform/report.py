"""Offline evaluation, production monitoring and generated documentation."""
from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.inspection import permutation_importance  # noqa: E402
from sklearn.metrics import precision_recall_curve  # noqa: E402
from sklearn.model_selection import train_test_split  # noqa: E402

from . import ml  # noqa: E402
from .config import get_logger  # noqa: E402
from .warehouse import connect  # noqa: E402

log = get_logger("report")

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE, AQUA, MUTED = "#2a78d6", "#eb6834", "#1baf7a", "#b9b8b2"
plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10, "axes.titlesize": 12,
    "axes.titleweight": "bold", "axes.titlelocation": "left", "lines.linewidth": 2, "legend.frameon": False,
})


def _save(fig, path):
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _pct(ax):
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))


# ------------------------------------------------------------------ offline study
def offline_study(con, cfg) -> tuple[dict, dict]:
    m, sp, share = cfg["ml"], cfg["ml"]["offline_split"], cfg["ml"]["top_k_share"]
    df = ml.load_features(con, with_leaky=True)
    t_end, v_end, x_end = (pd.Timestamp(sp[k]) for k in ("train_end", "valid_end", "test_end"))
    lab = df[df["is_late"].notna()]
    valid = lab[(lab["purchased_at"] > t_end + pd.Timedelta(days=1)) & (lab["purchased_at"] < v_end + pd.Timedelta(days=1))]
    test = lab[(lab["purchased_at"] > v_end + pd.Timedelta(days=1)) & (lab["purchased_at"] < x_end + pd.Timedelta(days=1))]
    res: dict = {"split": {
        "train": {"label_mature_by": str(t_end.date()), "rows": int(len(ml.mature_labels(df, t_end)))},
        "valid": {"purchases": f"{t_end.date()} < d <= {v_end.date()}", "rows": len(valid),
                  "late_rate": round(float(valid["is_late"].mean()), 4)},
        "test": {"purchases": f"{v_end.date()} < d <= {x_end.date()}", "rows": len(test),
                 "late_rate": round(float(test["is_late"].mean()), 4)}}}

    # Model selection on validation (models trained on labels mature at train_end)
    tr = ml.mature_labels(df, t_end)
    sel = {}
    for name, model in [("logreg", ml.make_logreg()), ("hgb", ml.make_hgb(m["hgb"]))]:
        model.fit(tr[ml.FEATURES], tr["label"])
        sel[name] = ml.evaluate(valid["is_late"], model.predict_proba(valid[ml.FEATURES])[:, 1], share)
    res["validation"] = sel

    # Final test: refit on everything mature at valid_end
    tr2 = ml.mature_labels(df, v_end)
    y = test["is_late"].values
    scores = {
        "Heuristic: seller's past late rate": test["seller_prior_late_rate_smoothed"].values,
        "Heuristic: region's late rate, last 30 days": test["state_late_rate_prev_30d"].values,
    }
    lr = ml.make_logreg().fit(tr2[ml.FEATURES], tr2["label"])
    scores["Logistic regression"] = lr.predict_proba(test[ml.FEATURES])[:, 1]
    hgb = ml.make_hgb(m["hgb"]).fit(tr2[ml.FEATURES], tr2["label"])
    scores["Gradient boosting"] = hgb.predict_proba(test[ml.FEATURES])[:, 1]
    res["test"] = {k: ml.evaluate(y, v, share) for k, v in scores.items()}

    # Evaluation-design / leakage experiments
    feats_leaky = ml.FEATURES + ml.LEAKY
    leaky = ml.make_hgb(m["hgb"], features=feats_leaky).fit(tr2[feats_leaky], tr2["label"])
    p_leaky = leaky.predict_proba(test[feats_leaky])[:, 1]
    full = lab[lab["purchased_at"] < x_end + pd.Timedelta(days=1)]
    a, b = train_test_split(full.index, test_size=0.2, random_state=42, stratify=full["is_late"])
    rnd = ml.make_hgb(m["hgb"]).fit(full.loc[a, ml.FEATURES], full.loc[a, "is_late"])
    p_rnd = rnd.predict_proba(full.loc[b, ml.FEATURES])[:, 1]
    res["experiments"] = {
        "Point-in-time features, future test months (reported)": res["test"]["Gradient boosting"]["pr_auc"],
        "Same model, random 80/20 split": round(float(ml.evaluate(full.loc[b, "is_late"], p_rnd, share)["pr_auc"]), 4),
        "Naive all-time aggregates (leaky)": round(float(ml.evaluate(y, p_leaky, share)["pr_auc"]), 4),
    }

    rng = np.random.default_rng(42)
    idx = rng.choice(len(test), size=min(12000, len(test)), replace=False)
    pi = permutation_importance(hgb, test[ml.FEATURES].iloc[idx], y[idx], scoring="average_precision",
                                n_repeats=5, random_state=42, n_jobs=-1)
    imp = pd.DataFrame({"feature": ml.FEATURES, "mean": pi.importances_mean, "std": pi.importances_std}
                       ).sort_values("mean", ascending=False)
    res["top_features"] = imp.head(8)["feature"].tolist()
    return res, {"y": y, "scores": scores, "importance": imp}


# ------------------------------------------------------------------ monitoring
def monitoring(con, cfg) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    share = cfg["ml"]["top_k_share"]
    feats = ml.load_features(con)
    preds = pd.read_sql("SELECT * FROM ml_predictions", con)
    d = preds.merge(feats[["order_id", "purchased_at", "is_late"] + ml.NUMERIC], on="order_id")
    d = d[(d["purchased_at"] <= pd.Timestamp(cfg["ml"]["monitor_until"]) + pd.Timedelta(days=1)) & d["is_late"].notna()]
    d["month"] = d["purchased_at"].dt.strftime("%Y-%m")
    rows = []
    for (policy, month), g in d.groupby(["policy", "month"]):
        rows.append({"policy": policy, "month": month, **ml.evaluate(g["is_late"], g["p_late"], share)})
    monthly = pd.DataFrame(rows)
    overall = {p: ml.evaluate(g["is_late"], g["p_late"], share) for p, g in d.groupby("policy")}
    # Ops flags the riskiest 10% of EACH month's orders, so per-month metrics are the operational view.
    per_month = monthly.groupby("policy")[["pr_auc", "roc_auc", "precision_at_k", "recall_at_k"]].mean().round(4)
    piv = monthly.pivot(index="month", columns="policy", values="pr_auc")
    wins = int((piv["monthly_retrain"] > piv["static"] + 1e-9).sum())
    ties = int((abs(piv["monthly_retrain"] - piv["static"]) <= 1e-9).sum())

    # Feature drift vs the static model's training data
    ref = ml.mature_labels(feats, pd.Timestamp(cfg["ml"]["first_train_cutoff"]))
    drift_feats = ["state_late_rate_prev_30d", "promised_days", "distance_km", "freight_ratio",
                   "seller_orders_prev_30d", "seller_prior_late_rate_smoothed"]
    live = d[d["policy"] == "static"]
    drift = pd.DataFrame([{"month": mo, "feature": f, "psi": ml.psi(ref[f].to_numpy(float), g[f].to_numpy(float))}
                          for mo, g in live.groupby("month") for f in drift_feats])
    return {"overall_pooled": overall,
            "mean_of_monthly": per_month.to_dict("index"),
            "retrain_wins_months": wins, "tied_months": ties, "n_months": int(len(piv)),
            "months": sorted(d["month"].unique().tolist()),
            "scored_orders": int(preds["order_id"].nunique()),
            "drift_alerts": drift[drift["psi"] > cfg["ml"]["psi_alert"]].round(3).to_dict("records")}, monthly, drift


# ------------------------------------------------------------------ figures
def figures(con, cfg, off, mon_monthly, drift):
    F = cfg["paths"]["figures_dir"]
    k = pd.read_sql("SELECT * FROM mart_monthly_kpis WHERE year_month BETWEEN '2017-01' AND '2018-08'", con)

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    a1.bar(k["year_month"], k["orders"], color=BLUE, width=0.7)
    a1.set_title("Orders per month")
    a2.plot(k["year_month"], k["late_rate"], color=ORANGE, marker="o", markersize=5)
    a2.set_title("Share of orders delivered after the promised date")
    _pct(a2)
    a2.tick_params(axis="x", rotation=60)
    _save(fig, F / "01_orders_and_late_rate.png")

    r = pd.read_sql("""SELECT is_late, review_score, COUNT(*) n FROM fact_orders
                       WHERE is_late IS NOT NULL AND review_score IS NOT NULL GROUP BY 1, 2""", con)
    fig, ax = plt.subplots(figsize=(8, 4.2))
    w = 0.38
    for i, (late, color, lab) in enumerate([(0, BLUE, "On time"), (1, ORANGE, "Late")]):
        s = r[r["is_late"] == late].set_index("review_score")["n"].reindex(range(1, 6), fill_value=0)
        ax.bar(np.arange(1, 6) + (i - 0.5) * (w + 0.02), s / s.sum(), width=w, color=color, label=lab)
    ax.set_xticks(range(1, 6))
    ax.set_xlabel("review score (stars)")
    ax.set_ylabel("share of reviews")
    _pct(ax)
    ax.legend(loc="upper center")
    ax.set_title("Late deliveries turn 5-star reviews into 1-star reviews")
    _save(fig, F / "02_reviews_late_vs_on_time.png")

    b = pd.read_sql("""SELECT b._batch_id AS batch,
                              SUM(CASE WHEN s.first_batch = b._batch_id THEN 1 ELSE 0 END) AS new_orders,
                              SUM(CASE WHEN s.first_batch <> b._batch_id THEN 1 ELSE 0 END) AS status_updates
                       FROM bronze_orders b JOIN silver_orders s USING (order_id) GROUP BY 1 ORDER BY 1""", con)
    fig, ax = plt.subplots(figsize=(9, 4.2))
    lbl = b["batch"].str.replace("batch_", "").str.replace("_", "-")
    ax.bar(lbl, b["new_orders"], color=BLUE, width=0.7, label="new orders")
    ax.bar(lbl, b["status_updates"], bottom=b["new_orders"] + 60, color=AQUA, width=0.7, label="status updates")
    ax.tick_params(axis="x", rotation=60)
    ax.legend(loc="upper left")
    ax.set_title("Order records per monthly batch: new orders vs late-arriving updates")
    _save(fig, F / "03_batch_composition.png")

    exp = off["experiments"]
    fig, ax = plt.subplots(figsize=(8.5, 3.6))
    labels = list(exp)[::-1]
    vals = [exp[x] for x in labels]
    colors = [ORANGE if "leaky" in x else (MUTED if "random" in x else BLUE) for x in labels]
    ax.barh(labels, vals, color=colors, height=0.6)
    for i, v in enumerate(vals):
        ax.text(v + 0.005, i, f"{v:.3f}", va="center", fontsize=9)
    ax.set_xlim(0, max(vals) * 1.18)
    ax.set_xlabel("PR AUC (late-delivery class)")
    ax.set_title("Same model, different feature pipeline / evaluation")
    ax.grid(axis="y", visible=False)
    _save(fig, F / "04_leakage_experiments.png")
    return F


def figures_ml(cfg, art, mon_monthly, drift, off):
    F = cfg["paths"]["figures_dir"]
    y = art["y"]
    fig, ax = plt.subplots(figsize=(7, 5))
    styles = {"Gradient boosting": (BLUE, "-"), "Logistic regression": (AQUA, "-"),
              "Heuristic: region's late rate, last 30 days": (ORANGE, "--"),
              "Heuristic: seller's past late rate": (MUTED, "--")}
    for name, p in art["scores"].items():
        pr, rc, _ = precision_recall_curve(y, p)
        c, ls = styles[name]
        ax.plot(rc, pr, color=c, ls=ls, label=f"{name} ({off['test'][name]['pr_auc']:.3f})")
    ax.axhline(y.mean(), color=INK2, lw=1, ls=":")
    ax.text(0.5, y.mean() - 0.015, f"base rate {y.mean():.3f} (random guessing)", ha="center", fontsize=8, color=INK2)
    ax.set(xlabel="recall", ylabel="precision", xlim=(0, 1), ylim=(0, 0.4),
           title="Precision-recall on future months (Mar-Jul 2018)")
    ax.legend(loc="upper right", fontsize=8)
    _save(fig, F / "05_precision_recall.png")

    imp = art["importance"].head(12).iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(imp["feature"], imp["mean"], xerr=imp["std"], color=BLUE, height=0.6,
            error_kw={"ecolor": INK2, "lw": 1})
    ax.set_xlabel("drop in PR AUC when the feature is shuffled")
    ax.set_title("Permutation importance (test months)")
    ax.grid(axis="y", visible=False)
    _save(fig, F / "06_permutation_importance.png")

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 6.5), sharex=True)
    for policy, color, lab in [("static", MUTED, "Trained once (Dec 2017)"),
                               ("monthly_retrain", BLUE, "Retrained every month")]:
        g = mon_monthly[mon_monthly["policy"] == policy]
        a1.plot(g["month"], g["recall_at_k"], color=color, marker="o", markersize=5, label=lab)
    a1.set_title("Share of late orders caught by flagging the riskiest 10%")
    _pct(a1)
    a1.set_ylim(0, 0.5)
    a1.legend(loc="upper left", ncol=2)
    g = mon_monthly[mon_monthly["policy"] == "static"]
    a2.bar(g["month"], g["late_rate"], color=ORANGE, width=0.6)
    a2.set_title("Actual late rate of scored orders")
    _pct(a2)
    _save(fig, F / "07_production_monitoring.png")

    fig, ax = plt.subplots(figsize=(9, 4.5))
    palette = [BLUE, ORANGE, AQUA, "#eda100", "#e87ba4", "#6250d6"]
    for (f, g), c in zip(drift.groupby("feature", sort=False), palette):
        ax.plot(g["month"], g["psi"], color=c, marker="o", markersize=4, label=f)
    ax.set_yscale("log")
    ax.axhline(cfg["ml"]["psi_alert"], color=INK2, lw=1, ls="--")
    ax.text(len(drift["month"].unique()) - 1, cfg["ml"]["psi_alert"] * 1.15, f"alert threshold ({cfg['ml']['psi_alert']})",
            color=INK2, fontsize=8, ha="right")
    ax.set_ylabel("PSI vs training data (log scale)")
    ax.set_title("Feature drift in production (population stability index)")
    ax.legend(fontsize=8, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    _save(fig, F / "08_feature_drift.png")


# ------------------------------------------------------------------ docs
def md_table(d: pd.DataFrame) -> str:
    head = "| " + " | ".join(map(str, d.columns)) + " |"
    sep = "|" + "|".join("---" for _ in d.columns) + "|"
    return "\n".join([head, sep] + ["| " + " | ".join(str(v) for v in r) + " |" for r in d.itertuples(index=False)])


def data_quality_doc(con, path):
    dq = pd.read_sql("""SELECT model, test, severity, SUM(1 - passed) AS batches_failed, COUNT(*) AS batches_run,
                               MAX(failures) AS max_failing_rows FROM meta_dq_results GROUP BY 1, 2, 3 ORDER BY 1, 2""", con)
    q = pd.read_sql("SELECT source_table, reason, COUNT(*) AS records FROM silver_quarantine GROUP BY 1, 2", con)
    b = pd.read_sql("SELECT batch_id, cutoff, rows_loaded, seconds FROM meta_batches ORDER BY 1", con)
    path.write_text("\n".join([
        "# Data quality report", "", "_Generated from `meta_dq_results`, `silver_quarantine` and `meta_batches`._", "",
        "## Tests across all batches", "", md_table(dq), "",
        "## Quarantined / repaired records", "", md_table(q), "",
        "## Batch loads", "", md_table(b), ""]))


def build_reports(cfg):
    con = connect(cfg["paths"]["warehouse"])
    log.info("offline study ...")
    off, art = offline_study(con, cfg)
    log.info("monitoring ...")
    mon, monthly, drift = monitoring(con, cfg)
    figures(con, cfg, off, monthly, drift)
    figures_ml(cfg, art, monthly, drift, off)
    monthly.to_csv(cfg["paths"]["reports_dir"] / "monitoring_monthly.csv", index=False)
    drift.round(4).to_csv(cfg["paths"]["reports_dir"] / "feature_drift.csv", index=False)
    art["importance"].round(5).to_csv(cfg["paths"]["reports_dir"] / "permutation_importance.csv", index=False)
    data_quality_doc(con, cfg["paths"]["docs_dir"] / "data_quality.md")
    wh = {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in
          ["bronze_orders", "silver_orders", "fact_orders", "fact_order_items", "dim_customer", "dim_seller",
           "dim_product", "silver_quarantine", "ml_features", "ml_predictions", "meta_model_registry"]}
    kpi = pd.read_sql("""SELECT ROUND(AVG(CASE WHEN is_late=1 THEN review_score END),2) late,
                                ROUND(AVG(CASE WHEN is_late=0 THEN review_score END),2) on_time
                         FROM fact_orders""", con).iloc[0].to_dict()
    out = {"warehouse_rows": wh, "avg_review": kpi, "offline": off, "production": mon,
           "batches": con.execute("SELECT COUNT(*) FROM meta_batches").fetchone()[0],
           "models_registered": pd.read_sql("SELECT policy, COUNT(*) n FROM meta_model_registry GROUP BY 1",
                                            con).set_index("policy")["n"].to_dict()}
    (cfg["paths"]["reports_dir"] / "metrics.json").write_text(json.dumps(out, indent=2, default=str))
    log.info("reports written")
    return out
