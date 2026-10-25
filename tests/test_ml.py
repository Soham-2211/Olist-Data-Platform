import numpy as np
import pandas as pd

from olist_platform import ml


def test_mature_labels_uses_promise_date_not_delivery():
    df = pd.DataFrame({
        "order_id": ["a", "b", "c", "d", "e"],
        "order_status": ["delivered", "shipped", "delivered", "delivered", "canceled"],
        "estimated_delivery_date": pd.to_datetime(["2018-01-10", "2018-01-10", "2018-01-10", "2018-02-20", "2018-01-10"]),
        "delivered_at": pd.to_datetime(["2018-01-09", None, "2018-01-12", "2018-01-30", None]),
    })
    out = ml.mature_labels(df, pd.Timestamp("2018-01-31")).set_index("order_id")["label"]
    assert out.to_dict() == {"a": 0, "b": 1, "c": 1}   # d: promise not yet due; e: canceled


def test_delivery_after_cutoff_counts_as_late():
    df = pd.DataFrame({"order_id": ["a"], "order_status": ["delivered"],
                       "estimated_delivery_date": pd.to_datetime(["2018-01-10"]),
                       "delivered_at": pd.to_datetime(["2018-02-05"])})
    assert ml.mature_labels(df, pd.Timestamp("2018-01-31"))["label"].tolist() == [1]


def test_top_k_and_psi():
    y = np.array([1, 0, 0, 0, 1, 0, 0, 0, 0, 0])
    p = np.array([.9, .1, .2, .1, .8, .1, .1, .3, .2, .1])
    m = ml.top_k_metrics(y, p, 0.2)
    assert m["precision_at_k"] == 1.0 and m["recall_at_k"] == 1.0
    rng = np.random.default_rng(0)
    a = rng.normal(size=5000)
    assert ml.psi(a, rng.normal(size=5000)) < 0.02
    assert ml.psi(a, rng.normal(1.5, 1, size=5000)) > 0.5


def test_feature_list_has_no_label_or_leaky_columns():
    banned = {"is_late", "delay_days", "delivered_at", "label", "order_status"} | set(ml.LEAKY)
    assert not banned & set(ml.FEATURES)
