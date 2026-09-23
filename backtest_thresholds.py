#!/usr/bin/env python3
"""How often would the alert rules fire? Backtests against Open-Meteo archive data.

Usage: python3 backtest_thresholds.py [start_date] [end_date]
"""
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from predict import LAT, LON, TZ, daily_summary  # noqa: E402

from datetime import date, timedelta  # noqa: E402

# Default: the past year, ending a week ago (the archive lags a few days).
end = sys.argv[2] if len(sys.argv) > 2 else (date.today() - timedelta(days=7)).isoformat()
start = sys.argv[1] if len(sys.argv) > 1 else (date.fromisoformat(end) - timedelta(days=365)).isoformat()
url = (f"https://archive-api.open-meteo.com/v1/archive?latitude={LAT}&longitude={LON}"
       f"&start_date={start}&end_date={end}&hourly=pressure_msl"
       f"&timezone={TZ.replace('/', '%2F')}")
d = json.loads(subprocess.run(["/usr/bin/curl", "-sf", "--max-time", "60", url],
                              capture_output=True, text=True, check=True).stdout)["hourly"]
summary = daily_summary([datetime.fromisoformat(t) for t in d["time"]], d["pressure_msl"])

n = len(summary)
counts = defaultdict(int)
months = defaultdict(lambda: [0, 0, 0])  # moderate, high, total
for day, info in summary.items():
    counts[info["level"]] += 1
    m = months[day.strftime("%b")]
    m[2] += 1
    if info["level"] == "MODERATE":
        m[0] += 1
    elif info["level"] == "HIGH":
        m[1] += 1

print(f"{n} days, {start} to {end}")
for lvl in ("LOW", "MODERATE", "HIGH"):  # last day is UNKNOWN (no next day)
    print(f"  {lvl:<8} {counts[lvl]:4d} ({100 * counts[lvl] / n:4.1f}%)")
print("\n  by month (moderate/high of days):")
for name in ["Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug"]:
    if months[name][2]:
        mo, hi, tot = months[name]
        print(f"    {name}: {mo:2d} moderate, {hi:2d} high  (of {tot})")
