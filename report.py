#!/usr/bin/env python3
""""Show my pattern": compares your headache log with local pressure and your
logged triggers, and writes report.html next to this file.

Usage: python3 report.py [--no-open]

Everything is simple counting (headache rate with vs. without something), with
sample sizes shown. With a few weeks of data these are early signals, not proof.

Days you didn't log count as headache-free, from your first entry on. Days with
signs of being sick (fever, body aches, congestion...) are set aside, so a flu
headache doesn't count for or against the weather or your triggers.
"""
import html
import os
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import predict  # noqa: E402

MIN_DAYS = 21          # below this, the report says it's too early for verdicts
MIN_EXPOSED = 5        # days needed in a group before comparing it
REPORT_FILE = os.path.join(predict.HERE, "report.html")


# ---------------------------------------------------------------- data

def pressure_by_day(start, end):
    """Daily risk summary covering start..end (plus a day either side)."""
    lo, hi = start - timedelta(days=2), end + timedelta(days=2)
    hourly = {}
    tz = predict.TZ.replace("/", "%2F")
    # The archive lags ~5 days; the forecast API reaches back 92 days. Use both.
    if lo < date.today() - timedelta(days=85):
        url = (f"https://archive-api.open-meteo.com/v1/archive?latitude={predict.LAT}"
               f"&longitude={predict.LON}&start_date={lo}&end_date={date.today() - timedelta(days=6)}"
               f"&hourly=pressure_msl,temperature_2m&temperature_unit={predict.TEMP_UNIT}&timezone={tz}")
        h = (predict.curl_json(url) or {}).get("hourly", {})
        hourly.update(zip(h.get("time", []), zip(h.get("pressure_msl", []), h.get("temperature_2m", []))))
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={predict.LAT}&longitude={predict.LON}"
           f"&hourly=pressure_msl,temperature_2m&temperature_unit={predict.TEMP_UNIT}"
           f"&past_days=92&forecast_days=3&timezone={tz}")
    h = (predict.curl_json(url) or {}).get("hourly", {})
    for t, pt in zip(h.get("time", []), zip(h.get("pressure_msl", []), h.get("temperature_2m", []))):
        hourly.setdefault(t, pt)
    if not hourly:
        raise RuntimeError("couldn't download pressure data")
    times = sorted(hourly)
    summary = predict.daily_summary([datetime.fromisoformat(t) for t in times],
                                    [hourly[t][0] for t in times],
                                    temps=[hourly[t][1] for t in times])
    return {d: v for d, v in summary.items() if lo <= d <= hi}


def compare(rows, has_it, outcome="headache"):
    """Rate of `outcome` (headache or migraine) on days with vs without a condition."""
    yes = [r for r in rows if has_it(r)]
    no = [r for r in rows if not has_it(r)]
    hits = lambda g: sum(r[outcome] for r in g)
    rate = lambda g: hits(g) / len(g) if g else None
    return {"n_yes": len(yes), "n_no": len(no), "hd_yes": hits(yes), "hd_no": hits(no),
            "rate_yes": rate(yes), "rate_no": rate(no)}


def fisher_greater(a, b, c, d):
    """One-sided Fisher exact p-value that group 1 (a of a+b) has a higher rate than
    group 2 (c of c+d). Plain hypergeometric sum; the tables here are tiny."""
    from math import comb
    n1, n2, k = a + b, c + d, a + c
    total = comb(n1 + n2, k)
    return sum(comb(n1, x) * comb(n2, k - x) for x in range(a, min(n1, k) + 1)) / total


def verdict(c, enough_data):
    if not enough_data:
        return "too early", "muted"
    if c["n_yes"] < MIN_EXPOSED or c["n_no"] < MIN_EXPOSED:
        return "not enough days yet", "muted"
    diff = c["rate_yes"] - c["rate_no"]
    p = fisher_greater(c["hd_yes"], c["n_yes"] - c["hd_yes"], c["hd_no"], c["n_no"] - c["hd_no"])
    c["p"] = p
    # p is how often a gap this big shows up by pure chance.
    if p < 0.05 and diff >= 0.15:
        return "looks linked", "strong"
    if p < 0.20 and diff >= 0.10:
        return "maybe linked", "some"
    return "no clear link", "none"


# ---------------------------------------------------------------- html

def pct(x):
    return "–" if x is None else f"{round(100 * x)}%"


def bar_row(label, c, enough):
    v, cls = verdict(c, enough)
    def bar(rate, kind):
        w = 0 if rate is None else round(100 * rate)
        return f'<div class="bar {kind}"><span style="width:{w}%"></span></div>'
    return f"""
    <tr>
      <td class="lbl">{html.escape(label)}</td>
      <td>{bar(c['rate_yes'], 'yes')}<small>{pct(c['rate_yes'])} of {c['n_yes']} days</small></td>
      <td>{bar(c['rate_no'], 'no')}<small>{pct(c['rate_no'])} of {c['n_no']} days</small></td>
      <td><span class="tag {cls}">{v}</span></td>
    </tr>"""


def table(title, sub, head_yes, head_no, body, rate_word="Headache"):
    return f"""
  <section>
    <h2>{title}</h2>
    <p class="sub">{sub}</p>
    <table>
      <thead><tr><th></th><th>{rate_word} rate {head_yes}</th><th>{head_no}</th><th></th></tr></thead>
      <tbody>{body}</tbody>
    </table>
  </section>"""


def count_list(counter, total, empty):
    if not counter:
        return f'<li class="muted">{empty}</li>'
    return "".join(f"<li><b>{html.escape(k)}</b>: {v} of {total}</li>"
                   for k, v in sorted(counter.items(), key=lambda kv: -kv[1]))


def weather_rows(rows, pressure, enough, outcome):
    risky = lambda d: d in pressure and pressure[d]["level"] in ("MODERATE", "HIGH")
    warm = lambda d: d in pressure and (pressure[d].get("t_delta") or 0) >= predict.TEMP_RISE
    big = lambda d: d in pressure and pressure[d]["swing"] >= predict.BIG_RANGE
    # pressure[d] describes the change from d to d+1, so "the day of" is the day after.
    before = lambda r: risky(r["date"])
    of = lambda r: risky(r["date"] - timedelta(days=1))
    c = lambda f: compare(rows, f, outcome)
    unit = predict.DEG
    return (bar_row("Day before a pressure drop (alert day)", c(before), enough)
            + bar_row("Day of the lower pressure", c(of), enough)
            + bar_row("Either of those days", c(lambda r: before(r) or of(r)), enough)
            + bar_row(f"Big range within the day ({predict.BIG_RANGE:.0f}+ hPa)", c(lambda r: big(r["date"])), enough)
            + bar_row("Big range, pressure falling",
                      c(lambda r: big(r["date"]) and pressure[r["date"]]["falling"]), enough)
            + bar_row(f"Day before a warm-up ({predict.TEMP_RISE:.0f}{unit}+ by next day)", c(lambda r: warm(r["date"])), enough)
            + bar_row("Day of the warm-up", c(lambda r: warm(r["date"] - timedelta(days=1))), enough))


def build(rows, pressure, log):
    n = len(rows)
    enough = n >= MIN_DAYS
    well = [r for r in rows if not r["sick"]]         # used for every comparison
    headaches = [r for r in rows if r["headache"]]
    n_logged = sum(r["logged"] for r in rows)
    n_sick = n - len(well)
    n_mig = sum(r["migraine"] for r in rows)
    sev = [int(r["severity"]) for r in headaches if r["severity"].isdigit()]
    first, last = rows[0]["date"], rows[-1]["date"]

    out = []
    out.append(f"""
  <header>
    <h1>My headache pattern</h1>
    <p class="sub">{html.escape(predict.PLACE)} · {first:%b %-d} – {last:%b %-d, %Y} ·
      generated {datetime.now():%b %-d, %-I:%M %p}</p>
  </header>
  <div class="tiles">
    <div class="tile"><b>{n}</b><span>days tracked ({n_logged} logged)</span></div>
    <div class="tile"><b>{len(headaches)}</b><span>headache days ({pct(len(headaches) / n)})</span></div>
    <div class="tile"><b>{n_mig}</b><span>migraines</span></div>
    <div class="tile"><b>{(sum(sev) / len(sev)) if sev else 0:.1f}</b><span>average severity</span></div>
  </div>
  <p class="sub">Days you didn't log count as headache-free.
    {f"{n_sick} day{'s' if n_sick != 1 else ''} with signs of being sick {'are' if n_sick != 1 else 'is'} "
     "set aside in the comparisons below." if n_sick else ""}</p>""")
    if not enough:
        out.append(f'<p class="note">{n} days tracked so far. Verdicts appear at {MIN_DAYS}; '
                   'until then, the numbers are just a preview.</p>')

    types, onsets = defaultdict(int), defaultdict(int)
    for r in headaches:
        types[r["type"] or "Not recorded"] += 1
        onsets[r["onset"] or "Not recorded"] += 1
    out.append(f"""
  <section class="two">
    <div><h2>Kinds of headache</h2><ul>{count_list(types, len(headaches), "No headaches logged.")}</ul></div>
    <div><h2>When they start</h2><ul>{count_list(onsets, len(headaches), "No headaches logged.")}</ul></div>
  </section>""")

    out.append(table("Weather: any headache",
                     "A pressure drop means the next day's average is 5+ hPa lower (Kimoto). Alerts flag the day before "
                     "the drop, as in the study; the first two rows test which day fits you. Range and warm-up rows test "
                     "things the pressure research didn't cover.",
                     "on those days", "on other days", weather_rows(well, pressure, enough, "headache")))
    if n_mig:
        out.append(table("Weather: migraines only",
                         "The pressure research is about migraine specifically, so this leaves out tension-type "
                         "headaches, brief jabs and \"not sure\".",
                         "on those days", "on other days", weather_rows(well, pressure, enough, "migraine"),
                         rate_word="Migraine"))

    # Triggers: only logged days know which triggers were present.
    logged = [r for r in well if r["logged"]]
    good_days = sum(1 for r in logged if not r["headache"])
    counts = defaultdict(int)
    for r in logged:
        for t in r["triggers"]:
            counts[t] += 1
    if good_days >= MIN_EXPOSED:
        body = "".join(bar_row(t, compare(logged, lambda r, t=t: t in r["triggers"]), enough)
                       for t in sorted(counts, key=lambda t: -counts[t]))
        out.append(table("Triggers you logged", "Headache rate on logged days you ticked each one vs. logged days you "
                         "didn't. A trigger ticked only a few times can't show much yet.",
                         "when present", "when absent",
                         body or '<tr><td colspan="4" class="muted">No triggers logged yet.</td></tr>'))
    else:
        on_headache = defaultdict(int)
        hd_logged = [r for r in logged if r["headache"]]
        for r in hd_logged:
            for t in r["triggers"]:
                on_headache[t] += 1
        out.append(f"""
  <section>
    <h2>Triggers on your headache days</h2>
    <p class="sub">How often each came up. To see whether a trigger actually raises your odds, the report needs
      some good days logged too ({good_days} so far, {MIN_EXPOSED} needed). Log a quick "No headache" now and then,
      ticking whatever was going on that day.</p>
    <ul>{count_list(on_headache, len(hd_logged), "No triggers logged yet.")}</ul>
  </section>""")

    # Preventive cycle.
    if predict.PREVENTIVE:
        doses = sorted({d for d, row in log.items() if f"{predict.PREVENTIVE} dose" in row["meds"]}
                       | ({predict.CONFIG["preventive_last_dose"]} if predict.CONFIG.get("preventive_last_dose") else set()))
        doses = [date.fromisoformat(d) for d in doses]
        def week(r):
            prior = [d for d in doses if d <= r["date"]]
            return None if not prior else min((r["date"] - max(prior)).days // 7 + 1, 5)
        body = ""
        for wk in range(1, 6):
            c = compare([r for r in well if week(r) is not None], lambda r, wk=wk: week(r) == wk)
            label = f"Week {wk} after a dose" if wk < 5 else "5+ weeks after a dose"
            if c["n_yes"]:
                body += bar_row(label, c, enough)
        out.append(table(f"{html.escape(predict.PREVENTIVE)} cycle",
                         "Some people notice more headaches as a monthly preventive wears off. "
                         "Only days after a known dose are counted.",
                         "in that week", "in other weeks", body or '<tr><td colspan="4" class="muted">No dose dates yet.</td></tr>'))

    # Meds per month (all days, sick ones included: rebound risk counts every dose).
    months = defaultdict(int)
    for r in rows:
        if r["acute"]:
            months[r["date"].strftime("%B %Y")] += 1
    items = "".join(
        f'<li><b>{m}</b>: {k} day{"s" if k != 1 else ""}'
        + (' <span class="tag strong">at or past the 10-day rebound limit</span>' if k >= predict.MEDS_LIMIT_COMBO
           else ' <span class="tag some">getting close</span>' if k >= predict.MEDS_WARN else "")
        + "</li>" for m, k in months.items())
    out.append(f"""
  <section>
    <h2>Acute meds</h2>
    <p class="sub">Rebound (medication-overuse) headache starts at 10+ days a month for triptans and
      combination pills like Excedrin, 15+ for Advil or Tylenol.</p>
    <ul class="months">{items or '<li class="muted">No acute meds logged.</li>'}</ul>
  </section>""")

    out.append("""
  <footer>Counts from your own log, not medical advice. Patterns with a handful of days can be
    coincidence. Worth bringing to your doctor once you have a couple of months.</footer>""")
    return PAGE.replace("{{BODY}}", "".join(out))


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Headache Pattern</title>
<style>
:root { --bg:#fbfaf8; --card:#fff; --ink:#1d1d1f; --muted:#6e6e73; --line:#e6e3de;
  --yes:#c2553d; --no:#9aa0a6; --strong:#c2553d; --some:#b7791f; --none:#5b8a5a; }
@media (prefers-color-scheme: dark) { :root { --bg:#161617; --card:#1f1f21; --ink:#f2f2f2;
  --muted:#a1a1a6; --line:#333336; --yes:#e07a5f; --no:#6e7378; --strong:#e07a5f; --some:#e0a54a; --none:#81b29a; } }
* { box-sizing:border-box } body { margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.5 -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif; }
main { max-width:860px; margin:0 auto; padding:32px 16px 48px; }
h1 { font-size:28px; margin:0 } h2 { font-size:18px; margin:0 0 2px }
.sub { color:var(--muted); margin:2px 0 14px; font-size:13px }
.tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin:20px 0 }
.tile { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px }
.tile b { display:block; font-size:26px } .tile span { color:var(--muted); font-size:13px }
.note { background:var(--card); border:1px dashed var(--line); border-radius:10px; padding:10px 14px; color:var(--muted) }
section { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:18px; margin:16px 0; overflow-x:auto }
table { width:100%; border-collapse:collapse; min-width:560px }
th { text-align:left; font-weight:500; color:var(--muted); font-size:12px; padding:0 8px 6px }
td { padding:8px; border-top:1px solid var(--line); vertical-align:middle }
td.lbl { width:32% } small { color:var(--muted); font-size:12px }
.bar { height:8px; background:var(--line); border-radius:4px; overflow:hidden; margin-bottom:3px }
.bar span { display:block; height:100% } .bar.yes span { background:var(--yes) } .bar.no span { background:var(--no) }
.tag { font-size:12px; padding:2px 8px; border-radius:999px; white-space:nowrap; border:1px solid currentColor }
.tag.strong { color:var(--strong) } .tag.some { color:var(--some) } .tag.none { color:var(--none) } .tag.muted, .muted { color:var(--muted) }
.months, section ul { margin:0; padding-left:18px }
.two { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:16px } footer { color:var(--muted); font-size:12px; margin-top:24px }
</style></head>
<body><main>{{BODY}}</main></body></html>
"""


def main():
    log = predict.read_log()
    if not log:
        predict.notify("Headache pattern", "Nothing logged yet. Use 📝 Log today in the menu bar first.")
        return
    first = date.fromisoformat(min(log))
    last = date.today() if date.today().isoformat() in log else date.today() - timedelta(days=1)
    last = max(last, date.fromisoformat(max(log)))
    rows = []
    d = first
    while d <= last:
        row = log.get(d.isoformat())
        if row:
            meds = [m for m in row["meds"].split(";") if m]
            headache = row["headache"] == "yes"
            rows.append({"date": d, "logged": True, "headache": headache,
                         "migraine": headache and (row.get("type") or "") == "Migraine",
                         "type": row.get("type") or "", "onset": row.get("onset") or "",
                         "severity": row["severity"], "sick": predict.is_sick_day(row),
                         "triggers": [t for t in row["triggers"].split(";") if t],
                         "acute": any(predict.is_acute(m) for m in meds)})
        else:  # not logged = headache-free
            rows.append({"date": d, "logged": False, "headache": False, "migraine": False,
                         "type": "", "onset": "", "severity": "", "sick": False,
                         "triggers": [], "acute": False})
        d += timedelta(days=1)
    pressure = pressure_by_day(first, last)
    with open(REPORT_FILE, "w") as f:
        f.write(build(rows, pressure, log))
    if "--no-open" not in sys.argv:
        subprocess.run(["open", REPORT_FILE])
    print(REPORT_FILE)


if __name__ == "__main__":
    main()
