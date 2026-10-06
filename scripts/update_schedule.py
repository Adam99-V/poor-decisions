#!/usr/bin/env python3
"""Poor Decisions - daily schedule + DJ updater.
Scrapes the TAO Group promoter page, keeps ONLY 'Guest List' (Passes) events,
and writes schedule.json with:
  - per-venue weekday availability  (e.g. "omnia": [0,2,4,5,6])
  - events: { "YYYY-MM-DD": { "omnia": "DJ Name", ... } }
"""
import re, json, sys, time, html as htmlmod
from datetime import datetime, timedelta
from urllib.request import urlopen, Request

URL=("https://tickets.taogroup.com/promoter/6590bba0-bfe4-4f86-b3c0-7d550ad120a1"
     "?utm_source=promoter&utm_id=6590bba0299c4fd084f67d550ad120a1")
VENUE_MAP={"OMNIA Nightclub":"omnia","Hakkasan Nightclub":"hakkasan","TAO Nightclub":"tao",
           "Marquee Nightclub":"marquee","JEWEL Nightclub":"jewel","OMNIA Dayclub":"omnia-day",
           "Marquee Dayclub":"mq-day","TAO Beach Dayclub":"tao-beach"}

def clean_dj(title):
    # "Guest List - DJ Name - Some Weekend" -> "DJ Name"
    t=title.split(" - ")[0].strip()
    t=re.sub(r"\s+(at|@)\s+.*$","",t,flags=re.I)
    return t[:40]

UA=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36")
HEADERS={"User-Agent":UA,"Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
         "Accept-Language":"en-US,en;q=0.9","Cache-Control":"no-cache","Pragma":"no-cache"}

def fetch(url):
    """GET with a real browser fingerprint, 4 attempts with backoff. Prints the HTTP status on failure."""
    last=None
    for attempt in range(4):
        try:
            r=urlopen(Request(url,headers=HEADERS),timeout=60)
            body=r.read().decode("utf-8","ignore")
            if len(body)>5000: return body
            last=f"short response ({len(body)} bytes)"
        except Exception as e:
            last=f"{type(e).__name__}: {str(e)[:120]}"
        print(f"fetch attempt {attempt+1} failed: {last}"); time.sleep(15*(attempt+1))
    print("Could not fetch the promoter page, keeping yesterday's schedule.json"); sys.exit(1)

def main():
    html=fetch(URL)
    text=htmlmod.unescape(re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",html)))
    venues="|".join(re.escape(v) for v in VENUE_MAP)
    pat=re.compile(r"Guest List - (.{0,120}?)(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), "
                   r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{1,2}), (\d{4}).{0,160}?("+venues+")")
    today=datetime.now(); horizon=today+timedelta(weeks=12)
    days={v:set() for v in VENUE_MAP.values()}; events={}; n=0
    for m in pat.finditer(text):
        title,_,mon,day,year,venue=m.groups()
        if re.search(r"closed|password|private|sold out|invite only|unavailable", title, re.I): continue
        tail=text[m.end():m.end()+200]
        if re.search(r"password|private|sold out|invite only|unavailable", tail, re.I): continue
        try: dt=datetime.strptime(f"{mon} {day} {year}","%b %d %Y")
        except ValueError: continue
        if not(today-timedelta(days=1)<=dt<=horizon): continue
        vid=VENUE_MAP[venue]; days[vid].add((dt.weekday()+1)%7); n+=1
        events.setdefault(dt.strftime("%Y-%m-%d"),{}).setdefault(vid,clean_dj(title))
    if n<10:
        print(f"Only {n} guest list events parsed - layout may have changed. Not overwriting.")
        print("Page sample:", text[:600]); sys.exit(1)
    out={v:sorted(d) for v,d in days.items() if d}
    out["events"]=dict(sorted(events.items()))
    out["_updated"]=today.strftime("%Y-%m-%d %H:%M")
    out["_source"]="taogroup promoter page - Guest List (Passes) events only"
    json.dump(out,open("schedule.json","w"),indent=2)
    print(f"Wrote schedule.json: {n} events, {len(events)} dates")
if __name__=="__main__": main()
