"""Usage:
  python -m planner_alert.run                      # demo with built-in sample data
  python -m planner_alert.run --data my_folder     # your own skus.csv, demand.csv, open_pos.csv
  python -m planner_alert.run --save-sample sample_data   # write the sample data as CSV files
"""
import argparse

from . import data, detect, report


def main():
    ap = argparse.ArgumentParser(description="Supply-chain exception alerts for planners")
    ap.add_argument("--data", help="folder with skus.csv, demand.csv and open_pos.csv")
    ap.add_argument("--save-sample", metavar="FOLDER", help="write the sample data to CSV files and exit")
    ap.add_argument("--out", default="report.html")
    ap.add_argument("--csv", default="alerts.csv")
    args = ap.parse_args()

    if args.save_sample:
        demand, skus, pos, _ = data.generate()
        data.save(demand, skus, pos, args.save_sample)
        print(f"sample data written to {args.save_sample}/")
        return

    demand, skus, open_pos, today = data.load(args.data) if args.data else data.generate()
    alerts = detect.run_all(demand, skus, open_pos, today)
    alerts.to_csv(args.csv, index=False)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(report.build_html(alerts, demand, today, len(skus)))
    print(f"{len(skus)} items checked, {alerts['sku'].nunique()} flagged, {len(alerts)} alerts -> {args.out}, {args.csv}")
    print(alerts["priority"].value_counts().to_string())


if __name__ == "__main__":
    main()
