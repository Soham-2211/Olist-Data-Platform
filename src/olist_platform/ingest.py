"""Source acquisition and batch simulation.

1. `fetch_source` downloads the raw files from a pinned commit and verifies
   SHA-256 checksums, so a silently changed upstream file can never slip in.
2. `simulate_batches` replays the static Olist dump as the monthly drops a real
   operational system would send. Each order appears in the drop where it was
   placed and again in every later drop where its status changed, with fields
   that were unknown at that time left blank. Downstream layers therefore have
   to handle late-arriving updates, exactly as in production.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import urllib.request
from pathlib import Path

import pandas as pd

from .config import get_logger

log = get_logger("ingest")

ORDER_TS = ["order_approved_at", "order_delivered_carrier_date", "order_delivered_customer_date"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_source(cfg: dict) -> None:
    src = cfg["paths"]["source_dir"]
    for name, spec in cfg["source"]["files"].items():
        path = src / spec["file"]
        if path.exists() and sha256(path) == spec["sha256"]:
            continue
        url = f"{cfg['source']['base_url']}/{spec['file']}"
        log.info("downloading %s", url)
        tmp = path.with_suffix(".part")
        with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        if sha256(tmp) != spec["sha256"]:
            tmp.unlink()
            raise ValueError(f"checksum mismatch for {spec['file']}: upstream file changed")
        tmp.rename(path)
    log.info("source verified: %d files", len(cfg["source"]["files"]))


def _read(cfg: dict, name: str) -> pd.DataFrame:
    # Everything as text: zip prefixes like "01037" must keep their leading zero.
    return pd.read_csv(cfg["paths"]["source_dir"] / cfg["source"]["files"][name]["file"],
                       dtype=str, keep_default_na=False, encoding="utf-8-sig")


def month_ends(first: str, last: str) -> list[pd.Timestamp]:
    return list(pd.date_range(first, last, freq="ME"))


def order_view(orders: pd.DataFrame, ts: dict, cutoff: pd.Timestamp) -> pd.DataFrame:
    """What the source system would have exported for each order at `cutoff`."""
    end = cutoff + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    v = orders.copy()
    for c in ORDER_TS:
        v.loc[~(ts[c] <= end), c] = ""
    final = orders["order_status"]
    progress = final.isin(["delivered", "shipped"])
    status = final.copy()
    status[progress & (v["order_approved_at"] != "")] = "approved"
    status[progress & (v["order_approved_at"] == "")] = "created"
    status[progress & (v["order_delivered_carrier_date"] != "")] = "shipped"
    status[(final == "delivered") & (v["order_delivered_customer_date"] != "")] = "delivered"
    v["order_status"] = status
    return v


def simulate_batches(cfg: dict) -> list[str]:
    landing = cfg["paths"]["landing_dir"]
    t = {n: _read(cfg, n) for n in cfg["source"]["files"]}
    orders = t["orders"]
    purchased = pd.to_datetime(orders["order_purchase_timestamp"])
    ts = {c: pd.to_datetime(orders[c].replace("", None)) for c in ORDER_TS}
    review_ts = pd.to_datetime(t["order_reviews"]["review_answer_timestamp"])

    cutoffs = month_ends(cfg["simulation"]["first_cutoff"], cfg["simulation"]["last_cutoff"])
    prev_view, prev_end = None, pd.Timestamp.min
    seen_products: set[str] = set()
    seen_sellers: set[str] = set()
    batch_ids = []
    for i, cutoff in enumerate(cutoffs):
        end = cutoff + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        last = i == len(cutoffs) - 1
        bid = f"batch_{cutoff:%Y_%m}"
        out = landing / bid
        out.mkdir(parents=True, exist_ok=True)

        view = order_view(orders, ts, cutoff)
        placed = purchased <= end
        new = placed & (purchased > prev_end)
        changed = placed & ~new
        if prev_view is not None:
            changed &= (view[["order_status", *ORDER_TS]] != prev_view[["order_status", *ORDER_TS]]).any(axis=1)
        drop = {"orders": view[new | changed]}
        new_ids = set(orders.loc[new, "order_id"])
        drop["order_items"] = t["order_items"][t["order_items"]["order_id"].isin(new_ids)]
        drop["order_payments"] = t["order_payments"][t["order_payments"]["order_id"].isin(new_ids)]
        new_customers = set(orders.loc[new, "customer_id"])
        drop["customers"] = t["customers"][t["customers"]["customer_id"].isin(new_customers)]
        rv = (review_ts > prev_end) & ((review_ts <= end) | last)
        drop["order_reviews"] = t["order_reviews"][rv]

        items = drop["order_items"]
        p_new = set(items["product_id"]) - seen_products
        s_new = set(items["seller_id"]) - seen_sellers
        if i == 0:  # reference data + catalogue entries never referenced by an order
            drop["geolocation"] = t["geolocation"]
            drop["category_translation"] = t["category_translation"]
            p_new |= set(t["products"]["product_id"]) - set(t["order_items"]["product_id"])
            s_new |= set(t["sellers"]["seller_id"]) - set(t["order_items"]["seller_id"])
        drop["products"] = t["products"][t["products"]["product_id"].isin(p_new)]
        drop["sellers"] = t["sellers"][t["sellers"]["seller_id"].isin(s_new)]
        seen_products |= p_new
        seen_sellers |= s_new

        manifest = {"batch_id": bid, "cutoff": str(cutoff.date()), "tables": {}}
        for name, df in drop.items():
            df.to_csv(out / f"{name}.csv", index=False)
            manifest["tables"][name] = {"rows": len(df), "sha256": sha256(out / f"{name}.csv")}
        (out / "_manifest.json").write_text(json.dumps(manifest, indent=2))
        batch_ids.append(bid)
        prev_view, prev_end = view, end
    log.info("simulated %d batches into %s", len(batch_ids), landing)
    return batch_ids


def list_batches(cfg: dict) -> list[str]:
    return sorted(p.name for p in cfg["paths"]["landing_dir"].glob("batch_*") if (p / "_manifest.json").exists())
