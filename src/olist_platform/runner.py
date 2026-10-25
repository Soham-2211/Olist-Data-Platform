"""A small dbt-style SQL model runner.

Each file in sql/<layer>/<model>.sql is one model. Models reference each other
with {{ ref('model_name') }}; the runner parses those references into a DAG,
runs models in topological order, and builds each one atomically
(build into a temp table, then swap in a single transaction), so a failed run
never leaves a half-built table behind. Optional header comments:

    -- description: one line shown in the lineage docs
    -- indexes: col_a; col_b, col_c
"""
from __future__ import annotations

import csv
import re
import time
from dataclasses import dataclass, field
from graphlib import TopologicalSorter
from pathlib import Path

from .config import get_logger
from .warehouse import row_count

log = get_logger("runner")
REF = re.compile(r"\{\{\s*ref\(\s*'([a-z0-9_]+)'\s*\)\s*\}\}")
VAR = re.compile(r"\{\{\s*var\(\s*'([a-z0-9_]+)'\s*\)\s*\}\}")


@dataclass
class Model:
    name: str
    layer: str
    path: Path
    sql: str
    refs: set[str] = field(default_factory=set)
    description: str = ""
    indexes: list[str] = field(default_factory=list)


def discover(sql_dir: Path) -> dict[str, Model]:
    models = {}
    for path in sorted(sql_dir.glob("*/*.sql")):
        text = path.read_text()
        m = Model(path.stem, path.parent.name, path, text, set(REF.findall(text)))
        for line in text.splitlines():
            if line.startswith("-- description:"):
                m.description = line.split(":", 1)[1].strip()
            if line.startswith("-- indexes:"):
                m.indexes = [s.strip() for s in line.split(":", 1)[1].split(";") if s.strip()]
        if m.name in models:
            raise ValueError(f"duplicate model name {m.name}")
        models[m.name] = m
    return models


def execution_order(models: dict[str, Model], sources: set[str]) -> list[str]:
    graph = {}
    for m in models.values():
        unknown = m.refs - set(models) - sources
        if unknown:
            raise ValueError(f"{m.name} references unknown models/sources: {sorted(unknown)}")
        graph[m.name] = m.refs & set(models)
    return list(TopologicalSorter(graph).static_order())


def compile_sql(m: Model, variables: dict) -> str:
    sql = REF.sub(lambda x: f'"{x.group(1)}"', m.sql)
    return VAR.sub(lambda x: str(variables[x.group(1)]), sql)


def load_seeds(con, seeds_dir: Path) -> set[str]:
    names = set()
    for path in sorted(seeds_dir.glob("*.csv")):
        name = f"seed_{path.stem}"
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        cols = rows[0]
        con.execute("BEGIN")
        con.execute(f'DROP TABLE IF EXISTS "{name}"')
        con.execute(f'CREATE TABLE "{name}" ({", ".join(chr(34) + c + chr(34) + " TEXT" for c in cols)})')
        con.executemany(f'INSERT INTO "{name}" VALUES ({", ".join("?" * len(cols))})', rows[1:])
        con.execute("COMMIT")
        names.add(name)
    return names


def ensure_meta(con) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS meta_model_runs (
        run_id TEXT, batch_id TEXT, model TEXT, layer TEXT, status TEXT, rows INTEGER,
        seconds REAL, started_at TEXT, error TEXT)""")


def run_models(con, sql_dir: Path, seeds_dir: Path, run_id: str, batch_id: str,
               variables: dict | None = None, select_layers: tuple[str, ...] | None = None) -> list[dict]:
    ensure_meta(con)
    sources = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    sources |= load_seeds(con, seeds_dir)
    models = discover(sql_dir)
    results = []
    for name in execution_order(models, sources):
        m = models[name]
        if select_layers and m.layer not in select_layers:
            continue
        t0, started = time.time(), time.strftime("%Y-%m-%dT%H:%M:%S")
        sql = compile_sql(m, variables or {})
        tmp = f"{name}__building"
        try:
            con.execute(f'DROP TABLE IF EXISTS "{tmp}"')
            con.execute(f'CREATE TABLE "{tmp}" AS {sql}')
            con.execute("BEGIN")
            con.execute(f'DROP TABLE IF EXISTS "{name}"')
            con.execute(f'ALTER TABLE "{tmp}" RENAME TO "{name}"')
            for i, cols in enumerate(m.indexes):
                con.execute(f'CREATE INDEX "ix_{name}_{i}" ON "{name}" ({cols})')
            con.execute("COMMIT")
            n, status, err = row_count(con, name), "success", None
        except Exception as e:  # record, then re-raise: downstream models must not run on stale inputs
            if con.in_transaction:
                con.execute("ROLLBACK")
            n, status, err = None, "error", str(e)
            con.execute("INSERT INTO meta_model_runs VALUES (?,?,?,?,?,?,?,?,?)",
                        (run_id, batch_id, name, m.layer, status, n, round(time.time() - t0, 3), started, err))
            log.error("model %s failed: %s", name, e)
            raise
        secs = round(time.time() - t0, 3)
        con.execute("INSERT INTO meta_model_runs VALUES (?,?,?,?,?,?,?,?,?)",
                    (run_id, batch_id, name, m.layer, status, n, secs, started, None))
        results.append({"model": name, "layer": m.layer, "rows": n, "seconds": secs})
    return results


def lineage_mermaid(sql_dir: Path) -> str:
    models = discover(sql_dir)
    lines = ["```mermaid", "flowchart LR"]
    layers = {}
    for m in models.values():
        layers.setdefault(m.layer, []).append(m.name)
        for r in sorted(m.refs):
            lines.append(f"    {r} --> {m.name}")
    for layer in ["silver", "gold", "ml"]:
        if layer in layers:
            lines.append(f"    subgraph {layer.upper()}")
            lines += [f"        {n}" for n in sorted(layers[layer])]
            lines.append("    end")
    lines.append("```")
    return "\n".join(lines)
