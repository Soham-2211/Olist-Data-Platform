import json

import pandas as pd
import pytest

from olist_platform import bronze, ingest
from olist_platform.warehouse import connect, row_count


def test_simulation_reconciles_with_source(cfg, batches):
    assert batches == ["batch_2017_01", "batch_2017_02", "batch_2017_03", "batch_2017_04"]
    landing = cfg["paths"]["landing_dir"]
    for table in ["order_items", "order_payments", "customers", "order_reviews", "products", "sellers"]:
        total = sum(json.loads((landing / b / "_manifest.json").read_text())["tables"][table]["rows"]
                    for b in batches)
        src = len(pd.read_csv(cfg["paths"]["source_dir"] / f"{table}.csv", dtype=str))
        assert total == src, table


def test_orders_reappear_when_status_changes(cfg, batches):
    landing = cfg["paths"]["landing_dir"]
    o1 = [pd.read_csv(landing / b / "orders.csv", dtype=str, keep_default_na=False).query("order_id == 'O1'")
          for b in batches]
    assert len(o1[0]) == 1 and o1[0].iloc[0]["order_status"] == "delivered"
    o3 = pd.read_csv(landing / "batch_2017_03" / "orders.csv", dtype=str, keep_default_na=False)
    assert set(o3["order_id"]) == {"O3", "O4"}


def test_future_fields_hidden_at_cutoff(cfg):
    orders = pd.read_csv(cfg["paths"]["source_dir"] / "orders.csv", dtype=str, keep_default_na=False)
    ts = {c: pd.to_datetime(orders[c].replace("", None)) for c in ingest.ORDER_TS}
    v = ingest.order_view(orders, ts, pd.Timestamp("2017-01-20"))
    o1 = v[v["order_id"] == "O1"].iloc[0]
    assert o1["order_status"] == "shipped" and o1["order_delivered_customer_date"] == ""


def test_zip_leading_zero_preserved(cfg, batches):
    c = pd.read_csv(cfg["paths"]["landing_dir"] / batches[0] / "customers.csv", dtype=str)
    assert c["customer_zip_code_prefix"].iloc[0] == "01037"


def test_bronze_load_is_idempotent(cfg, batches):
    con = connect(cfg["paths"]["warehouse"])
    b = cfg["paths"]["landing_dir"] / batches[0]
    bronze.load_batch(con, b)
    n = row_count(con, "bronze_orders")
    bronze.load_batch(con, b)
    assert row_count(con, "bronze_orders") == n
    assert bronze.loaded_batches(con) == [batches[0]]


def test_schema_drift_rejected_before_any_write(cfg, batches):
    con = connect(cfg["paths"]["warehouse"])
    b = cfg["paths"]["landing_dir"] / batches[0]
    path = b / "sellers.csv"
    df = pd.read_csv(path, dtype=str).rename(columns={"seller_state": "state"})
    df.to_csv(path, index=False)
    m = json.loads((b / "_manifest.json").read_text())
    m["tables"]["sellers"]["sha256"] = ingest.sha256(path)
    (b / "_manifest.json").write_text(json.dumps(m))
    with pytest.raises(bronze.SchemaDriftError):
        bronze.load_batch(con, b)
    assert bronze.loaded_batches(con) == []


def test_tampered_file_rejected(cfg, batches):
    con = connect(cfg["paths"]["warehouse"])
    b = cfg["paths"]["landing_dir"] / batches[0]
    with open(b / "orders.csv", "a") as f:
        f.write("X,Y,delivered,2017-01-01,,,,2017-01-10\n")
    with pytest.raises(ValueError, match="checksum"):
        bronze.load_batch(con, b)
