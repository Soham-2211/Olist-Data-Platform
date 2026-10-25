"""Orchestration CLI.

    python -m olist_platform.pipeline fetch      # download + verify raw files
    python -m olist_platform.pipeline land       # cut raw files into monthly drops
    python -m olist_platform.pipeline run        # replay every batch: bronze -> silver/gold/ml -> DQ -> train/score
    python -m olist_platform.pipeline evaluate   # offline model study + production monitoring report
    python -m olist_platform.pipeline all        # everything, from scratch

Each batch is processed exactly like a scheduled nightly job would be. Re-running
`run` is safe: already-loaded batches are skipped (or reloaded with --reload).
"""
from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path

import joblib
import pandas as pd

from . import bronze, ingest, ml, quality, runner
from .config import PROJECT_ROOT, get_logger, load_config
from .warehouse import connect

log = get_logger("pipeline")


def process_batch(con, cfg: dict, batch_id: str, reload: bool = False) -> dict:
    t0 = time.time()
    P = cfg["paths"]
    run_id = uuid.uuid4().hex[:8]
    if reload or batch_id not in bronze.loaded_batches(con):
        bronze.load_batch(con, P["landing_dir"] / batch_id)
    runner.run_models(con, P["sql_dir"], P["seeds_dir"], run_id, batch_id)
    dq = quality.run_tests(con, PROJECT_ROOT / "quality" / "tests.yaml", batch_id)

    out = {"batch_id": batch_id, "run_id": run_id, "dq_failed_warn": sum(1 for r in dq if not r["passed"])}
    cutoff = pd.Timestamp(con.execute("SELECT cutoff FROM meta_batches WHERE batch_id=?", (batch_id,)).fetchone()[0])
    mcfg = cfg["ml"]
    if cutoff >= pd.Timestamp(mcfg["first_train_cutoff"]):
        df = ml.load_features(con)
        for policy in ("static", "monthly_retrain"):
            # 1) Score this batch's new orders with the model that existed BEFORE the batch.
            #    In production these orders were scored the moment they were placed, so a
            #    model trained at this month-end (which may have seen some of their outcomes)
            #    must never score them.
            version = _latest_version(con, policy)
            if version:
                model = joblib.load(P["models_dir"] / policy / f"{version}.joblib")["model"]
                out[f"scored_{policy}"] = ml.score_batch(con, model, df, batch_id, version, policy)
            # 2) Then (re)train on labels that have matured by this cutoff, for next month.
            if version is None or policy == "monthly_retrain":
                model, train = ml.train_at_cutoff(df, cutoff, mcfg["hgb"], cfg.get("seed", 42))
                if len(train) >= mcfg["min_train_rows"]:
                    ml.register(con, P["models_dir"], model, f"{cutoff:%Y%m%d}", policy, train,
                                {"cutoff": str(cutoff.date()), "batch_id": batch_id})
    out["seconds"] = round(time.time() - t0, 1)
    log.info("batch %s done in %.1fs %s", batch_id, out["seconds"],
             {k: v for k, v in out.items() if k.startswith("scored")})
    return out


def _latest_version(con, policy: str):
    try:
        r = con.execute("SELECT MAX(version) FROM meta_model_registry WHERE policy=?", (policy,)).fetchone()
        return r[0]
    except Exception:
        return None


def cmd_run(cfg: dict, reload: bool = False, limit: int | None = None) -> list[dict]:
    con = connect(cfg["paths"]["warehouse"])
    batches = ingest.list_batches(cfg)[:limit]
    results = [process_batch(con, cfg, b, reload) for b in batches]
    (cfg["paths"]["docs_dir"] / "lineage.md").write_text(
        "# Model lineage\n\n_Generated from the `{{ ref() }}` graph in `sql/`._\n\n"
        + runner.lineage_mermaid(cfg["paths"]["sql_dir"]) + "\n")
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["fetch", "land", "run", "evaluate", "all"])
    ap.add_argument("--reload", action="store_true", help="reload batches already in bronze")
    ap.add_argument("--limit", type=int, default=None, help="only process the first N batches")
    a = ap.parse_args(argv)
    cfg = load_config()
    if a.command in ("fetch", "all"):
        ingest.fetch_source(cfg)
    if a.command in ("land", "all"):
        ingest.simulate_batches(cfg)
    if a.command == "all":
        wh = cfg["paths"]["warehouse"]
        for suffix in ("", "-wal", "-shm"):
            Path(str(wh) + suffix).unlink(missing_ok=True)
        for f in cfg["paths"]["models_dir"].glob("*/*.joblib"):
            f.unlink()
    if a.command in ("run", "all"):
        res = cmd_run(cfg, a.reload, a.limit)
        (cfg["paths"]["reports_dir"] / "batch_runs.json").write_text(json.dumps(res, indent=2))
    if a.command in ("evaluate", "all"):
        from .report import build_reports
        build_reports(cfg)


if __name__ == "__main__":
    main()
