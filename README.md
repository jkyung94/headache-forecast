# Headache Forecast

A small Mac menu bar tool that warns you the night before pressure-drop days,
lets you log headaches in a few clicks, and shows whether weather, triggers or
your preventive medication actually line up with *your* headaches.

Everything stays on your Mac. The only thing sent online is your location's
coordinates, to download the weather from [Open-Meteo](https://open-meteo.com)
(free, no account).

> Not medical advice. It counts patterns in your own log. Talk to your doctor
> about treatment, and before taking medication preventively.

## Install

1. Download: on the GitHub page, click **Code → Download ZIP**, then open the zip
   (or get the zip from a friend). Double-click **install.command** inside.
   If macOS says it can't be opened, right-click it → **Open** → **Open**.
2. It checks for Python 3 and SwiftBar and helps install either if missing.
   If Apple's Command Line Tools installer appears, let it finish, then run
   install.command again.
3. Enter your city or zip code, and a preventive medication if you take one
   (e.g. Emgality, Aimovig, Ajovy). You can skip that part.
4. A colored dot appears in the menu bar. In SwiftBar's menu → Preferences, turn
   on **Launch at login**.

Files live in `~/headache-forecast`. Running the installer again upgrades the
code and keeps your log.

## What you'll see

**The dot** is the risk for today, or for tomorrow after 6pm:

- 🟢 **Low**
- 🟡 **Moderate**: pressure will be 5+ hPa lower by the next day
- 🔴 **High**: that drop, and pressure ends up unusually low for where you live

Click it for a week of daily pressure, the in-day range and temperature changes.

**A 9pm notification** arrives only on 🟡/🔴 nights, so it's quiet most of the year.

## Where the rules come from

- **Kimoto et al., 2011** (28 people): migraines became more frequent when the
  daily pressure fell more than 5 hPa. The headaches landed on the day *before*
  the lower-pressure day, so that's the day the dot flags.
- **Okuma et al., 2015** (34 people): attacks were most frequent when pressure
  sat 6–10 hPa below the 1013 hPa standard. The tool uses 6 below *your local*
  normal (your past-year average) instead, since normal pressure varies by place.

Both studies are small, and weather sensitivity varies a lot between people.
That's what the log and report are for.

## Logging

Menu → **📝 Log today**. A few quick dialogs ask the kind of headache, when it
started, severity, other symptoms, meds, possible triggers, and notes.

- **Only log when you're in pain if you like.** Days you don't log count as
  headache-free. Logging a good day now and then (with whatever was going on)
  lets the report test triggers properly.
- **Log another day…** fills in or edits any of the last 14 days. Edits start
  from your earlier answers.
- Days with signs of being sick (fever, body aches, congestion…) are set aside,
  so a flu headache doesn't count for or against the weather.
- If you tick **fever and neck stiffness** together, it tells you to check with
  a doctor. That combination with a headache can be serious.

## The pattern report

Menu → **📊 Show my pattern** opens a page in your browser that compares your
headache rate on days with vs. without each thing:

- pressure drops (the day before vs. the day of), big in-day swings, and warm-ups
- a migraines-only version
- each trigger you've logged
- weeks since your preventive dose
- acute-meds days per month

Verdicts use a standard statistical test (Fisher's exact test) and wait for 21
days of data. Winter has far more pressure drops than summer, so the weather
section needs a season to say much.

## Meds counter

The menu counts days with acute meds this month and turns orange at 8, red at 10.
Rebound (medication-overuse) headache can start at **10+ days a month** for
triptans and combination pills like Excedrin, and **15+** for Advil, Aleve or
Tylenol. Preventive doses don't count.

## Troubleshooting

- **No dot in the menu bar:** it may be behind the notch (hold ⌘ and drag other
  icons off), or you're in a full-screen app (move the mouse to the top edge).
- **No notifications:** System Settings → Notifications → Script Editor → allow.
- **Change location or preventive:** menu → Change location…
- **Missed the 9pm check** (Mac asleep or offline): it runs when the Mac wakes and
  retries for about 5 minutes if there's no internet yet.

## Your files (`~/headache-forecast`)

| File | What it is |
|---|---|
| `log.csv` | Your headache log. Opens in Numbers or Excel |
| `history.csv` | What each nightly check predicted |
| `config.json` | Location and preventive settings |
| `local_climate.json` | Your location's normal pressure and "unusual" levels, refreshed monthly |
| `report.html` | The latest pattern report |

## Limitations

- The ⚡ (big in-day pressure range) and 🌡 (big warm-up) markers are measured from
  your own location's past year: the top ~15% and ~10% of days there. There's no
  research threshold for either, so they're info only and don't drive alerts.
- The 🟡 rule is a fixed 5 hPa daily drop, straight from the study, so alerts come
  more often in stormy climates (e.g. the Midwest in winter) than in steady ones
  (e.g. Florida, Southern California). `python3 backtest_thresholds.py` shows how
  often they would have fired where you live over the past year.
- Pressure is forecast at one point for your town. Forecasts more than 3–4 days out
  are rough.

## For developers

Plain Python 3.8+ standard library (see `requirements.txt`: nothing to install).

| File | Role |
|---|---|
| `predict.py` | Forecast, risk rules, menu bar output, nightly check, logging, setup |
| `report.py` | "Show my pattern" HTML report |
| `backtest_thresholds.py` | How often the alert rules fire over a past year for your location |
| `log_dialog.applescript` | The native log dialogs (note: `kind` is reserved in AppleScript) |
| `install.command` / `uninstall.command` | Setup for non-programmers |

Try it without installing: `python3 predict.py --setup`, then `python3 predict.py --swiftbar`.
To test the installer without touching your system:
`HF_DEST=/tmp/hf HF_AGENTS=/tmp/hf-agents HF_DRY_RUN=1 bash install.command`.
Personal files (`config.json`, `log.csv`, …) are in `.gitignore`.

## Uninstall

Double-click **uninstall.command**. It removes the menu item and the nightly check,
then asks before deleting your log.
