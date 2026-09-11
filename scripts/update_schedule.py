#!/usr/bin/env python3
"""
Poor Decisions - weekly schedule updater.
Scrapes the TAO Group promoter page, keeps ONLY "Guest List" (Passes) events,
and works out which venues have guest list availability on which weekdays.
Writes schedule.json at repo root. Non-TAO venues (XS, Zouk, Encore Beach,
Wet Republic) are not on this page and are left untouched by the planner.
"""
import re, json, sys
from datetime import datetime, timedelta
from urllib.request import urlopen, Request

URL = ("https://tickets.taogroup.com/promoter/"
       "6590bba0-bfe4-4f86-b3c0-7d550ad120a1?utm_source=promoter"
       "&utm_id=6590bba0299c4fd084f67d550ad120a1")

# TAO page venue name -> planner club id
VENUE_MAP = {
    "OMNIA Nightclub":   "omnia",
    "Hakkasan Nightclub":"hakkasan",
    "TAO Nightclub":     "tao",
    "Marquee Nightclub": "marquee",
    "JEWEL Nightclub":   "jewel",
    "OMNIA Dayclub":     "omnia-day",
    "Marquee Dayclub":   "mq-day",
    "TAO Beach Dayclub": "tao-beach",
}

def main():
    req = Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    html = urlopen(req, timeout=60).read().decode("utf-8", "ignore")
    # Strip tags so text matches regardless of markup changes
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)

    venues_alt = "|".join(re.escape(v) for v in VENUE_MAP)
    # Match: Guest List - <title> <Weekday>, <Mon> <D>, <YYYY> ... <Venue>
    pattern = re.compile(
        r"Guest List - (.{0,120}?)"
        r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), "
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{1,2}), (\d{4})"
        r".{0,160}?(" + venues_alt + ")"
    )

    today = datetime.now()
    horizon = today + timedelta(weeks=12)
    days = {vid: set() for vid in VENUE_MAP.values()}
    count = 0

    for m in pattern.finditer(text):
        title, _dow, mon, day, year, venue = m.groups()
        if "CLOSED" in title.upper():
            continue
        try:
            dt = datetime.strptime(f"{mon} {day} {year}", "%b %d %Y")
        except ValueError:
            continue
        if not (today - timedelta(days=1) <= dt <= horizon):
            continue
        # JS getDay(): Sun=0 ... Sat=6 ; Python weekday(): Mon=0 ... Sun=6
        js_dow = (dt.weekday() + 1) % 7
        days[VENUE_MAP[venue]].add(js_dow)
        count += 1

    if count < 10:
        print(f"Only parsed {count} guest list events - page layout may have "
              f"changed. Refusing to overwrite schedule.json.")
        sys.exit(1)

    out = {vid: sorted(d) for vid, d in days.items() if d}
    out["_updated"] = today.strftime("%Y-%m-%d")
    out["_source"] = "taogroup promoter page - Guest List (Passes) events only"

    with open("schedule.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote schedule.json from {count} guest list events:")
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()
