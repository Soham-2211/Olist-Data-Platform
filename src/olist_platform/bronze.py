"""Bronze layer: land each batch verbatim, with lineage columns.

Guarantees
- Idempotent: re-loading a batch replaces exactly that batch's rows (delete + insert
  in one transaction), so retries and backfills never create duplicates.
- Integrity: every landed file is checked against the batch manifest's checksum.
- Schema contract: a source file with missing or unexpected columns is rejected
  before anything is written (schema drift fails loudly instead of corrupting data).
"""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from .config import get_logger
from .ingest import sha256

log = get_logger("bronze")

EXPECTED_COLUMNS = {
    "orders": ["order_id", "customer_id", "order_status", "order_purchase_timestamp", "order_approved_at",
               "order_delivered_carrier_date", "order_delivered_customer_date", "order_estimated_delivery_date"],
    "order_items": ["order_id", "order_item_id", "product_id", "seller_id", "shipping_limit_date", "price",
                    "freight_value"],
    "order_payments": ["order_id", "payment_sequential", "payment_type", "payment_installments", "payment_value"],
    "order_reviews": ["review_id", "order_id", "review_score", "review_comment_title", "review_comment_message",
                      "review_creation_date", "review_answer_timestamp"],
    "customers": ["customer_id", "customer_unique_id", "customer_zip_code_prefix", "customer_city",
                  "customer_state"],
    "sellers": ["seller_id", "seller_zip_code_prefix", "seller_city", "seller_state"],
    "products": ["product_id", "product_category_name", "product_name_lenght", "product_description_lenght",
                 "product_photos_qty", "product_weight_g", "product_length_cm", "product_height_cm",
                 "product_width_cm"],
    "geolocation": ["geolocation_zip_code_prefix", "geolocation_lat", "geolocation_lng", "geolocation_city",
                    "geolocation_state"],
    "category_translation": ["product_category_name", "product_category_name_english"],
}
META_COLS = ["_batch_id", "_source_file", "_row_num", "_loaded_at"]


class SchemaDriftError(ValueError):
    pass


def ensure_meta(con) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS meta_batches (
        batch_id TEXT PRIMARY KEY, cutoff TEXT, loaded_at TEXT, rows_loaded INTEGER, seconds REAL)""")


def _ensure_table(con, table: str, cols: list[str]) -> None:
    ddl = ", ".join(f'"{c}" TEXT' for c in cols + META_COLS)
    con.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({ddl})')
    con.execute(f'CREATE INDEX IF NOT EXISTS "ix_{table}_batch" ON "{table}" (_batch_id)')


def load_batch(con, batch_dir: Path) -> int:
    ensure_meta(con)
    manifest = json.loads((batch_dir / "_manifest.json").read_text())
    bid = manifest["batch_id"]
    t0 = time.time()
    loaded_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    # Validate everything before writing anything.
    files = {}
    for name, meta in manifest["tables"].items():
        path = batch_dir / f"{name}.csv"
        if sha256(path) != meta["sha256"]:
            raise ValueError(f"{bid}/{name}.csv does not match its manifest checksum")
        with open(path, newline="", encoding="utf-8-sig") as f:
            header = next(csv.reader(f))
        if header != EXPECTED_COLUMNS[name]:
            missing = set(EXPECTED_COLUMNS[name]) - set(header)
            extra = set(header) - set(EXPECTED_COLUMNS[name])
            raise SchemaDriftError(f"{bid}/{name}: missing={sorted(missing)} unexpected={sorted(extra)}")
        files[name] = path

    total = 0
    con.execute("BEGIN")
    try:
        for name, path in files.items():
            table = f"bronze_{name}"
            cols = EXPECTED_COLUMNS[name]
            _ensure_table(con, table, cols)
            con.execute(f'DELETE FROM "{table}" WHERE _batch_id = ?', (bid,))
            ph = ", ".join("?" * (len(cols) + len(META_COLS)))
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                next(reader)
                rows = ((*r, bid, path.name, i, loaded_at) for i, r in enumerate(reader, 1))
                cur = con.executemany(f'INSERT INTO "{table}" VALUES ({ph})', rows)
                total += cur.rowcount
            if cur.rowcount != manifest["tables"][name]["rows"]:
                raise ValueError(f"{bid}/{name}: loaded {cur.rowcount} rows, manifest says "
                                 f"{manifest['tables'][name]['rows']}")
        con.execute("INSERT OR REPLACE INTO meta_batches VALUES (?, ?, ?, ?, ?)",
                    (bid, manifest["cutoff"], loaded_at, total, round(time.time() - t0, 2)))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    log.info("%s: %s rows -> bronze (%.1fs)", bid, f"{total:,}", time.time() - t0)
    return total


def loaded_batches(con) -> list[str]:
    ensure_meta(con)
    return [r[0] for r in con.execute("SELECT batch_id FROM meta_batches ORDER BY batch_id")]
