"""Sample supply-chain data (synthetic, no private data) and a CSV loader.

Three tables, like what a planner exports from an ERP:
  skus      one row per item (stock, lead time, forecast, customer backlog)
  demand    one row per item per day (units sold)
  open_pos  one row per open purchase order (deliveries still expected)

generate() builds them with a few deliberately planted problems (see SCENARIOS)
so the demo shows every alert type. All other items are healthy on purpose.
"""
from pathlib import Path

import numpy as np
import pandas as pd

TYPES = ["Resistor", "Capacitor", "Connector", "Diode", "Sensor",
         "Relay", "Switch", "Fuse", "LED", "Transistor"]

# How many days late each supplier usually delivers. F and G are the unreliable ones.
SUPPLIER_DELAY = {"Supplier A": 0, "Supplier B": 1, "Supplier C": 0, "Supplier D": 2,
                  "Supplier E": 1, "Supplier F": 9, "Supplier G": 6}
RELIABLE = ["Supplier A", "Supplier B", "Supplier C", "Supplier D", "Supplier E"]

# SKU number -> the problem planted in it. SKU-021 and above are healthy.
SCENARIOS = {
    1: "spike", 2: "spike",
    3: "stockout_no_po", 4: "stockout_late_po",
    5: "overdue_po", 6: "overdue_po",
    7: "late_supplier", 8: "late_supplier",
    9: "overstock", 10: "overstock",
    11: "forecast_low", 12: "forecast_high",
    13: "slow", 14: "slow",
    15: "backlog", 16: "backlog",
    17: "mismatch", 18: "mismatch",
    19: "duplicate_po", 20: "negative_stock",
}

REQUIRED = {
    "skus": ["sku", "on_hand", "lead_time_days", "safety_stock"],
    "demand": ["date", "sku", "demand"],
    "open_pos": ["sku", "promised_date", "supplier", "supplier_avg_delay_days"],
}


def generate(n_skus: int = 60, days: int = 120, seed: int = 42):
    rng = np.random.default_rng(seed)
    today = pd.Timestamp.today().normalize()
    dates = pd.date_range(end=today, periods=days)
    sku_rows, demand_rows, po_rows = [], [], []

    for i in range(1, n_skus + 1):
        sc = SCENARIOS.get(i, "ok")
        sku = f"SKU-{i:03d}"
        base = int(rng.integers(15, 80))                   # normal units sold per day
        lead = int(rng.integers(12, 21)) if sc == "late_supplier" else int(rng.integers(5, 21))
        cover = lead * rng.uniform(2.2, 3.2)               # healthy: stock lasts 2-3x the lead time
        forecast = base * rng.uniform(0.92, 1.08)          # healthy: forecast within ~8%
        backlog_ratio = rng.uniform(0, 0.3)                # healthy: small backlog vs stock
        po = None
        if rng.random() < 0.7:                             # most healthy items have an order coming
            po = {"days": int(rng.integers(1, lead + 1)), "supplier": str(rng.choice(RELIABLE))}
        demand = rng.poisson(base, days).astype(float)

        # ---- plant the problem ----
        if sc == "spike":
            demand[-3:] *= rng.uniform(3, 4)
        elif sc == "stockout_no_po":
            cover, po = lead * rng.uniform(0.3, 0.6), None
        elif sc == "stockout_late_po":
            cover, po = 5, {"days": 12, "supplier": "Supplier D"}
        elif sc == "overdue_po":
            po = {"days": -int(rng.integers(3, 8)), "supplier": "Supplier B"}
        elif sc == "late_supplier":
            po = {"days": int(rng.integers(3, 9)), "supplier": str(rng.choice(["Supplier F", "Supplier G"]))}
        elif sc == "overstock":
            cover, po = rng.uniform(100, 160), None
        elif sc == "forecast_low":
            forecast = base * 0.5
        elif sc == "forecast_high":
            forecast = base * 1.7
        elif sc == "slow":
            demand[-70:], forecast, cover, po = 0, 0, 40, None
        elif sc == "backlog":
            backlog_ratio = rng.uniform(1.5, 2.5)
        elif sc == "duplicate_po":
            po = {"days": int(rng.integers(2, 9)), "supplier": "Supplier A"}

        on_hand = int(base * cover)
        backlog = int(on_hand * backlog_ratio)
        wms = max(on_hand + int(rng.integers(-2, 3)), 0)   # warehouse count, normally ~ERP
        if sc == "mismatch":
            wms = int(on_hand * rng.uniform(0.55, 0.75))
        elif sc == "negative_stock":
            on_hand, wms = -int(rng.integers(10, 60)), 0

        sku_rows.append({
            "sku": sku,
            "description": f"{TYPES[(i - 1) % len(TYPES)]} (ref {i:03d})",
            "unit_cost": round(float(rng.uniform(0.5, 40)), 2),
            "lead_time_days": lead,
            "safety_stock": int(base * rng.uniform(2, 5)),
            "on_hand": on_hand,
            "on_hand_wms": wms,
            "backlog_qty": backlog,
            "forecast_daily": round(float(forecast), 1),
        })
        demand_rows.append(pd.DataFrame({"date": dates, "sku": sku, "demand": demand}))

        if po:
            row = {
                "sku": sku,
                "supplier": po["supplier"],
                "po_qty": int(base * rng.integers(10, 25)),
                "promised_date": today + pd.Timedelta(days=po["days"]),
                "supplier_avg_delay_days": float(SUPPLIER_DELAY[po["supplier"]]),
            }
            po_rows.append(row)
            if sc == "duplicate_po":
                po_rows.append(dict(row))

    return (pd.concat(demand_rows, ignore_index=True), pd.DataFrame(sku_rows),
            pd.DataFrame(po_rows), today)


def save(demand, skus, open_pos, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    skus.to_csv(folder / "skus.csv", index=False)
    demand.to_csv(folder / "demand.csv", index=False, date_format="%Y-%m-%d")
    open_pos.to_csv(folder / "open_pos.csv", index=False, date_format="%Y-%m-%d")


def load(folder):
    """Load your own data: three CSV files in the same format as sample_data/."""
    folder = Path(folder)
    skus = pd.read_csv(folder / "skus.csv")
    demand = pd.read_csv(folder / "demand.csv", parse_dates=["date"])
    po_file = folder / "open_pos.csv"
    pos = (pd.read_csv(po_file, parse_dates=["promised_date"]) if po_file.exists()
           else pd.DataFrame(columns=REQUIRED["open_pos"]))
    for name, df in [("skus", skus), ("demand", demand), ("open_pos", pos)]:
        missing = [c for c in REQUIRED[name] if c not in df.columns]
        if missing:
            raise ValueError(f"{name}.csv is missing columns: {', '.join(missing)}")
    if "description" not in skus:
        skus["description"] = skus["sku"]
    for col, default in [("unit_cost", np.nan), ("on_hand_wms", np.nan),
                         ("backlog_qty", 0), ("forecast_daily", np.nan)]:
        if col not in skus:
            skus[col] = default
    return demand, skus, pos, demand["date"].max().normalize()
