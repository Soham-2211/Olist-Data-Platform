"""Declarative data-quality tests (dbt-test style) defined in quality/tests.yaml.

Every test compiles to a SQL query returning the number of failing rows.
Tests run after each batch; results are kept in meta_dq_results, so data quality
can be tracked over time, not just pass/fail today.
  severity: error -> pipeline stops before ML consumes the data
  severity: warn  -> logged and reported, pipeline continues
"""
from __future__ import annotations

import time
from pathlib import Path

import yaml

from .config import get_logger

log = get_logger("quality")


class DataQualityError(RuntimeError):
    pass


def compile_test(model: str, test: dict) -> tuple[str, str]:
    kind = next(k for k in test if k not in ("severity", "name"))
    arg = test[kind]
    if kind == "not_null":
        cols = arg if isinstance(arg, list) else [arg]
        cond = " OR ".join(f'"{c}" IS NULL' for c in cols)
        return f"not_null({', '.join(cols)})", f'SELECT COUNT(*) FROM "{model}" WHERE {cond}'
    if kind == "unique":
        cols = arg if isinstance(arg, list) else [arg]
        key = ", ".join(f'"{c}"' for c in cols)
        return (f"unique({', '.join(cols)})",
                f'SELECT COALESCE(SUM(n - 1), 0) FROM (SELECT COUNT(*) n FROM "{model}" GROUP BY {key} HAVING n > 1)')
    if kind == "accepted_values":
        vals = ", ".join(f"'{v}'" for v in arg["values"])
        return (f"accepted_values({arg['column']})",
                f'SELECT COUNT(*) FROM "{model}" WHERE "{arg["column"]}" IS NOT NULL AND "{arg["column"]}" NOT IN ({vals})')
    if kind == "relationships":
        return (f"relationships({arg['column']} -> {arg['to']}.{arg['field']})",
                f'SELECT COUNT(*) FROM "{model}" a WHERE a."{arg["column"]}" IS NOT NULL AND NOT EXISTS '
                f'(SELECT 1 FROM "{arg["to"]}" b WHERE b."{arg["field"]}" = a."{arg["column"]}")')
    if kind == "range":
        conds = []
        if "min" in arg:
            conds.append(f'"{arg["column"]}" < {arg["min"]}')
        if "max" in arg:
            conds.append(f'"{arg["column"]}" > {arg["max"]}')
        return f"range({arg['column']})", f'SELECT COUNT(*) FROM "{model}" WHERE {" OR ".join(conds)}'
    if kind == "expression_is_true":
        return f"expression({arg})", f'SELECT COUNT(*) FROM "{model}" WHERE NOT ({arg})'
    if kind == "row_count_min":
        return f"row_count_min({arg})", f'SELECT CASE WHEN COUNT(*) < {arg} THEN 1 ELSE 0 END FROM "{model}"'
    raise ValueError(f"unknown test type {kind}")


def run_tests(con, tests_path: Path, batch_id: str, raise_on_error: bool = True) -> list[dict]:
    con.execute("""CREATE TABLE IF NOT EXISTS meta_dq_results (
        batch_id TEXT, model TEXT, test TEXT, severity TEXT, failures INTEGER, passed INTEGER, ran_at TEXT)""")
    spec = yaml.safe_load(tests_path.read_text())
    ran_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    results = []
    for model, tests in spec["models"].items():
        for test in tests:
            name, sql = compile_test(model, test)
            name = test.get("name", name)
            failures = con.execute(sql).fetchone()[0]
            sev = test.get("severity", "error")
            results.append({"batch_id": batch_id, "model": model, "test": name, "severity": sev,
                            "failures": failures, "passed": int(failures == 0), "ran_at": ran_at})
    con.execute("DELETE FROM meta_dq_results WHERE batch_id = ?", (batch_id,))
    con.executemany("INSERT INTO meta_dq_results VALUES (:batch_id,:model,:test,:severity,:failures,:passed,:ran_at)",
                    results)
    errors = [r for r in results if not r["passed"] and r["severity"] == "error"]
    warns = [r for r in results if not r["passed"] and r["severity"] == "warn"]
    for w in warns:
        log.warning("%s: %s %s -> %s rows", batch_id, w["model"], w["test"], w["failures"])
    if errors and raise_on_error:
        msg = "; ".join(f"{e['model']}.{e['test']}={e['failures']}" for e in errors)
        raise DataQualityError(f"{batch_id}: {msg}")
    log.info("%s: %d/%d tests passed (%d warnings)", batch_id,
             sum(r["passed"] for r in results), len(results), len(warns))
    return results
