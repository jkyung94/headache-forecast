#!/usr/bin/env python3
"""Migraine risk from barometric pressure changes, for any location.

Uses the definitions from the two most-cited studies, applied to daily averages
of the hourly Open-Meteo forecast (free, no key):

  Kimoto et al. 2011 (n=28): migraines rose when the daily pressure fell by
    more than 5 hPa vs the previous day.
  Okuma et al. 2015 (n=34): attacks were most frequent when pressure sat
    6-10 hPa below standard (1013), i.e. at or under ~1007 hPa.

  Kimoto's headaches landed on the day BEFORE the lower-pressure day, while
  pressure was still falling, so a day is flagged when the next day is lower:
  MODERATE = the next day's average is 5+ hPa lower than this day's (Kimoto)
  HIGH     = that drop AND the next day lands 6+ hPa below the local normal
             (past-year average for the configured location) (Kimoto + Okuma)

Backtested on Sep 2025 - Sep 2026 data for northern Illinois: moderate ~10% of
days, high ~7%, clustered Nov-Apr. Run backtest_thresholds.py for your location.

Includes a headache log (native Mac dialogs, saved to log.csv; days you don't log
count as headache-free, so logging only when in pain is fine) and counts
days with acute headache meds this month, because rebound (medication-overuse)
headache starts at 10+ days/month for triptans and combination pills like
Excedrin, 15+ for Advil/Tylenol.

Usage:
  python3 predict.py --setup     # choose your location (city, zip, or lat,lon)
  python3 predict.py             # nightly: print report, notify if moderate/high
  python3 predict.py --quiet     # nightly without printing
  python3 predict.py --always    # notify even on low-risk days (for testing)
  python3 predict.py --swiftbar  # menu bar output (no logging, no notification)
  python3 predict.py --log       # log today (or --log pick to choose a past day)
"""
import json
import os
import subprocess
import sys
import csv
import time
import urllib.parse
from collections import defaultdict
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(HERE, "config.json")


def load_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


# Pressure is regional, so one point per town is plenty. Set with --setup.
CONFIG = load_config()
LAT, LON = CONFIG.get("lat"), CONFIG.get("lon")
TZ = CONFIG.get("timezone", "auto")
PLACE = CONFIG.get("place", "")
TEMP_UNIT = CONFIG.get("temp_unit", "fahrenheit")
DEG = "°F" if TEMP_UNIT == "fahrenheit" else "°C"

DAILY_DROP = 5.0        # Kimoto: day-over-day fall in the daily average, hPa
BELOW_NORMAL = 6.0      # Okuma: 6+ hPa below 1013, which is ~normal in Japan.
                        # Applied here as 6 below the *local* normal instead, since
                        # northern Illinois averages ~1017 (1007 would be ~10 below).

BIG_RANGE = 12.0        # in-day high-low range, hPa. Not research-backed: ~top 15% of
                        # days in northern Illinois. Shown and tested in the report,
                        # but doesn't drive alerts unless the log shows it matters.

TEMP_RISE = 9.0 if TEMP_UNIT == "fahrenheit" else 5.0
                        # daily-average warm-up by the next day. Mukamal et al. 2009
                        # (Boston ER visits) linked headaches to rising temperature,
                        # per 5°C. ~top 10% of days in northern Illinois. Info + report only.

MEDS_WARN = 8           # start warning before the first rebound limit
MEDS_LIMIT_COMBO = 10   # triptans, Excedrin and other combination pills
MEDS_LIMIT_SIMPLE = 15  # Advil, Tylenol, aspirin

HISTORY_FILE = os.path.join(HERE, "history.csv")
LOG_FILE = os.path.join(HERE, "log.csv")
NORMAL_FILE = os.path.join(HERE, "local_normal.json")
DIALOG_SCRIPT = os.path.join(HERE, "log_dialog.applescript")
PREVENTIVE = CONFIG.get("preventive")        # optional, e.g. "Emgality"

# Acute meds count toward the monthly rebound limits; "None" and preventives don't.
ACUTE_MEDS = ["Advil / ibuprofen", "Aleve / naproxen", "Tylenol / acetaminophen", "Aspirin",
              "Excedrin", "Triptan (e.g. sumatriptan)", "Nurtec / Ubrelvy", "Other"]
TRIGGERS = ["Poor sleep", "Overslept", "Skipped/late meal", "Dehydration", "Caffeine change",
            "Alcohol", "Stress", "Let-down after stress", "Routine change/holiday", "Travel",
            "Long screen time", "Bright/flickering light", "Strong smell", "Loud noise",
            "Dry indoor heat", "Cold exposure", "Period/hormonal",
            "Neck/shoulder tension", "Intense exercise"]
# No "Weather change" trigger on purpose: the tool measures weather itself, and ticking
# it by hand tends to happen on headache days, which would make weather look guiltier.
HEADACHE_TYPES = ["Migraine (throbbing, nausea, or light/sound hurts)",
                  "Tension-type (pressing band, mild to moderate)",
                  "Brief jab (a few seconds)", "Not sure"]
ONSETS = ["Morning", "Afternoon", "Evening", "Night / woke up with it"]
# Illness signs mean the headache is probably from being sick; the report sets those days
# aside. The migraine features help check the type that was picked.
ILLNESS_SIGNS = ["Fever / chills", "Body aches", "Congestion / sinus pressure", "Sore throat",
                 "Cough"]
MIGRAINE_FEATURES = ["Nausea / vomiting", "Light hurts", "Sound hurts",
                     "Aura (zigzags, spots, tingling)"]
SYMPTOMS = ILLNESS_SIGNS + MIGRAINE_FEATURES + ["Dizziness", "Neck stiffness", "Jaw / tooth pain"]
LOG_FIELDS = ["date", "headache", "type", "onset", "severity", "symptoms", "meds", "triggers",
              "notes", "logged_at"]


# ---------------------------------------------------------------- data

def fetch_hourly(attempts=6):
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        "&hourly=pressure_msl,temperature_2m"
        f"&timezone={TZ.replace('/', '%2F')}&past_days=1&forecast_days=7"
        f"&temperature_unit={TEMP_UNIT}"
    )
    # macOS curl uses the system keychain certs (python.org Python often lacks them).
    # Retry because the 9pm job can fire right as the Mac wakes, before Wi-Fi/DNS
    # is back (curl exit 6 on 2026-09-22).
    for attempt in range(attempts):
        r = subprocess.run(["/usr/bin/curl", "-sf", "--max-time", "20", url],
                           capture_output=True, text=True)
        if r.returncode == 0:
            break
        if attempt < attempts - 1:
            time.sleep(60)
    else:
        raise RuntimeError(f"forecast fetch failed after {attempts} tries (curl exit {r.returncode})")
    data = json.loads(r.stdout)["hourly"]
    times = [datetime.fromisoformat(t) for t in data["time"]]
    return times, data["pressure_msl"], data["temperature_2m"]


def local_normal():
    """Average sea-level pressure over the past year here, cached for 30 days."""
    try:
        with open(NORMAL_FILE) as f:
            cached = json.load(f)
        if (date.today() - date.fromisoformat(cached["computed"])).days < 30 \
                and cached["lat"] == LAT and cached["lon"] == LON:
            return cached["normal_hpa"]
    except (OSError, ValueError, KeyError):
        cached = None

    end = date.today() - timedelta(days=7)  # archive lags a few days
    url = (f"https://archive-api.open-meteo.com/v1/archive?latitude={LAT}&longitude={LON}"
           f"&start_date={end - timedelta(days=365)}&end_date={end}"
           f"&daily=pressure_msl_mean&timezone={TZ.replace('/', '%2F')}")
    r = subprocess.run(["/usr/bin/curl", "-sf", "--max-time", "30", url],
                       capture_output=True, text=True)
    if r.returncode != 0:
        # Stale cache beats nothing; the standard atmosphere is the last resort.
        return cached["normal_hpa"] if cached else 1013.25
    vals = [v for v in json.loads(r.stdout)["daily"]["pressure_msl_mean"] if v is not None]
    normal = round(sum(vals) / len(vals), 1)
    with open(NORMAL_FILE, "w") as f:
        json.dump({"normal_hpa": normal, "computed": date.today().isoformat(),
                   "lat": LAT, "lon": LON}, f)
    return normal


def daily_summary(times, pressure, low_level=None, temps=None):
    """Per calendar day: average pressure, change to the next day, in-day swing, risk.

    Risk sits on the day before the lower day (Kimoto timing). The last day has no
    next day to compare with, so its risk is UNKNOWN.
    """
    by_day = defaultdict(list)
    temp_by_day = defaultdict(list)
    for t, p, tt in zip(times, pressure, temps or [None] * len(times)):
        if p is not None:
            by_day[t.date()].append(p)
        if tt is not None:
            temp_by_day[t.date()].append(tt)
    tavg = {d: sum(v) / len(v) for d, v in temp_by_day.items() if len(v) >= 20}
    days = [d for d in sorted(by_day) if len(by_day[d]) >= 20]  # skip partial days

    if low_level is None:
        low_level = local_normal() - BELOW_NORMAL
    avg = {d: sum(by_day[d]) / len(by_day[d]) for d in days}
    out = {}
    for d, nxt in zip(days, days[1:] + [None]):
        vals = by_day[d]
        if nxt is None or (nxt - d).days != 1:
            delta, level = None, "UNKNOWN"
        else:
            delta = avg[nxt] - avg[d]
            if delta <= -DAILY_DROP and avg[nxt] <= low_level:
                level = "HIGH"
            elif delta <= -DAILY_DROP:
                level = "MODERATE"
            else:
                level = "LOW"
        t_delta = (tavg[nxt] - tavg[d]) if nxt in tavg and d in tavg and delta is not None else None
        out[d] = {"avg": avg[d], "delta": delta, "next_avg": avg.get(nxt), "t_delta": t_delta,
                  "swing": max(vals) - min(vals), "level": level, "falling": vals[-1] < vals[0]}
    return out


# ---------------------------------------------------------------- log

def read_log():
    """{date string: row dict} from log.csv."""
    if not os.path.exists(LOG_FILE):
        return {}
    with open(LOG_FILE, newline="") as f:
        return {row["date"]: row for row in csv.DictReader(f)}


def save_log_row(row):
    """Insert or replace the row for row['date'] (re-logging a day edits it)."""
    rows = read_log()
    rows[row["date"]] = row
    with open(LOG_FILE, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        w.writeheader()
        for d in sorted(rows):
            w.writerow({k: rows[d].get(k, "") for k in LOG_FIELDS})


def short_type(t):
    """'Migraine (throbbing, ...)' -> 'Migraine' for storage and display."""
    return t.split(" (")[0]


def log_dialog(day):
    ago = (date.today() - day).days
    label = {0: "today", 1: "yesterday"}.get(ago, "on")
    label += f" ({day.strftime('%a %-m/%-d')})" if ago <= 1 else f" {day.strftime('%a %-m/%-d')}"
    meds = ["None"] + ACUTE_MEDS + ([f"{PREVENTIVE} dose (preventive)"] if PREVENTIVE else [])

    # Editing a day starts from what was saved. Only pass answers that are still
    # options: a default the list doesn't contain makes the dialog fail.
    prev = read_log().get(day.isoformat(), {})
    keep = lambda saved, options: "\n".join(x for x in (saved or "").split(";") if x in options)
    sev_opts = ["1 - barely noticeable", "2", "3", "4 - distracting", "5", "6",
                "7 - hard to function", "8", "9", "10 - worst ever"]
    defaults = [
        {"yes": "Headache", "no": "No headache"}.get(prev.get("headache"), ""),
        next((t for t in HEADACHE_TYPES if short_type(t) == prev.get("type")), ""),
        prev.get("onset", "") if prev.get("onset") in ONSETS else "",
        next((o for o in sev_opts if o.split()[0] == prev.get("severity")), ""),
        keep(prev.get("symptoms"), SYMPTOMS),
        keep(prev.get("meds"), meds),
        keep(prev.get("triggers"), TRIGGERS),
        prev.get("notes", ""),
    ]
    r = subprocess.run(["osascript", DIALOG_SCRIPT, label, "\n".join(meds), "\n".join(TRIGGERS),
                        "\n".join(HEADACHE_TYPES), "\n".join(ONSETS), "\n".join(SYMPTOMS)]
                       + defaults, capture_output=True, text=True)
    if r.returncode != 0:  # cancelled
        return False
    headache, kind, onset, severity, symptoms, meds_pick, triggers, notes = \
        (r.stdout.rstrip("\n").split("\t") + [""] * 8)[:8]
    meds_pick = ";".join(m for m in meds_pick.split(";") if m and m != "None")
    save_log_row({"date": day.isoformat(), "headache": "yes" if headache == "true" else "no",
                  "type": short_type(kind), "onset": onset, "severity": severity,
                  "symptoms": symptoms,
                  "meds": meds_pick, "triggers": triggers, "notes": notes.strip(),
                  "logged_at": datetime.now().isoformat(timespec="minutes")})
    picked = set(symptoms.split(";"))
    if {"Fever / chills", "Neck stiffness"} <= picked:
        subprocess.run(["osascript", "-e", 'display alert "Please check with a doctor" message '
                        '"A headache with fever and a stiff neck can be a sign of something serious, '
                        'like meningitis. If it came on suddenly or feels severe, get medical care '
                        'today." as critical'], capture_output=True)
    return True


def is_sick_day(row):
    return any(s in ILLNESS_SIGNS for s in (row.get("symptoms") or "").split(";"))


def pick_day_dialog():
    """Choose one of the past 14 days to log or edit. Returns a date or None."""
    logged = read_log()
    days = [date.today() - timedelta(days=k) for k in range(1, 15)]
    labels = [f"{d.strftime('%a %-m/%-d')}{'  (logged, edit)' if d.isoformat() in logged else ''}"
              for d in days]
    items = "{" + ", ".join(json.dumps(l) for l in labels) + "}"
    r = subprocess.run(["osascript", "-e", "activate", "-e",
                        f'choose from list {items} with title "Headache log" '
                        'with prompt "Which day?" default items {item 1 of ' + items + '}'],
                       capture_output=True, text=True)
    pick = r.stdout.strip()
    if r.returncode != 0 or pick in ("", "false"):
        return None
    return days[labels.index(pick)]


def is_acute(med):
    return med in ACUTE_MEDS


def meds_this_month():
    prefix = date.today().strftime("%Y-%m")
    return sum(1 for d, row in read_log().items()
               if d.startswith(prefix) and any(is_acute(m) for m in row["meds"].split(";")))


def days_since_preventive():
    if not PREVENTIVE:
        return None
    dose_days = [d for d, row in read_log().items() if f"{PREVENTIVE} dose" in row["meds"]]
    if CONFIG.get("preventive_last_dose"):  # entered at setup, before logging began
        dose_days.append(CONFIG["preventive_last_dose"])
    return (date.today() - date.fromisoformat(max(dose_days))).days if dose_days else None


def meds_note(n):
    if n >= MEDS_LIMIT_COMBO:
        return f"Meds on {n} days this month -- past the rebound limit for Excedrin/triptans (10), 15 for Advil."
    if n >= MEDS_WARN:
        return f"Meds on {n} days this month -- getting close to the 10-day rebound limit."
    return ""


# ---------------------------------------------------------------- output

ICON = {"LOW": "🟢", "MODERATE": "🟡", "HIGH": "🔴", "UNKNOWN": "⚪"}


def describe(d, info):
    day = "Tomorrow" if d == date.today() + timedelta(days=1) else \
          "Today" if d == date.today() else d.strftime("%A")
    if info["delta"] is None:
        return f"{day}: not enough forecast to tell"
    if info["level"] == "HIGH":
        return (f"{day}: pressure falling {-info['delta']:.1f} hPa by the next day, down to a low "
                f"{info['next_avg']:.0f} hPa")
    if info["level"] == "MODERATE":
        return f"{day}: pressure falling {-info['delta']:.1f} hPa by the next day"
    if info["delta"] > 2:
        return f"{day}: pressure rising, no significant drop"
    if info["delta"] < -2:
        return f"{day}: pressure easing down, under the {DAILY_DROP:.0f} hPa mark"
    return f"{day}: pressure steady"


def notify(title, message):
    script = f'display notification {json.dumps(message)} with title {json.dumps(title)} sound name "Glass"'
    subprocess.run(["osascript", "-e", script], check=False)


def log_history(now, target, info):
    new = not os.path.exists(HISTORY_FILE)
    with open(HISTORY_FILE, "a") as f:
        if new:
            f.write("run_time,for_date,risk,avg_hpa,change_to_next_day_hpa,in_day_swing_hpa\n")
        f.write(f"{now.isoformat(timespec='minutes')},{target.isoformat()},{info['level']},"
                f"{info['avg']:.1f},{info['delta']:+.1f},{info['swing']:.1f}\n")


def print_swiftbar(summary, pressure_now, temp_now):
    today = date.today()
    # After 6pm the question is "what about tomorrow?"
    focus = today + timedelta(days=1) if datetime.now().hour >= 18 else today
    info = summary.get(focus) or summary[min(summary)]
    n_meds = meds_this_month()
    logged = read_log()

    print(f"{ICON[info['level']]} {info['level'].title()}")
    print("---")
    print(f"Migraine risk: {info['level'].title()} | size=14")
    print(describe(focus, info))
    print(f"Now: {pressure_now:.0f} hPa, {temp_now:.0f}{DEG}  ·  {PLACE} | color=gray")
    print("---")
    print("Daily average pressure | color=gray")
    # 📅 is the same width as the risk dots, so the columns line up.
    print(f"📅 {'':<9}  {'avg':>6}  {'pressure change':<15}  {'range':>5}  {'temp':>5} | "
          "font=Menlo-Regular size=12 color=gray")
    for d in sorted(summary):
        if d < today:
            continue
        i = summary[d]
        label = d.strftime("%a %-m/%-d")
        nxt = (d + timedelta(days=1)).strftime("%a")
        change = "" if i["delta"] is None else f"{i['delta']:+5.1f} by {nxt}"
        t = None if i.get("t_delta") is None else round(i["t_delta"])
        temp = "" if t is None else ("0°" if t == 0 else f"{t:+d}°")
        flags = (" ⚡" if i["swing"] >= BIG_RANGE else "") + \
                (" 🌡" if (i.get("t_delta") or 0) >= TEMP_RISE else "")
        print(f"{ICON[i['level']]} {label:<9}  {i['avg']:6.1f}  {change:<15}  "
              f"{i['swing']:5.1f}  {temp:>5}{flags}"
              f"{'  ← today' if d == today else ''} | font=Menlo-Regular size=12")
    low = local_normal() - BELOW_NORMAL
    print("The dot is a heads-up for that day: 🟡 = pressure will be 5+ hPa lower by the next day "
          "(headaches tend to start the day before the low) | size=11 color=gray")
    print(f"🔴 = that drop, and it ends up unusually low ({low:.0f} or below; normal here is "
          f"{local_normal():.0f}) · ⚪ = forecast doesn't reach far enough | size=11 color=gray")
    print(f"range = high−low within the day · temp = change by the next day, {DEG} · "
          f"⚡🌡 = unusually big (info only) | size=11 color=gray")
    print("---")

    py, script = sys.executable, os.path.abspath(__file__)
    if today.isoformat() in logged:
        row = logged[today.isoformat()]
        kind = (row.get("type") or "headache").lower()
        what = f"{kind} {row['severity']}/10" if row["headache"] == "yes" else "no headache"
        print(f"✓ Logged today: {what}  (edit) | bash=\"{py}\" param1=\"{script}\" param2=--log "
              "terminal=false refresh=true")
    else:
        print(f"📝 Log today | bash=\"{py}\" param1=\"{script}\" param2=--log "
              "terminal=false refresh=true")
    # Unlogged days count as headache-free, so this is for catching up, not a chore.
    print(f"📝 Log another day… | bash=\"{py}\" param1=\"{script}\" param2=--log "
          "param3=pick terminal=false refresh=true")

    report = os.path.join(HERE, "report.py")
    print(f"📊 Show my pattern | bash=\"{py}\" param1=\"{report}\" terminal=false")

    color = "red" if n_meds >= MEDS_LIMIT_COMBO else "orange" if n_meds >= MEDS_WARN else "gray"
    print(f"Meds days in {today.strftime('%B')}: {n_meds} | color={color}")
    note = meds_note(n_meds)
    if note:
        print(f"{note} | size=11 color={color}")
    since = days_since_preventive()
    if since is not None:
        print(f"{PREVENTIVE}: {since} days since last dose | color=gray")
    print("---")
    print(f"Change location… | bash=\"{py}\" param1=\"{script}\" param2=--setup "
          "terminal=true refresh=true")
    print("Refresh | refresh=true")


# ---------------------------------------------------------------- setup

def curl_json(url):
    r = subprocess.run(["/usr/bin/curl", "-sf", "--max-time", "20", url],
                       capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 else None


def geocode(query):
    """Candidate places for a city name or zip code, best matches first."""
    base = ("https://geocoding-api.open-meteo.com/v1/search?count=8&language=en&format=json"
            f"&name={urllib.parse.quote(query)}")
    # A bare 5-digit number is almost always a US zip; unfiltered, "60118" matches France.
    tries = [base + "&countryCode=US", base] if query.isdigit() and len(query) == 5 else [base]
    for url in tries:
        results = (curl_json(url) or {}).get("results") or []
        if results:
            return results
    return []


def parse_latlon(text):
    parts = text.replace(" ", "").split(",")
    if len(parts) != 2:
        return None
    try:
        lat, lon = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None


def setup():
    print("Headache Forecast: setup\n")
    print("Enter a city (\"Chicago\"), a US zip code (\"60601\"), or latitude,longitude (\"41.88,-87.63\").")
    while True:
        query = input("\nLocation: ").strip()
        if not query:
            continue
        coords = parse_latlon(query)
        if coords:
            lat, lon = coords
            info = curl_json("https://api.open-meteo.com/v1/forecast"
                             f"?latitude={lat}&longitude={lon}&timezone=auto&forecast_days=1") or {}
            tz = info.get("timezone", "auto")
            place = input("Name for this place (e.g. \"Home\"): ").strip() or f"{lat}, {lon}"
            unit = input("Temperature in F or C? [F]: ").strip().upper() or "F"
            break
        results = geocode(query)
        if not results:
            print("No matches. Try the nearest city name, or latitude,longitude.")
            continue
        for n, r in enumerate(results, 1):
            where = ", ".join(x for x in (r.get("admin1"), r.get("country")) if x)
            print(f"  {n}. {r['name']}, {where}")
        pick = input("Which one? (number, or Enter to search again): ").strip()
        if not pick.isdigit() or not 1 <= int(pick) <= len(results):
            continue
        r = results[int(pick) - 1]
        lat, lon, tz = r["latitude"], r["longitude"], r.get("timezone", "auto")
        place = ", ".join(x for x in (r["name"], r.get("admin1") if r.get("country_code") == "US"
                                      else r.get("country")) if x)
        unit = "F" if r.get("country_code") == "US" else "C"
        break

    cfg = load_config()  # keep the preventive settings when only the location changes
    cfg.update({"place": place, "lat": round(lat, 4), "lon": round(lon, 4), "timezone": tz,
                "temp_unit": "fahrenheit" if unit.startswith("F") else "celsius"})
    current = cfg.get("preventive") or ""
    prompt = (f"\nPreventive migraine med you take on a schedule [{current}] "
              "(Enter to keep, '-' for none): " if current else
              "\nDo you take a scheduled preventive (e.g. Emgality, Aimovig, Ajovy)? "
              "Name it, or Enter to skip: ")
    ans = input(prompt).strip()
    if ans == "-":
        cfg.pop("preventive", None)
    elif ans:
        cfg["preventive"] = ans
    if cfg.get("preventive"):
        when_ = input(f"Date of your last {cfg['preventive']} dose (YYYY-MM-DD, Enter to skip): ").strip()
        try:
            cfg["preventive_last_dose"] = date.fromisoformat(when_).isoformat()
        except ValueError:
            pass
        print("  Future doses: log them from the menu bar (📝 → meds → preventive).")
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
    print(f"\nSaved: {place} ({cfg['lat']}, {cfg['lon']}), {tz}.")
    print("You can close this window. The menu bar will update on its next refresh.")


# ---------------------------------------------------------------- main

def main():
    if "--log" in sys.argv:
        day = pick_day_dialog() if "pick" in sys.argv else date.today()
        if day:
            log_dialog(day)
        return

    if "--setup" in sys.argv:
        setup()
        return

    swiftbar = "--swiftbar" in sys.argv
    if LAT is None:
        py, script = sys.executable, os.path.abspath(__file__)
        if swiftbar:
            print("⚙️ Set location")
            print("---")
            print(f"Set your location… | bash=\"{py}\" param1=\"{script}\" param2=--setup "
                  "terminal=true refresh=true")
        else:
            notify("Migraine predictor", "No location set yet. Choose one from the menu bar.")
            print(f"No location set. Run: python3 {script} --setup", file=sys.stderr)
        sys.exit(1)

    try:
        # Menu bar refreshes every 30 min anyway, so don't block it retrying.
        times, pressure, temp = fetch_hourly(attempts=1 if swiftbar else 6)
    except RuntimeError as e:
        if swiftbar:
            print("⚪ offline")
            print("---")
            print("Couldn't reach the weather service. Will retry. | color=gray")
            print("Refresh | refresh=true")
        else:
            notify("Migraine predictor", "Couldn't get tomorrow's forecast (no internet?). Check the menu bar later.")
            print(e, file=sys.stderr)
        sys.exit(1)

    now = datetime.now()
    now_i = min(range(len(times)), key=lambda i: abs((times[i] - now).total_seconds()))
    summary = daily_summary(times, pressure, temps=temp)

    if swiftbar:
        print_swiftbar(summary, pressure[now_i], temp[now_i])
        return

    tomorrow = date.today() + timedelta(days=1)
    info = summary[tomorrow]

    if "--quiet" not in sys.argv:
        print(f"Tomorrow's migraine pressure risk: {info['level']}")
        print(f"  {describe(tomorrow, info)}")
        print(f"  Now: {pressure[now_i]:.1f} hPa, {temp[now_i]:.0f}{DEG} ({PLACE})")
        print("  Daily averages:")
        for d in sorted(summary):
            i = summary[d]
            ch = "" if i["delta"] is None else f"{i['delta']:+.1f}"
            print(f"    {d.strftime('%a %-m/%-d'):>9}  {i['avg']:7.1f}  {ch:>6}  {i['level']}")

    log_history(now, tomorrow, info)

    extra = meds_note(meds_this_month())
    extra = f" {extra}" if extra else ""
    if info["level"] == "HIGH":
        notify("Migraine risk tomorrow: HIGH",
               f"{describe(tomorrow, info)}. Protect sleep, eat regularly, hydrate, and keep meds handy.{extra}")
    elif info["level"] == "MODERATE":
        notify("Migraine risk tomorrow: moderate",
               f"{describe(tomorrow, info)}. Keep other triggers low and stay hydrated.{extra}")
    elif "--always" in sys.argv:
        notify("Migraine risk tomorrow: low", f"{describe(tomorrow, info)}.{extra}")


if __name__ == "__main__":
    main()
