"""Alert rules.

Every rule returns tuples: (sku, alert_type, severity 1-3, message, suggested_action).
Thresholds are named constants below so they are easy to find and change.
"""
import numpy as np
import pandas as pd

SEVERITY = {1: "Low", 2: "Medium", 3: "High"}

# ---- thresholds ----
SPIKE_Z = 3.5          # how unusual recent demand must be to count as a spike
RECENT_DAYS = 3        # "recent" demand = last 3 days
FORECAST_GAP = 0.30    # forecast vs actual differ by more than 30%
SLOW_DAYS = 45         # no sales for this many days = slow-moving
OVERSTOCK_DAYS = 75    # more than this many days of stock = overstock
LATE_SUPPLIER_DAYS = 4 # supplier usually this many days late or more
STOCK_MISMATCH = 0.10  # ERP vs warehouse stock differ by more than 10%


def _recent_avg(demand, days):
    return demand.sort_values("date").groupby("sku")["demand"].apply(lambda s: s.tail(days).mean())


def _value(units, cost):
    return "" if pd.isna(cost) else f" (about €{units * cost:,.0f} tied up)"


def data_checks(skus, open_pos):
    """Check the data itself first. Items with bad data are paused for the other rules."""
    out, bad = [], set()
    for _, s in skus.iterrows():
        wms = s.get("on_hand_wms", np.nan)
        if s.on_hand < 0:
            out.append((s.sku, "Data check", 3,
                        f"The ERP shows negative stock ({s.on_hand:,.0f} units), which is impossible.",
                        "Fix the stock record first. Other alerts for this item are paused."))
            bad.add(s.sku)
        elif pd.notna(wms):
            diff = abs(s.on_hand - wms)
            if diff >= 20 and diff > STOCK_MISMATCH * max(abs(s.on_hand), 1):
                out.append((s.sku, "Data check", 2,
                            f"ERP says {s.on_hand:,.0f} units, the warehouse count says {wms:,.0f} (difference of {diff:,.0f}).",
                            "Find out which number is right. Other alerts for this item are paused."))
                bad.add(s.sku)
    if len(open_pos):
        cols = [c for c in ["sku", "supplier", "promised_date", "po_qty"] if c in open_pos.columns]
        dup = open_pos[open_pos.duplicated(cols, keep=False)]
        for sku, g in dup.groupby("sku"):
            out.append((sku, "Data check", 2,
                        f"The same purchase order appears {len(g)} times, so incoming supply may be double-counted.",
                        "Remove the duplicate line. Other alerts for this item are paused."))
            bad.add(sku)
    return out, bad


def demand_spikes(demand, window=60, recent=RECENT_DAYS, z_thr=SPIKE_Z):
    """Robust z-score (median/MAD) of recent average demand vs the item's own history."""
    out = []
    for sku, g in demand.sort_values("date").groupby("sku"):
        hist = g["demand"].iloc[:-recent].tail(window)
        cur = g["demand"].tail(recent).mean()
        med = hist.median()
        mad = np.median(np.abs(hist - med)) or 1.0
        z = 0.6745 * (cur - med) / mad
        if z > z_thr:
            out.append((sku, "Demand spike", 3 if z > 2 * z_thr else 2,
                        f"Sales jumped: the last {recent} days averaged {cur:,.0f} units/day, normally about {med:,.0f}.",
                        "Check for a large customer order. Update the forecast or expedite supply."))
    return out


def stockout_risk(demand, skus, open_pos, today):
    """Will stock run out before the next delivery can arrive?"""
    avg = _recent_avg(demand, 14)
    first_po = {}
    if len(open_pos):
        for _, p in open_pos.sort_values("promised_date").drop_duplicates("sku").iterrows():
            first_po[p.sku] = p
    out = []
    for _, s in skus.iterrows():
        cover = s.on_hand / max(avg.get(s.sku, 1.0), 0.1)   # days the stock will last
        p = first_po.get(s.sku)
        if p is not None:
            eta = max((p.promised_date - today).days + p.supplier_avg_delay_days, 0)
            source = "the open order"
        else:
            eta = s.lead_time_days   # nothing ordered: a new order takes a full lead time
            source = "a new order (nothing is on order)"
        if eta > cover:
            sev = 3 if cover < 0.5 * eta or s.on_hand < s.safety_stock else 2
            action = ("Ask the supplier to expedite, or look for another source."
                      if p is not None else "Place an order now and ask for the fastest delivery.")
            out.append((s.sku, "Stock-out risk", sev,
                        f"Stock lasts about {cover:,.0f} days, but {source} would arrive in about {eta:,.0f} days.",
                        action))
    return out


def late_supply(open_pos, today, delay_thr=LATE_SUPPLIER_DAYS):
    out = []
    for _, p in open_pos.iterrows():
        due_in = (p.promised_date - today).days
        if due_in < 0:
            out.append((p.sku, "Overdue PO", 3,
                        f"{p.supplier} promised this order {-due_in} days ago and it has not arrived.",
                        "Call the supplier for a new date and check how long stock will last."))
        elif p.supplier_avg_delay_days >= delay_thr and due_in <= 10:
            out.append((p.sku, "Late supply", 3 if p.supplier_avg_delay_days >= 8 else 2,
                        f"{p.supplier} is usually about {p.supplier_avg_delay_days:,.0f} days late. This order is due in {due_in} days.",
                        "Expect a later delivery and ask the supplier to confirm the date."))
    return out


def backlog_risk(skus):
    """Customers are waiting for more units than are in stock."""
    out = []
    for _, s in skus.iterrows():
        backlog = s.get("backlog_qty", 0)
        if pd.notna(backlog) and backlog > s.on_hand:
            out.append((s.sku, "Backlog risk", 3 if s.on_hand < 0.5 * backlog else 2,
                        f"Customers are waiting for {backlog:,.0f} units but only {s.on_hand:,.0f} are in stock ({backlog - s.on_hand:,.0f} short).",
                        "Decide which customer orders ship first and expedite supply."))
    return out


def forecast_gap(demand, skus, skip=(), days=14, gap_thr=FORECAST_GAP):
    """Forecast vs what really sold over the last 14 days."""
    actual = _recent_avg(demand, days)
    out = []
    for _, s in skus.iterrows():
        f, a = s.get("forecast_daily", np.nan), actual.get(s.sku, np.nan)
        if pd.isna(f) or pd.isna(a) or s.sku in skip:
            continue
        if abs(a - f) / max(a, f, 1) > gap_thr:
            higher = a > f
            out.append((s.sku, "Forecast gap", 2 if higher else 1,
                        f"The forecast says {f:,.0f} units/day, but the last {days} days averaged {a:,.0f}. "
                        f"Real demand is {'higher' if higher else 'lower'} than forecast.",
                        "Raise the forecast to avoid shortages." if higher
                        else "Lower the forecast to avoid building excess stock."))
    return out


def overstock(demand, skus, max_cover=OVERSTOCK_DAYS):
    avg = _recent_avg(demand, 30)
    out = []
    for _, s in skus.iterrows():
        a = avg.get(s.sku, 0)
        if a > 0 and s.on_hand / a > max_cover:
            out.append((s.sku, "Overstock", 1,
                        f"Stock covers {s.on_hand / a:,.0f} days of sales{_value(s.on_hand, s.get('unit_cost', np.nan))}.",
                        "Pause new orders and consider selling or returning the excess."))
    return out


def slow_moving(demand, skus, today, min_days=SLOW_DAYS):
    last_sale = demand[demand["demand"] > 0].groupby("sku")["date"].max()
    first_day = demand["date"].min()
    out = []
    for _, s in skus.iterrows():
        days = (today - last_sale.get(s.sku, first_day)).days
        if days >= min_days and s.on_hand > 0:
            out.append((s.sku, "Slow-moving stock", 2 if days >= 90 else 1,
                        f"No sales for {days} days, with {s.on_hand:,.0f} units in stock{_value(s.on_hand, s.get('unit_cost', np.nan))}.",
                        "Stop reordering. Review for a discount, transfer or write-off."))
    return out


def run_all(demand, skus, open_pos, today) -> pd.DataFrame:
    data_rows, bad = data_checks(skus, open_pos)
    ok_skus = skus[~skus["sku"].isin(bad)]
    ok_pos = open_pos[~open_pos["sku"].isin(bad)] if len(open_pos) else open_pos
    spikes = demand_spikes(demand)
    rows = (data_rows + spikes
            + stockout_risk(demand, ok_skus, ok_pos, today)
            + late_supply(ok_pos, today)
            + backlog_risk(ok_skus)
            + forecast_gap(demand, ok_skus, skip={r[0] for r in spikes})
            + overstock(demand, ok_skus)
            + slow_moving(demand, ok_skus, today))
    cols = ["sku", "alert_type", "severity", "message", "action"]
    df = pd.DataFrame(rows, columns=cols)
    df["priority"] = df["severity"].map(SEVERITY)
    desc = skus.set_index("sku")["description"] if "description" in skus.columns else pd.Series(dtype=str)
    df["description"] = df["sku"].map(desc).fillna("")
    return df.sort_values(["severity", "alert_type", "sku"], ascending=[False, True, True]).reset_index(drop=True)
