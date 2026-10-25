from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_config(path: str | Path | None = None, root: Path | None = None) -> dict[str, Any]:
    root = Path(root) if root else PROJECT_ROOT
    with open(Path(path) if path else PROJECT_ROOT / "config.yaml") as f:
        cfg = yaml.safe_load(f)
    cfg["paths"] = {k: (root / v) for k, v in cfg["paths"].items()}
    for k, p in cfg["paths"].items():
        (p.parent if k == "warehouse" else p).mkdir(parents=True, exist_ok=True)
    return cfg


def get_logger(name: str = "olist") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(name)s | %(message)s", "%H:%M:%S"))
        logger.addHandler(h)
        logger.setLevel(logging.INFO)
    return logger
