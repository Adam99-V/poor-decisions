#!/usr/bin/env python3
"""Poor Decisions - daily schedule + DJ updater.
Scrapes the TAO Group promoter page, keeps ONLY 'Guest List' (Passes) events,
and writes schedule.json with:
  - per-venue weekday availability  (e.g. "omnia": [0,2,4,5,6])
  - events: { "YYYY-MM-DD": { "omnia": "DJ Name", ... } }
"""
import re, json, sys, html as htmlmod
from datetime import datetime, timedelta

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

# ===== Cloudflare-aware page fetch (real Chrome, waits for the "Performing security verification" page to clear) =====
UA=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36")

def _new_browser(pw):
    args=["--disable-blink-features=AutomationControlled","--no-first-run","--no-default-browser-check"]
    for channel in ("chrome","chromium"):
        try:
            if channel=="chrome": return pw.chromium.launch(channel="chrome",headless=True,args=args)
            return pw.chromium.launch(headless=True,args=args)
        except Exception as e:
            print(f"launch {channel} failed: {type(e).__name__}")
    raise RuntimeError("no browser available")

def _new_context(browser):
    ctx=browser.new_context(user_agent=UA,viewport={"width":1366,"height":850},locale="en-US",
                            timezone_id="America/Los_Angeles",
                            extra_http_headers={"Accept-Language":"en-US,en;q=0.9"})
    ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                        "window.chrome={runtime:{}};"
                        "Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});"
                        "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});")
    return ctx

def wait_past_cloudflare(page, ok_text, timeout_s=75):
    """Return True once the page shows real content (ok_text), False if the challenge never clears."""
    import time as _t
    t0=_t.time()
    while _t.time()-t0<timeout_s:
        try: body=page.inner_text("body")
        except Exception: body=""
        if ok_text.lower() in body.lower(): return True
        _t.sleep(2)
    return False

def fetch_html(url, ok_text):
    """Open url in a real browser, get past Cloudflare, return the full HTML."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b=_new_browser(pw); ctx=_new_context(b); page=ctx.new_page()
        page.goto(url,wait_until="domcontentloaded",timeout=60000)
        ok=wait_past_cloudflare(page, ok_text)
        if not ok:
            snippet=(page.inner_text("body") or "")[:300].replace("\n"," ")
            b.close(); raise RuntimeError("Cloudflare challenge did not clear. Page said: "+snippet)
        html=page.content(); b.close(); return html

def main():
    html=fetch_html(URL,"Guest List")
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
