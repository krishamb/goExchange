"""li.py <tag> -> one public LinkedIn job search per run (rebuilt 2026-11-28).

LinkedIn answers about 8 guest requests a day at hourly spacing, then 429, so every run spends exactly ONE request on a
public search page (never signed in, never a job page): the next query in QUERIES (rotation index 'li_rot' in
blocks.json), past 24 hours. Cards (company, title, location, listed date) pass harvest.py's title / location rules and
gates.allow; each survivor is then resolved on the employer's own board when the company's Greenhouse / Ashby / Lever
board is in boards.json (title match, employer publish date inside the 7-day window -> route one_click / bot_hold),
otherwise it is listed for resolving on the employer site by hand (route "resolve"). Rows -> <scratchpad>/harvest/li_<tag>.json.
The first 401 / 403 / 406 / 429 / 503 / 999 pauses www.linkedin.com 24 h (blocks.json); the run stops at once."""
import datetime, html, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import gates as g
SC = "/tmp/claude-0/-home-user-goExchange/8d20ffb7-2488-5f8f-a666-35334b9e3ba6/scratchpad"
OUTD = os.path.join(SC, "harvest"); os.makedirs(OUTD, exist_ok=True)
tag = sys.argv[1]
LEAD = '("VP of Engineering" OR "VP Engineering" OR "Head of Engineering" OR "CTO" OR "Chief Technology Officer" OR "Director of Engineering" OR "VP of AI" OR "Head of AI")'
IC = '("Principal Engineer" OR "Staff Engineer" OR "Principal Software Engineer" OR "Staff Software Engineer" OR "Software Architect" OR "Distinguished Engineer")'
AI = '("Director of AI" OR "Head of Machine Learning" OR "Director of Machine Learning" OR "VP of Machine Learning" OR "AI Architect" OR "Head of Data")'
FINCRYPTO = '("Head of Engineering" OR "CTO" OR "VP Engineering" OR "Director of Engineering") AND (crypto OR blockchain OR payments OR fintech OR stablecoin)'
US, BAY = ("United States", "103644278"), ("San Francisco Bay Area", "90000084")
QUERIES = [(LEAD, US, "2"), (LEAD, BAY, ""), (IC, US, "2"), (AI, US, "2"), (IC, BAY, ""), (AI, BAY, ""), (FINCRYPTO, US, "2"), (FINCRYPTO, BAY, "")]
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}
BLK = os.path.join(HERE, "blocks.json"); HOST = "www.linkedin.com"
try: BLOCKS = json.load(open(BLK))
except Exception: BLOCKS = {}
def save_block(key, val):
    try: cur = json.load(open(BLK))
    except Exception: cur = {}
    cur[key] = val; BLOCKS[key] = val; json.dump(cur, open(BLK, "w"), indent=1)
FROM = os.environ.get("LI_FROM")   # parse a saved search page (no request, no pause / rotation change)
if not FROM and time.time() < float(BLOCKS.get(HOST, {}).get("until", 0)):
    raise SystemExit(f"li: {HOST} paused until {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(float(BLOCKS[HOST]['until'])))}")
if not FROM and time.time() - float(BLOCKS.get("li_last", {}).get("t", 0)) < 50 * 60: raise SystemExit("li: less than 50 minutes since the last LinkedIn request")
src = open(os.path.join(HERE, "harvest.py")).read(); ns = {"re": re}
for nm in ("ENG", "LEVEL", "NO", "NONUS", "USOK", "BAY", "US_CITY", "STAFF", "FRONTIER", "FIN"):
    exec(re.search(rf"^{nm} = re\.compile\(.*\)$", src, re.M).group(0), ns)
exec(src[src.index("def loc_ok("):src.index("STAFF = re.compile(")], ns)
loc_ok = ns["loc_ok"]
def txt(x): return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x or ""))).strip()

rot = int(BLOCKS.get("li_rot", {}).get("i", 0)) % len(QUERIES)
kw, (loc, geo), wt = QUERIES[rot]
q = {"keywords": kw, "location": loc, "geoId": geo, "f_TPR": "r86400", "position": "1", "pageNum": "0"}
if wt: q["f_WT"] = wt
url = "https://www.linkedin.com/jobs/search/?" + urllib.parse.urlencode(q)
if FROM: page = open(FROM).read()
else:
  save_block("li_last", {"t": time.time()}); save_block("li_rot", {"i": rot + 1})
  try:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        if urllib.parse.urlsplit(r.geturl()).path.startswith(("/authwall", "/login", "/checkpoint")): raise urllib.error.HTTPError(url, 999, "auth wall", None, None)
        page = r.read().decode("utf-8", "replace")
  except urllib.error.HTTPError as e:
    if e.code in (401, 403, 406, 429, 503, 999):
        save_block(HOST, {"until": time.time() + 86400, "code": e.code, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    raise SystemExit(f"li: HTTP {e.code} on query {rot} - {'paused 24 h' if e.code in (401, 403, 406, 429, 503, 999) else 'not paused'}")
  except Exception as e: raise SystemExit(f"li: {type(e).__name__} on query {rot}")
  open(os.path.join(OUTD, f"li_{tag}.html"), "w").write(page)   # kept for re-parsing (LI_FROM)

def parse_cards(page):
  out = []
  for blk in re.split(r"<li[ >]", page)[1:]:
    m = re.search(r"urn:li:jobPosting:(\d+)", blk)
    t = re.search(r'class="base-search-card__title"[^>]*>(.*?)</h3>', blk, re.S)
    c = re.search(r'class="base-search-card__subtitle"[^>]*>(.*?)</h4>', blk, re.S)
    l = re.search(r'class="job-search-card__location"[^>]*>(.*?)</span>', blk, re.S)
    d = re.search(r'<time[^>]*datetime="([\d-]+)"', blk)
    if m and t and c: out.append({"li_id": m.group(1), "title": txt(t.group(1)), "company": txt(c.group(1)), "loc": txt(l.group(1)) if l else "", "listed": d.group(1) if d else ""})
  return out
cards = parse_cards(page)
print(f"li {tag}: query {rot} ({loc}{', remote' if wt == '2' else ''}) -> {len(cards)} cards")

B = json.load(open(os.path.join(HERE, "boards.json"))); idx = {a: {g.norm(s): s for s in v} for a, v in B.items()}
def board_lookup(co, ti):
    """(ats, url, published_ts) of the title on the company's own Greenhouse / Ashby / Lever board, if the board is known."""
    for a in ("ashby", "lever", "greenhouse"):
        slug = idx.get(a, {}).get(g.norm(co)) or idx.get(a, {}).get(g.key(co))
        if not slug: continue
        time.sleep(1)
        try:
            u = {"ashby": f"https://api.ashbyhq.com/posting-api/job-board/{slug}", "lever": f"https://api.lever.co/v0/postings/{slug}?mode=json",
                 "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"}[a]
            d = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA["User-Agent"]}), timeout=30).read())
        except Exception: continue
        jobs = d.get("jobs", []) if isinstance(d, dict) else d
        for j in jobs:
            jt = j.get("title") or j.get("text") or ""
            if g.same_role(jt, ti) or jt.strip().lower() == ti.strip().lower():
                ts = j.get("publishedAt") or j.get("createdAt") or j.get("first_published") or j.get("updated_at")
                try: pub = (ts / 1000) if isinstance(ts, (int, float)) else datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
                except Exception: pub = None
                return a, j.get("jobUrl") or j.get("hostedUrl") or j.get("absolute_url") or "", pub
        return a, "", None
    return "", "", None

keep, why = [], {}
def W(k): why[k] = why.get(k, 0) + 1
for c in cards:
    t, co = c["title"], c["company"]
    if not ns["ENG"].search(t) or not ns["LEVEL"].search(t) or ns["NO"].search(t): W("title"); continue
    if ns["STAFF"].search(co): W("staffing"); continue
    if ns["FRONTIER"].search(co.strip()) and not ns["FIN"].search(t): W("frontier lab: finance roles only"); continue
    ok, lw = loc_ok([c["loc"]], wt == "2", "Remote" if wt == "2" else "")
    if not ok: W("location: " + lw); continue
    ok, gw = g.allow(co, t, extra=keep)
    if not ok: W("gate: " + gw.split("(")[0].strip()); continue
    a, u, pub = board_lookup(co, t)
    if a and not u: W("employer board known, no exact title match (listed to resolve)")   # LinkedIn titles often differ from the ATS title
    if pub and pub < time.time() - 7 * 86400: W("employer publish date older than 7 days"); continue
    route = {"ashby": "one_click", "lever": "one_click", "greenhouse": "bot_hold"}.get(a, "resolve") if (u or not a) else "resolve"
    keep.append({"route": route, "ats": a, "company": co, "title": t, "url": u, "apply_url": "",
                 "note": f"LinkedIn {c['listed'] or 'last 24 h'} ({c['loc']}; {lw})" + (f"; employer board {a}" if a and u else f"; {a} board known, title not matched: check it" if a else "; find the employer's own posting"), "li_id": c["li_id"]})
json.dump(keep, open(os.path.join(OUTD, f"li_{tag}.json"), "w"), indent=0)
print(f"li {tag}: kept {len(keep)} | dropped {dict(sorted(why.items(), key=lambda x: -x[1]))}")
for k in keep: print(f"  {k['route']:9} | {k['company'][:24]:24} | {k['title'][:60]:60} | {k['note'][:70]:70} | {k['url'][:90]}")
