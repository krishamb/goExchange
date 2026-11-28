"""builtin.py <tag> [paths] -> Built In job cards from the last day, screened, then each survivor's job page (rebuilt 2026-11-28).

Listing pages (public, never signed in): https://builtin.com/jobs/<path>?daysSinceUpdated=1&page=N for paths such as
remote/dev-engineering/expert-leader (default set below; Bay Area = builtin.com/jobs/hybrid/national/... is not used:
Built In SF pages are https://www.builtinsf.com/jobs/<category>/<level>). Cards give id, title, company, location;
cards pass harvest.py's title rules and gates.allow, then the job page's JobPosting JSON-LD gives datePosted,
location requirements, pay and the employer's site. Rows -> <scratchpad>/harvest/bi_<tag>.json. Seen card ids are kept
in bi_seen.json (repo) so a row is screened once. Sequential, 2 s apart; the first refusal pauses the host 24 h."""
import json, os, re, sys, time, html, urllib.request, urllib.error, urllib.parse
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import gates as g
SC = "/tmp/claude-0/-home-user-goExchange/8d20ffb7-2488-5f8f-a666-35334b9e3ba6/scratchpad"
OUTD = os.path.join(SC, "harvest"); os.makedirs(OUTD, exist_ok=True)
tag = sys.argv[1]
PATHS = (sys.argv[2].split(",") if len(sys.argv) > 2 else
         ["https://builtin.com/jobs/remote/dev-engineering/expert-leader", "https://builtin.com/jobs/remote/data-analytics/expert-leader",
          "https://builtin.com/jobs/remote/dev-engineering/senior", "https://www.builtinsf.com/jobs/dev-engineering/expert-leader"])
MAXPAGES = int(os.environ.get("BI_PAGES", "3"))
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}
BLK = os.path.join(HERE, "blocks.json"); SEEN = os.path.join(HERE, "bi_seen.json")
try: BLOCKS = json.load(open(BLK))
except Exception: BLOCKS = {}
def save_block(key, val):   # merge-on-write: other sweeps may have written blocks.json since this one started
    try: cur = json.load(open(BLK))
    except Exception: cur = {}
    cur[key] = val; BLOCKS[key] = val; json.dump(cur, open(BLK, "w"), indent=1)
try: seen = set(json.load(open(SEEN)))
except Exception: seen = set()
src = open(os.path.join(HERE, "harvest.py")).read(); ns = {"re": re}
for nm in ("ENG", "LEVEL", "NO", "NONUS", "USOK", "BAY", "US_CITY", "STAFF", "FRONTIER", "FIN"):
    exec(re.search(rf"^{nm} = re\.compile\(.*\)$", src, re.M).group(0), ns)
REFUSED = set()
def get(u):
    h = urllib.parse.urlsplit(u).hostname
    if h in REFUSED or time.time() < float(BLOCKS.get(h, {}).get("until", 0)): return None
    time.sleep(2)
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as r: return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 406, 429, 503):
            REFUSED.add(h); save_block(h, {"until": time.time() + 86400, "code": e.code, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}); print("  REFUSED", e.code, h, "- paused 24 h")
        return None
    except Exception: return None
def txt(x): return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x or ""))).strip()

cards, why = {}, {}
def W(k): why[k] = why.get(k, 0) + 1
for base in PATHS:
    for p in range(1, MAXPAGES + 1):
        h = get(f"{base}?daysSinceUpdated=1&page={p}")
        if not h: break
        parts = re.split(r'(?=<div[^>]+id="job-card-\d+")', h)[1:]
        if not parts: break
        n0 = len(cards)
        for c in parts:
            m = re.search(r'id="job-card-(\d+)"', c); link = re.search(r'href="(/job/[^"]+/(\d+))"', c)
            if not m or not link: continue
            jid = link.group(2)
            title = txt((re.search(r'data-id="job-card-title"[^>]*>(.*?)</a>', c, re.S) or re.search(r'<h2[^>]*>(.*?)</h2>', c, re.S) or [None, ""])[1])
            co = txt((re.search(r'data-id="company-title"[^>]*>(.*?)</a>', c, re.S) or re.search(r'<span[^>]*company[^>]*>(.*?)</span>', c, re.S) or [None, ""])[1])
            host = urllib.parse.urlsplit(base).scheme + "://" + urllib.parse.urlsplit(base).hostname
            cards.setdefault(jid, {"id": jid, "title": title, "company": co, "url": host + link.group(1), "list": base})
        if len(cards) == n0: break
print(f"cards {len(cards)} from {len(PATHS)} listings")
rows = []
for c in cards.values():
    if c["id"] in seen: W("seen before"); continue
    t, co = c["title"], c["company"]
    if not t or not co: W("unparsed card"); continue
    seen.add(c["id"])   # screened from here on (a job page that cannot be read is un-marked below and retried next run)
    if not ns["ENG"].search(t) or not ns["LEVEL"].search(t) or ns["NO"].search(t): W("title"); continue
    if ns["STAFF"].search(co): W("staffing"); continue
    ok, gw = g.allow(co, t, c["url"])   # company-level gates first; the in-run cap is checked once the job page passes
    if not ok: W("gate: " + gw.split("(")[0].strip()); continue
    h = get(c["url"])
    if not h: W("job page not read"); seen.discard(c["id"]); continue
    jp = None
    for b in re.findall(r'<script type="application/ld(?:\+|&#x2B;)json"[^>]*>(.*?)</script>', h, re.S):
        try:
            d = json.loads(b); d = d if isinstance(d, list) else d.get("@graph", [d])
            jp = next((x for x in d if isinstance(x, dict) and x.get("@type") == "JobPosting"), None) or jp
        except Exception: pass
    if not jp: W("no JobPosting data"); seen.discard(c["id"]); continue
    org = jp.get("hiringOrganization") or {}
    lr = jp.get("applicantLocationRequirements") or []; lr = lr if isinstance(lr, list) else [lr]
    jl = jp.get("jobLocation") or []; jl = jl if isinstance(jl, list) else [jl]
    locs = [x.get("name") or "" for x in lr] + [", ".join(filter(None, [(x.get("address") or {}).get(k) for k in ("addressLocality", "addressRegion", "addressCountry")])) for x in jl]
    remote = (jp.get("jobLocationType") or "") == "TELECOMMUTE"
    sal = jp.get("baseSalary") or {}; val = (sal.get("value") or {}) if isinstance(sal, dict) else {}
    pmax = val.get("maxValue") if isinstance(val, dict) else None
    if pmax and str(val.get("unitText") or "YEAR").upper() == "YEAR" and float(pmax) < 180000: W("pay below floor"); continue
    s = " / ".join(l for l in locs if l)
    if not remote and not ns["BAY"].search(s): W("location: on-site / hybrid outside the Bay Area"); continue
    if remote and ns["NONUS"].search(s) and not ns["USOK"].search(s): W("location: non-US"); continue
    if (jp.get("datePosted") or "9999") < "2026-11-28" and not os.environ.get("HARVEST_ALL"): W("screened by the old pipeline"); continue   # the old Built In lane ran hourly until 03:43Z Nov 28
    ok, gw = g.allow(org.get("name") or co, jp.get("title") or t, c["url"], extra=rows)
    if not ok: W("gate (in-run cap): " + gw.split("(")[0].strip()); continue
    rows.append({"id": c["id"], "company": org.get("name") or co, "title": jp.get("title") or t, "builtin_url": c["url"], "company_site": org.get("sameAs") or org.get("url") or "",
                 "posted": jp.get("datePosted") or "", "remote": remote, "locs": locs, "pay": f"{val.get('minValue')}-{pmax}" if pmax else "",
                 "jd": txt(jp.get("description"))[:3000]})
json.dump(sorted(seen), open(SEEN, "w"))
json.dump(rows, open(os.path.join(OUTD, f"bi_{tag}.json"), "w"), indent=0)
print(f"builtin {tag}: cards {len(cards)} | rows {len(rows)} | refused {sorted(REFUSED)} | dropped {dict(sorted(why.items(), key=lambda x: -x[1]))}")
for r in rows: print(f"  {r['posted'][:16]} | {r['company'][:26]:26} | {r['title'][:60]:60} | {'remote' if r['remote'] else ' / '.join(r['locs'])[:30]:30} | {r['pay'][:16]:16} | {r['company_site'][:40]} | {r['builtin_url']}")
