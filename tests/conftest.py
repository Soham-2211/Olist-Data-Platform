import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from olist_platform import ingest  # noqa: E402
from olist_platform.bronze import EXPECTED_COLUMNS  # noqa: E402
from olist_platform.config import load_config  # noqa: E402


def _write(path, cols, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)


def make_source(src: Path):
    """A tiny but messy Olist-shaped dataset.

    Seller S1 ships to customer C1 (same city) three times:
      O1 placed Jan, delivered late in Jan
      O2 placed Feb, delivered on time in Feb
      O3 placed Mar 1 - its point-in-time seller history must contain O1 and O2 only
      O4 placed Mar 2 by another customer, delivered after O3 was placed
    """
    E = EXPECTED_COLUMNS
    _write(src / "orders.csv", E["orders"], [
        ["O1", "C1", "delivered", "2017-01-05 10:00:00", "2017-01-05 11:00:00", "2017-01-06 09:00:00",
         "2017-01-25 12:00:00", "2017-01-20 00:00:00"],
        ["O2", "C2", "delivered", "2017-02-03 10:00:00", "2017-02-03 12:00:00", "2017-02-04 09:00:00",
         "2017-02-10 12:00:00", "2017-02-20 00:00:00"],
        ["O3", "C3", "delivered", "2017-03-01 10:00:00", "2017-03-01 12:00:00", "2017-02-27 09:00:00",
         "2017-03-15 12:00:00", "2017-03-20 00:00:00"],      # carrier date BEFORE purchase -> repaired
        ["O4", "C4", "delivered", "2017-03-02 10:00:00", "2017-03-02 12:00:00", "2017-03-03 09:00:00",
         "2017-03-05 12:00:00", "2017-03-25 00:00:00"],
    ])
    _write(src / "order_items.csv", E["order_items"], [
        ["O1", "1", "P1", "S1", "2017-01-10 00:00:00", "100.00", "10.00"],
        ["O2", "1", "P1", "S1", "2017-02-08 00:00:00", "50.00", "5.00"],
        ["O3", "1", "P2", "S1", "2017-03-06 00:00:00", "80.00", "8.00"],
        ["O4", "1", "P2", "S1", "2017-03-07 00:00:00", "80.00", "8.00"],
    ])
    _write(src / "order_payments.csv", E["order_payments"], [
        ["O1", "1", "credit_card", "3", "110.00"], ["O2", "1", "boleto", "1", "55.00"],
        ["O3", "1", "not_defined", "0", "88.00"], ["O4", "1", "credit_card", "1", "88.00"],
    ])
    _write(src / "order_reviews.csv", E["order_reviews"], [
        ["R1", "O1", "1", "", "atrasou", "2017-01-26 00:00:00", "2017-01-27 10:00:00"],
        ["R2", "O1", "2", "", "", "2017-01-26 00:00:00", "2017-01-26 10:00:00"],   # older duplicate
        ["R3", "O2", "5", "", "", "2017-02-11 00:00:00", "2017-02-12 10:00:00"],
    ])
    _write(src / "customers.csv", E["customers"], [
        ["C1", "U1", "01037", "São Paulo", "SP"], ["C2", "U2", "01037", "sao-paulo", "SP"],
        ["C3", "U1", "01037", "sao paulo", "SP"], ["C4", "U3", "99999", "Sao Paulo", "sp"],  # zip missing -> city fallback
    ])
    _write(src / "sellers.csv", E["sellers"], [["S1", "01046", "sao paulo", "SP"]])
    _write(src / "products.csv", E["products"], [
        ["P1", "pc_gamer", "40", "200", "1", "500", "10", "10", "10"],
        ["P2", "", "", "", "", "0", "20", "10", "10"],
    ])
    _write(src / "geolocation.csv", E["geolocation"], [
        ["01037", "-23.5456", "-46.6393", "sao paulo", "SP"],
        ["01037", "-23.5456", "-46.6393", "são paulo", "SP"],   # duplicate with accent
        ["01046", "-23.5461", "-46.6448", "sa£o paulo", "SP"],
        ["01046", "38.70", "-9.14", "sao paulo", "SP"],          # Lisbon: outside Brazil
    ])
    _write(src / "category_translation.csv", E["category_translation"], [["informatica_acessorios", "computers"]])


@pytest.fixture
def cfg(tmp_path):
    c = load_config(root=tmp_path)
    c["paths"]["sql_dir"] = ROOT / "sql"
    c["paths"]["seeds_dir"] = ROOT / "seeds"
    for name in c["source"]["files"]:
        c["source"]["files"][name]["file"] = f"{name}.csv"
    make_source(c["paths"]["source_dir"])
    for name in c["source"]["files"]:
        c["source"]["files"][name]["sha256"] = ingest.sha256(c["paths"]["source_dir"] / f"{name}.csv")
    c["simulation"] = {"first_cutoff": "2017-01-31", "last_cutoff": "2017-04-30"}
    return c


@pytest.fixture
def batches(cfg):
    return ingest.simulate_batches(cfg)
