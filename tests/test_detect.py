import pandas as pd

from planner_alert import data, detect

TODAY = pd.Timestamp("2026-02-01")


def _demand(values, sku="A"):
    dates = pd.date_range(end=TODAY, periods=len(values))
    return pd.DataFrame({"date": dates, "sku": sku, "demand": values})


def _skus(**kw):
    row = {"sku": "A", "description": "Test", "on_hand": 500, "on_hand_wms": 500, "lead_time_days": 14,
           "safety_stock": 20, "backlog_qty": 0, "forecast_daily": 10.0, "unit_cost": 2.0}
    row.update(kw)
    return pd.DataFrame([row])


def _pos(**kw):
    row = {"sku": "A", "supplier": "S1", "po_qty": 100, "promised_date": TODAY + pd.Timedelta(days=5),
           "supplier_avg_delay_days": 0.0}
    row.update(kw)
    return pd.DataFrame([row])


NO_POS = pd.DataFrame(columns=["sku", "supplier", "promised_date", "supplier_avg_delay_days"])


def test_spike_detected():
    d = _demand([10, 11, 9, 10, 12, 10, 11, 9, 10, 10] * 6 + [50, 55, 60])
    assert detect.demand_spikes(d)[0][1] == "Demand spike"


def test_no_spike_on_flat_demand():
    assert detect.demand_spikes(_demand([10, 11, 9, 10] * 20)) == []


def test_stockout_when_cover_below_eta():
    out = detect.stockout_risk(_demand([10] * 30), _skus(on_hand=50), NO_POS, TODAY)
    assert out and out[0][1] == "Stock-out risk"


def test_no_stockout_when_cover_is_enough():
    assert detect.stockout_risk(_demand([10] * 30), _skus(on_hand=500), _pos(), TODAY) == []


def test_overdue_po():
    out = detect.late_supply(_pos(promised_date=TODAY - pd.Timedelta(days=4)), TODAY)
    assert out[0][1] == "Overdue PO" and "4 days ago" in out[0][3]


def test_late_supplier():
    out = detect.late_supply(_pos(supplier_avg_delay_days=9.0), TODAY)
    assert out[0][1] == "Late supply"


def test_backlog_risk():
    assert detect.backlog_risk(_skus(on_hand=100, backlog_qty=300))[0][1] == "Backlog risk"
    assert detect.backlog_risk(_skus(on_hand=500, backlog_qty=100)) == []


def test_forecast_gap_both_directions():
    d = _demand([20] * 30)
    assert detect.forecast_gap(d, _skus(forecast_daily=10.0))[0][2] == 2   # demand higher
    assert detect.forecast_gap(d, _skus(forecast_daily=40.0))[0][2] == 1   # demand lower
    assert detect.forecast_gap(d, _skus(forecast_daily=21.0)) == []


def test_slow_moving_and_overstock():
    d = _demand([10] * 20 + [0] * 60)
    assert detect.slow_moving(d, _skus(), TODAY)[0][1] == "Slow-moving stock"
    assert detect.overstock(_demand([5] * 30), _skus(on_hand=1000))[0][1] == "Overstock"


def test_data_checks_flag_and_pause_item():
    skus = pd.concat([_skus(sku="A", on_hand=-5, on_hand_wms=0), _skus(sku="B", on_hand=1000, on_hand_wms=600)])
    rows, bad = detect.data_checks(skus, NO_POS)
    assert bad == {"A", "B"} and len(rows) == 2
    dup = pd.concat([_pos(), _pos()])
    assert detect.data_checks(_skus(), dup)[1] == {"A"}


def test_sample_data_flags_planted_problems_and_not_healthy_items():
    demand, skus, pos, today = data.generate()
    alerts = detect.run_all(demand, skus, pos, today)
    flagged = set(alerts["sku"])
    planted = {f"SKU-{i:03d}" for i in data.SCENARIOS}
    assert planted <= flagged, f"missed: {sorted(planted - flagged)}"
    false_alarms = flagged - planted
    assert len(false_alarms) <= 2, f"too many false alarms: {sorted(false_alarms)}"


def test_load_rejects_missing_columns(tmp_path):
    demand, skus, pos, _ = data.generate(n_skus=21)
    data.save(demand, skus.drop(columns=["lead_time_days"]), pos, tmp_path)
    try:
        data.load(tmp_path)
        assert False
    except ValueError as e:
        assert "lead_time_days" in str(e)
