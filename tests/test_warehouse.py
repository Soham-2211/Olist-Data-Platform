from pathlib import Path

import pandas as pd
import pytest

from olist_platform import bronze, quality, runner
from olist_platform.warehouse import connect, haversine_km, norm_city

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def built(cfg, batches):
    con = connect(cfg["paths"]["warehouse"])
    for b in batches:
        bronze.load_batch(con, cfg["paths"]["landing_dir"] / b)
    runner.run_models(con, cfg["paths"]["sql_dir"], cfg["paths"]["seeds_dir"], "t", batches[-1])
    return con


def q(con, sql):
    return pd.read_sql(sql, con)


def test_udfs():
    assert norm_city("São-Paulo ") == "sao paulo"
    assert norm_city("sa£o paulo") == "sao paulo"
    assert haversine_km(-23.55, -46.63, -22.91, -43.17) == pytest.approx(360, abs=10)  # SP -> Rio


def test_dag_order_and_unknown_ref(tmp_path):
    models = runner.discover(ROOT / "sql")
    order = runner.execution_order(models, sources={f"bronze_{t}" for t in bronze.EXPECTED_COLUMNS}
                                   | {"seed_category_translation_overrides"})
    assert order.index("silver_orders") < order.index("fact_orders") < order.index("ml_features")
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "m.sql").write_text("SELECT * FROM {{ ref('does_not_exist') }}")
    with pytest.raises(ValueError, match="unknown"):
        runner.execution_order(runner.discover(tmp_path), set())


def test_failed_model_keeps_previous_table(cfg, built, tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "fact_orders.sql").write_text("SELECT broken syntax here")
    before = q(built, "SELECT COUNT(*) n FROM fact_orders")["n"][0]
    with pytest.raises(Exception):
        runner.run_models(built, tmp_path, cfg["paths"]["seeds_dir"], "t2", "b")
    assert q(built, "SELECT COUNT(*) n FROM fact_orders")["n"][0] == before


def test_latest_version_of_each_order_wins(built):
    o = q(built, "SELECT order_id, order_status, n_versions FROM silver_orders ORDER BY order_id")
    assert (o["order_status"] == "delivered").all()
    assert o.set_index("order_id").loc["O1", "n_versions"] == 1   # placed and delivered within January
    assert len(o) == 4


def test_silver_repairs(built):
    o3 = q(built, "SELECT * FROM silver_orders WHERE order_id='O3'").iloc[0]
    assert o3["carrier_at"] is None and o3["flag_carrier_before_purchase"] == 1
    p = q(built, "SELECT * FROM silver_payments WHERE order_id='O3'").iloc[0]
    assert p["payment_type"] is None and p["installments"] == 1
    prod = q(built, "SELECT * FROM silver_products ORDER BY product_id")
    assert prod["category"].tolist() == ["pc_gamer", "unknown"]       # seed override + missing category
    assert pd.isna(prod["weight_g"].iloc[1])                           # weight 0 -> NULL
    geo = q(built, "SELECT * FROM silver_geolocation ORDER BY zip_prefix")
    assert geo["n_points"].tolist() == [1, 1]                         # dupes + Lisbon point removed
    assert geo["city"].tolist() == ["sao paulo", "sao paulo"]
    r = q(built, "SELECT * FROM silver_reviews WHERE order_id='O1'")
    assert len(r) == 1 and r["review_id"][0] == "R1"


def test_customer_identity_and_geo_fallback(built):
    d = q(built, "SELECT * FROM dim_customer ORDER BY customer_unique_id").set_index("customer_unique_id")
    assert d.loc["U1", "n_orders"] == 2                                # C1 and C3 are the same person
    assert d.loc["U3", "geo_source"] == "city"


def test_point_in_time_features(built):
    f = q(built, "SELECT * FROM ml_features ORDER BY order_id").set_index("order_id")
    # O3 placed Mar 1: only O1 (late) and O2 (on time) had been delivered
    assert f.loc["O3", "seller_prior_deliveries"] == 2
    assert f.loc["O3", "seller_prior_late_rate_smoothed"] == pytest.approx((1 + 1) / (2 + 15))
    # O4 placed Mar 2: O3 not delivered until Mar 15, so still only 2
    assert f.loc["O4", "seller_prior_deliveries"] == 2
    assert f.loc["O1", "seller_prior_deliveries"] == 0
    assert f.loc["O1", "is_late"] == 1 and f.loc["O2", "is_late"] == 0
    assert f.loc["O3", "customer_prior_orders"] == 1


def test_leaky_features_really_leak(built):
    leaky = q(built, "SELECT * FROM ml_leaky_features WHERE order_id='O1'").iloc[0]
    assert leaky["leaky_seller_deliveries"] == 4                       # sees the future


def test_quality_suite_runs_and_catches_violations(built, cfg):
    res = quality.run_tests(built, ROOT / "quality" / "tests.yaml", "t", raise_on_error=False)
    errors = [r for r in res if not r["passed"] and r["severity"] == "error"]
    assert not errors, errors
    built.execute("UPDATE silver_orders SET order_status = 'teleported' WHERE order_id = 'O1'")
    with pytest.raises(quality.DataQualityError):
        quality.run_tests(built, ROOT / "quality" / "tests.yaml", "t")


def test_lineage_doc():
    md = runner.lineage_mermaid(ROOT / "sql")
    assert "silver_orders --> fact_orders" in md


def test_facts_use_the_address_on_each_order(built):
    o = q(built, "SELECT order_id, ship_zip_prefix, ship_lat FROM fact_orders ORDER BY order_id").set_index("order_id")
    assert o.loc["O4", "ship_zip_prefix"] == "99999" and o.loc["O4", "ship_lat"] is not None  # city fallback
    i = q(built, "SELECT order_id, distance_km FROM fact_order_items").set_index("order_id")
    assert i.loc["O1", "distance_km"] < 5                                  # seller and customer in same district
