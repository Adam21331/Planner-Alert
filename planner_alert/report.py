"""Turn alerts into a single-file HTML report a planner can open each morning."""
import base64
import html
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

COLORS = {"High": "#b3261e", "Medium": "#b26a00", "Low": "#5f6b73"}
GROUPS = [("High", "Act today"), ("Medium", "Check this week"), ("Low", "Keep an eye on")]
ALERT_HELP = [
    ("Data check", "The numbers themselves look wrong. Fix these first."),
    ("Demand spike", "Sales suddenly jumped well above normal."),
    ("Stock-out risk", "Stock will run out before the next delivery."),
    ("Overdue PO / Late supply", "A supplier order is late, or likely to be."),
    ("Backlog risk", "Customers are waiting for more units than we have."),
    ("Forecast gap", "The forecast is far from what is really selling."),
    ("Overstock", "Far more stock than we will sell soon."),
    ("Slow-moving stock", "Stock that has not sold for weeks."),
]


def _chart(demand, sku):
    g = demand[demand.sku == sku].sort_values("date")
    fig, ax = plt.subplots(figsize=(3, 0.8))
    ax.plot(g["date"], g["demand"], lw=1, color="#44525c")
    ax.axvspan(g["date"].iloc[-3], g["date"].iloc[-1], color="#b3261e", alpha=0.15)
    ax.axis("off")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=90, bbox_inches="tight", transparent=True)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _card(a, demand):
    img = _chart(demand, a.sku)
    return f"""<div class="card" style="border-left-color:{COLORS[a.priority]}">
  <div class="top"><b>{html.escape(a.sku)}</b> <span class="desc">{html.escape(a.description)}</span>
  <span class="type" style="color:{COLORS[a.priority]}">{html.escape(a.alert_type)}</span></div>
  <div class="msg">{html.escape(a.message)}</div>
  <div class="act"><b>Next step:</b> {html.escape(a.action)}</div>
  <img src="data:image/png;base64,{img}" alt="Daily sales, last 120 days">
</div>"""


def build_html(alerts, demand, today, n_items) -> str:
    counts = alerts["priority"].value_counts() if len(alerts) else {}
    flagged = alerts["sku"].nunique() if len(alerts) else 0
    kpis = "".join(
        f'<div class="kpi"><b style="color:{COLORS[k]}">{counts.get(k, 0)}</b><span>{label}</span></div>'
        for k, label in GROUPS)
    kpis += f'<div class="kpi"><b>{n_items - flagged}</b><span>Items with no alerts</span></div>'

    sections = ""
    for key, label in GROUPS:
        subset = alerts[alerts["priority"] == key] if len(alerts) else alerts
        if len(subset):
            cards = "".join(_card(a, demand) for _, a in subset.iterrows())
            sections += f'<h2 style="color:{COLORS[key]}">{label} <small>({len(subset)})</small></h2>{cards}'
    if not sections:
        sections = "<p>No alerts today. Everything looks normal.</p>"

    help_rows = "".join(f"<li><b>{t}:</b> {d}</li>" for t, d in ALERT_HELP)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Planner Alert</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;margin:0 auto;padding:32px 20px;color:#1f2933;max-width:860px;background:#fafafa}}
h1{{margin:0}} .sub{{color:#5f6b73;margin:4px 0 20px}}
h2{{margin:32px 0 10px;font-size:20px}} h2 small{{font-weight:400;color:#5f6b73}}
.kpis{{display:flex;gap:12px;flex-wrap:wrap}}
.kpi{{background:#fff;border:1px solid #e1e4e8;border-radius:8px;padding:12px 18px;display:flex;flex-direction:column;min-width:110px}}
.kpi b{{font-size:28px}} .kpi span{{color:#5f6b73;font-size:13px}}
.card{{background:#fff;border:1px solid #e1e4e8;border-left:5px solid;border-radius:8px;padding:12px 16px;margin-bottom:10px;position:relative}}
.top{{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}} .desc{{color:#5f6b73;font-size:14px}}
.type{{margin-left:auto;font-weight:600;font-size:13px}}
.msg{{margin:6px 0 4px;max-width:560px}} .act{{color:#3d4a54;font-size:14px;max-width:560px}}
.card img{{position:absolute;right:16px;bottom:10px;height:34px;opacity:.9}}
details{{margin-top:36px;background:#fff;border:1px solid #e1e4e8;border-radius:8px;padding:12px 16px}}
summary{{cursor:pointer;font-weight:600}} li{{margin:6px 0}}
.foot{{color:#5f6b73;font-size:12px;margin-top:20px}}
@media(max-width:600px){{.card img{{position:static;display:block;margin-top:6px}}.type{{margin-left:0}}}}
</style></head><body>
<h1>Planner Alert</h1>
<div class="sub">Daily supply-chain exceptions for {today:%A %d %B %Y}. Only items that need attention are listed.</div>
<div class="kpis">{kpis}</div>
{sections}
<details><summary>How to read this report</summary>
<p>Each card is one item (SKU) that needs a look, with the reason in plain words and a suggested next step.
The small chart shows daily sales over the last 120 days; the shaded area is the last 3 days.</p>
<ul>{help_rows}</ul></details>
<div class="foot">Generated automatically from demand history, stock levels, purchase orders and forecasts. Sample data.</div>
</body></html>"""
