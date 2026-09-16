#!/usr/bin/env python3
"""Poor Decisions - TAO guest list auto-registration.

Input: PAYLOAD env var (JSON) =
  {ref, name, email, zip, males, females,
   events:[{date:'YYYY-MM-DD', venueId:'omnia', venue:'Omnia', slot:'night'}]}

For every event at a TAO venue it finds the promoter's guest list link for that
venue + date, opens it in a real Chrome, sets the female / male quantities, fills
the customer's details, accepts the terms, submits, and records the result.

Results are POSTed back to the Apps Script web app (WEBAPP_URL + ADMIN_KEY env)
as {action:'glresult', key, ref, results:[{date, venueId, venue, ok, url, order, error}]}.

Never prints customer name / email (the repo is public, so are the logs).
"""
import os, re, sys, json, time, random, html
from datetime import datetime
from urllib.request import urlopen, Request

PROMOTER_URL = ("https://tickets.taogroup.com/promoter/6590bba0-bfe4-4f86-b3c0-7d550ad120a1"
                "?utm_source=promoter&utm_id=6590bba0299c4fd084f67d550ad120a1")
UTM = "utm_source=promoter&utm_id=6590bba0299c4fd084f67d550ad120a1"

# our planner venue IDs -> the venue name TAO prints on the promoter page
TAO = {"omnia": "OMNIA Nightclub", "hakkasan": "Hakkasan Nightclub", "tao": "TAO Nightclub",
       "marquee": "Marquee Nightclub", "jewel": "JEWEL Nightclub", "omnia-day": "OMNIA Dayclub",
       "mq-day": "Marquee Dayclub", "tao-beach": "TAO Beach Dayclub", "wet-rep": "Palm Tree Beach Club"}

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0.0.0 Safari/537.36")

def log(*a): print(*a, flush=True)

def find_links():
    """Scrape the promoter page -> {(tao_venue_name, 'YYYY-MM-DD'): tickets_url}"""
    raw = urlopen(Request(PROMOTER_URL, headers={"User-Agent": UA}), timeout=60).read().decode("utf-8", "ignore")
    # keep hrefs as text tokens, drop every other tag
    t = re.sub(r'<a\s[^>]*href="([^"]+)"[^>]*>', r' HREF:\1 ', raw, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t); t = html.unescape(re.sub(r"\s+", " ", t))
    venues = "|".join(re.escape(v) for v in TAO.values())
    pat = re.compile(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), "
                     r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{1,2}), (\d{4})"
                     r".{0,200}?(" + venues + r"), Las Vegas, NV.{0,400}?HREF:(https?://\S+?/e/\S+?/tickets)\b")
    out = {}
    for m in pat.finditer(t):
        _, mon, day, year, venue, url = m.groups()
        try: d = datetime.strptime(f"{mon} {day} {year}", "%b %d %Y").strftime("%Y-%m-%d")
        except ValueError: continue
        # skip closed / password / sold out events (text just before the link)
        window = t[max(0, m.start() - 300):m.end()]
        if re.search(r"password|private|sold out|invite only|unavailable|closed", window, re.I): continue
        out.setdefault((venue, d), url)
    log(f"promoter page: {len(out)} guest list events found")
    return out

def pick_select(page, label_word):
    """Return the quantity control inside the 'Guest List - Female' / 'Guest List - Male' card.
    Handles native <select>, inputs, and custom dropdowns (role=combobox / listbox buttons)."""
    handle = page.evaluate_handle(r"""(word) => {
      const re = new RegExp('Guest\\s*List\\s*[-–]\\s*' + word, 'i');
      const cands = [...document.querySelectorAll('select, input[type=number], [role=combobox], [role=listbox], button[aria-haspopup]')];
      for (const c of cands) {
        let el = c;
        for (let i = 0; i < 10 && el; i++) {
          el = el.parentElement; if (!el || el === document.body) break;
          const txt = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ');
          if (txt.length > 900) break;
          if (re.test(txt)) return c;
        }
      }
      return null;
    }""", label_word)
    return handle.as_element()

def dump_form(page):
    """Diagnostic: list form controls (no customer data is on the page yet at this point)."""
    info = page.evaluate(r"""() => {
      const out = [];
      for (const el of document.querySelectorAll('select, input, button, [role=combobox], [role=listbox]')) {
        const near = (el.closest('div,li,tr,section') || el).innerText || '';
        out.push([el.tagName, el.type || '', el.name || '', el.id || '', (el.className || '').toString().slice(0, 60),
                  el.tagName === 'SELECT' ? el.options.length + ' opts' : '', near.replace(/\\s+/g, ' ').slice(0, 70)].join(' | '));
      }
      return { n: out.length, iframes: document.querySelectorAll('iframe').length, url: location.href, els: out.slice(0, 60) };
    }""")
    log("DEBUG url:", info["url"], "| controls:", info["n"], "| iframes:", info["iframes"])
    for line in info["els"]: log("   ", line)

def set_qty(page, word, n):
    sel = pick_select(page, word)
    if sel is None:
        if n == 0: return True
        dump_form(page)
        raise RuntimeError(f"no {word} quantity selector on page")
    tag = sel.evaluate("el => el.tagName")
    if tag == "SELECT":
        try: sel.select_option(label=str(n))
        except Exception: sel.select_option(value=str(n))
    elif tag == "INPUT":
        sel.fill(str(n))
    else:                                   # custom dropdown: open it, click the option with the number
        sel.click(); page.wait_for_timeout(400)
        page.get_by_role("option", name=re.compile(r"^\s*" + str(n) + r"\s*$")).first.click()
    page.wait_for_timeout(700)
    return True

def fill(page, label_regex, fallback_css, value):
    loc = page.get_by_label(re.compile(label_regex, re.I))
    if loc.count() == 0:
        loc = page.locator(fallback_css)
    loc.first.fill(value)

def click_checkbox(page, must_contain, want_checked):
    boxes = page.locator('input[type="checkbox"]')
    for i in range(boxes.count()):
        b = boxes.nth(i)
        txt = b.evaluate(r"""el => { let e = el; for (let i=0;i<6&&e;i++){ e=e.parentElement; if(!e) break;
                 const t=(e.innerText||'').replace(/\\s+/g,' '); if(t.length>300) break; if(t.length>15) return t; } return ''; }""")
        if re.search(must_contain, txt or "", re.I):
            if b.is_checked() != want_checked: b.click()
            return True
    return False

def register(page, url, p):
    first, last = (p["name"].strip().split(" ", 1) + ["Guest"])[:2] if " " in p["name"].strip() else (p["name"].strip(), "Guest")
    page.goto(url + ("&" if "?" in url else "?") + UTM, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1500)
    body = page.inner_text("body")
    if re.search(r"verify you are human|checking your browser|attention required", body, re.I):
        raise RuntimeError("cloudflare challenge")
    if re.search(r"already passed|sold out|not available", body, re.I):
        raise RuntimeError("event closed or sold out")
    set_qty(page, "Female", int(p.get("females") or 0))
    set_qty(page, "Male", int(p.get("males") or 0))
    fill(page, r"email", 'input[type="email"], input[name*="email" i]', p["email"])
    fill(page, r"first\s*name", 'input[name*="first" i], input[id*="first" i]', first)
    fill(page, r"last\s*name", 'input[name*="last" i], input[id*="last" i]', last)
    fill(page, r"postal|zip|post\s*code", 'input[name*="zip" i], input[name*="postal" i], input[id*="zip" i]', p.get("zip") or "00000")
    click_checkbox(page, r"sign up|offers|news", False)          # no marketing on the customer's behalf
    if not click_checkbox(page, r"accept|agree|terms", True):
        dump_form(page)
        raise RuntimeError("terms checkbox not found")
    page.wait_for_timeout(400 + random.randint(0, 800))
    btn = page.get_by_role("button", name=re.compile(r"submit order|submit|complete", re.I)).first
    btn.click()
    page.wait_for_load_state("networkidle", timeout=60000)
    page.wait_for_timeout(1500)
    body = page.inner_text("body"); u = page.url
    if re.search(r"thank you|confirm|success|your order|order number|receipt", body, re.I) or re.search(r"confirm|thank|receipt|order", u, re.I):
        m = re.search(r"(?:order|confirmation)\s*(?:#|number|no\.?|id)?\s*[:#]?\s*([A-Z0-9-]{5,})", body, re.I)
        return {"ok": True, "url": u, "order": m.group(1) if m else ""}
    err = re.search(r"(required|invalid|error|sold out|limit)[^\n]{0,80}", body, re.I)
    raise RuntimeError("no confirmation after submit" + (": " + err.group(0) if err else ""))

def post_results(ref, results):
    url, key = os.environ.get("WEBAPP_URL", ""), os.environ.get("ADMIN_KEY", "")
    if not url or not key: log("WEBAPP_URL / ADMIN_KEY not set, results not reported"); return
    data = json.dumps({"action": "glresult", "key": key, "ref": ref, "results": results}).encode()
    try:
        r = urlopen(Request(url, data=data, headers={"Content-Type": "application/json"}), timeout=60)
        log("reported to dashboard:", r.status)
    except Exception as e:
        log("report failed:", type(e).__name__)

def main():
    p = json.loads(os.environ["PAYLOAD"])
    ref = p.get("ref", "?"); log("booking", ref)
    events = [e for e in p.get("events", []) if e.get("venueId") in TAO]
    if not events: log("no TAO venues in this booking, nothing to do"); return
    delay = int(os.environ.get("DELAY_MAX_SEC", "0") or 0)
    if delay: s = random.randint(30, delay); log(f"waiting {s}s"); time.sleep(s)
    links = find_links(); results = []
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        ctx = b.new_context(user_agent=UA, viewport={"width": 1280, "height": 900}, locale="en-US",
                            timezone_id="America/Los_Angeles")
        page = ctx.new_page()
        for e in events:
            venue = TAO[e["venueId"]]; key = (venue, e["date"])
            r = {"date": e["date"], "venueId": e["venueId"], "venue": e.get("venue", venue), "ok": False, "url": "", "order": "", "error": ""}
            url = links.get(key)
            if not url:
                r["error"] = "no guest list event on promoter page for that date"
            else:
                r["url"] = url
                try:
                    r.update(register(page, url, p))
                except Exception as ex:
                    r["error"] = str(ex)[:160]
            log(f"  {e['date']} {venue}: {'OK ' + (r['order'] or '') if r['ok'] else 'FAILED - ' + r['error']}")
            results.append(r)
            time.sleep(random.randint(8, 25))
        b.close()
    post_results(ref, results)
    if any(not r["ok"] for r in results): sys.exit(2)

if __name__ == "__main__": main()
