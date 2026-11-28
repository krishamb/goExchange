"""feeds.py <tag> [days=7] -> remote job feeds (rebuilt 2026-11-28): RemoteOK API, We Work Remotely RSS, Remotive API,
Jobicy API and Working Nomads API.

Each feed's rows pass harvest.py's title / location / pay rules and gates.allow; survivors get their employer apply link
(RemoteOK: one redirect hop read from the Location header, never auto-followed; the others: the apply link on the feed's
job page). Greenhouse / Lever / Ashby links are checked on the employer ATS (still open, publish date inside the window:
the employer date governs, a feed repost does not reset it). Route: Ashby / Lever -> one_click; Greenhouse, Workday,
Oracle, Jobvite -> bot_hold (the bot lanes); everything else -> apply_myself. Rows (rows.py format) go to
<scratchpad>/harvest/feeds_<tag>.json for review, then `rows.py add`. New Greenhouse / Ashby / Lever board tokens are added
to boards.json. Sequential, 1.5 s apart; the first 401 / 403 / 406 / 429 / 503 pauses that host 24 h (blocks.json);
Remotive at most every 6 h and Jobicy every 3 h (their APIs ask for a few calls a day). Links onto indeed.com,
theladders.com, a16z / Consider or LinkedIn are never fetched."""
import datetime, email.utils, html, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import gates as g
SC = "/tmp/claude-0/-home-user-goExchange/8d20ffb7-2488-5f8f-a666-35334b9e3ba6/scratchpad"
OUTD = os.path.join(SC, "harvest"); os.makedirs(OUTD, exist_ok=True)
tag = sys.argv[1]; DAYS = float(sys.argv[2]) if len(sys.argv) > 2 else 7
NOW = time.time(); CUT = NOW - DAYS * 86400
OLD_FEEDS = datetime.datetime(2026, 11, 28, 3, 40, tzinfo=datetime.timezone.utc).timestamp()   # the old feed lane ran hourly until the reset
SRC = (os.environ.get("FEEDS") or "remoteok,wwr,remotive,jobicy,workingnomads").split(",")
MIN_GAP = {"remotive.com": 6 * 3600, "jobicy.com": 3 * 3600}
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}
FORBID = re.compile(r"(^|\.)(indeed\.com|theladders\.com|a16z\.com|consider\.com|consider\.co|linkedin\.com)$", re.I)
BLK = os.path.join(HERE, "blocks.json")
try: BLOCKS = json.load(open(BLK))
except Exception: BLOCKS = {}
src = open(os.path.join(HERE, "harvest.py")).read(); ns = {"re": re}
for nm in ("ENG", "LEVEL", "NO", "NONUS", "USOK", "BAY", "US_CITY", "STAFF", "FRONTIER", "FIN"):
    exec(re.search(rf"^{nm} = re\.compile\(.*\)$", src, re.M).group(0), ns)
exec(src[src.index("def loc_ok("):src.index("STAFF = re.compile(")], ns)
exec(src[src.index("def pay_max("):src.index("def txt(")], ns)
loc_ok, pay_max = ns["loc_ok"], ns["pay_max"]
REFUSED = set()
def saveb(): json.dump(BLOCKS, open(BLK, "w"), indent=1)

class _NoRedir(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
_noredir = urllib.request.build_opener(_NoRedir)
def get(u, follow=True):
    h = (urllib.parse.urlsplit(u).hostname or "").lower(); base = re.sub(r"^www\.", "", h)
    if not h or FORBID.search(h) or h in REFUSED or time.time() < float(BLOCKS.get(h, {}).get("until", 0)): return None, "skipped"
    if base in MIN_GAP and "/api/" in urllib.parse.urlsplit(u).path:   # the call limits are for the APIs, not the job pages
        if time.time() - float(BLOCKS.get(base + "_last", {}).get("at_ts", 0)) < MIN_GAP[base]: return None, "too soon"
        BLOCKS[base + "_last"] = {"at_ts": time.time()}; saveb()
    time.sleep(1.5)
    try:
        r = (urllib.request.urlopen if follow else _noredir.open)(urllib.request.Request(u, headers=UA), timeout=40)
        if follow and FORBID.search(urllib.parse.urlsplit(r.geturl()).hostname or ""): return None, "redirected to a forbidden host"
        return r.read().decode("utf-8", "replace"), 200
    except urllib.error.HTTPError as e:
        if not follow and e.code in (301, 302, 303, 307, 308): return urllib.parse.urljoin(u, e.headers.get("Location") or ""), e.code
        if e.code in (401, 403, 406, 429, 503):
            REFUSED.add(h); BLOCKS[h] = {"until": time.time() + 86400, "code": e.code, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}; saveb()
            print("  REFUSED", e.code, h, "- paused 24 h")
        return None, e.code
    except Exception as e: return None, type(e).__name__
def txt(x): return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x or ""))).strip()
def pts(s):
    if not s: return 0
    if isinstance(s, (int, float)): return float(s) / (1000 if s > 1e12 else 1)
    s = str(s).strip()
    try: return email.utils.parsedate_to_datetime(s).timestamp()
    except Exception: pass
    try:
        d = datetime.datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T"))
        return (d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)).timestamp()
    except Exception: return 0
def tagv(it, t):
    m = re.search(rf"<{t}>(.*?)</{t}>", it, re.S)
    return html.unescape(re.sub(r"^<!\[CDATA\[|\]\]>$", "", m.group(1).strip())) if m else ""

def feed_rows(s):
    if s == "remoteok":
        b, c = get("https://remoteok.com/api")
        for j in (json.loads(b)[1:] if b else []):
            yield {"src": s, "company": j.get("company"), "title": j.get("position"), "page": j.get("url"), "apply": j.get("apply_url"), "ts": pts(j.get("epoch")),
                   "locs": [j.get("location") or ""], "pay": float(j.get("salary_max") or 0) or None, "desc": j.get("description")}
    elif s == "wwr":
        b, c = get("https://weworkremotely.com/remote-jobs.rss")
        for it in re.findall(r"<item>(.*?)</item>", b or "", re.S):
            co, _, t = tagv(it, "title").partition(": ")
            yield {"src": s, "company": co, "title": t, "page": tagv(it, "link"), "apply": "", "ts": pts(tagv(it, "pubDate")),
                   "locs": [tagv(it, "region"), tagv(it, "country")], "pay": None, "desc": tagv(it, "description")}
    elif s == "remotive":
        b, c = get("https://remotive.com/api/remote-jobs")
        for j in (json.loads(b).get("jobs", []) if b else []):
            yield {"src": s, "company": j.get("company_name"), "title": j.get("title"), "page": j.get("url"), "apply": "", "ts": pts(j.get("publication_date")),
                   "locs": [j.get("candidate_required_location") or ""], "pay": pay_max(j.get("salary") or ""), "desc": j.get("description")}
    elif s == "jobicy":
        b, c = get("https://jobicy.com/api/v2/remote-jobs?count=100&geo=usa")
        for j in (json.loads(b).get("jobs", []) if b else []):
            mx = j.get("annualSalaryMax") if (j.get("salaryCurrency") or "USD") == "USD" else None
            yield {"src": s, "company": j.get("companyName"), "title": html.unescape(j.get("jobTitle") or ""), "page": j.get("url"), "apply": "", "ts": pts(j.get("pubDate")),
                   "locs": [j.get("jobGeo") or ""], "pay": float(mx) if mx else None, "desc": j.get("jobDescription")}
    elif s == "workingnomads":
        b, c = get("https://www.workingnomads.com/api/exposed_jobs/")
        for j in (json.loads(b) if b else []):
            yield {"src": s, "company": j.get("company_name"), "title": j.get("title"), "page": j.get("url"), "apply": "", "ts": pts(j.get("pub_date")),
                   "locs": [j.get("location") or ""], "pay": None, "desc": j.get("description")}
    if s in ("remoteok", "wwr", "remotive", "jobicy", "workingnomads"): print(f"{s}: read")

ATSRX = re.compile(r"https?://[^\s\"'<>]*(greenhouse\.io|ashbyhq\.com|lever\.co|myworkdayjobs\.com|oraclecloud\.com|jobvite\.com|smartrecruiters\.com|workable\.com|bamboohr\.com|rippling|recruitee\.com|breezy\.hr|applytojob\.com|teamtailor\.com|personio|pinpointhq\.com|icims\.com|dover\.com|wellfound\.com)[^\s\"'<>]*", re.I)
def apply_link(r):
    if r["src"] == "remoteok" and r["apply"]:
        u = r["apply"]
        for _ in range(3):
            loc, c = get(u, follow=False)
            if c not in (301, 302, 303, 307, 308) or not loc: break
            u = loc
            if "remoteok.com" not in (urllib.parse.urlsplit(u).hostname or ""): return u
        return ""
    b, c = get(r["page"])
    if not b: return ""
    m = ATSRX.search(html.unescape(b))
    if m: return m.group(0)
    for href, text in re.findall(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', b, re.S):
        if re.search(r"apply", txt(text), re.I) and urllib.parse.urlsplit(href).hostname not in (urllib.parse.urlsplit(r["page"]).hostname,): return html.unescape(href)
    return ""

def ats_check(u):
    """(ats, published_ts or None, open?) from the employer ATS; None ts when the ATS gives no date or is not one of the three."""
    m = re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)/jobs/(\d+)", u) or re.search(r"greenhouse\.io/embed/job_app\?for=([\w-]+)&token=(\d+)", u)
    if m:
        b, c = get(f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs/{m.group(2)}")
        if c == 404: return "greenhouse", None, False
        return "greenhouse", (pts(json.loads(b).get("first_published")) if b else None), True
    m = re.search(r"jobs\.lever\.co/([\w.-]+)/([0-9a-f-]{36})", u)
    if m:
        b, c = get(f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}")
        if c == 404: return "lever", None, False
        return "lever", (pts(json.loads(b).get("createdAt")) if b else None), True
    m = re.search(r"jobs\.ashbyhq\.com/([\w%.-]+)/([0-9a-f-]{36})", u)
    if m:
        b, c = get(f"https://api.ashbyhq.com/posting-api/job-board/{m.group(1)}")
        if b:
            j = next((x for x in json.loads(b).get("jobs", []) if x.get("id") == m.group(2)), None)
            return "ashby", (pts(j.get("publishedAt")) if j else None), bool(j)
        return "ashby", None, True
    for k in ("myworkdayjobs", "oraclecloud", "jobvite"):
        if k in u: return {"myworkdayjobs": "workday", "oraclecloud": "oracle", "jobvite": "jobvite"}[k], None, True
    return (urllib.parse.urlsplit(u).hostname or "").replace("www.", ""), None, True

keep, why, seen = [], {}, set()
def W(k): why[k] = why.get(k, 0) + 1
for s in SRC:
    for r in feed_rows(s):
        t, co = (r["title"] or "").strip(), (r["company"] or "").strip()
        k = (g.key(co), t.lower())
        if not t or not co or k in seen: continue
        seen.add(k)
        if r["ts"] < CUT: W("older than window"); continue
        if r["ts"] < OLD_FEEDS and not os.environ.get("HARVEST_ALL"): W("screened by the old pipeline"); continue
        if not ns["ENG"].search(t) or not ns["LEVEL"].search(t) or ns["NO"].search(t): W("title"); continue
        if ns["STAFF"].search(co): W("staffing"); continue
        if ns["FRONTIER"].search(co) and not ns["FIN"].search(t): W("frontier lab: finance roles only"); continue
        ok, lw = loc_ok(r["locs"], True, "Remote")
        if not ok: W("location: " + lw); continue
        if r["pay"] and r["pay"] < 180000: W("pay below floor"); continue
        if not r["pay"] and pay_max(txt(r["desc"])) and pay_max(txt(r["desc"])) < 180000: W("pay below floor (description)"); continue
        okg, gw = g.allow(co, t, r["page"] or "")
        if not okg: W("gate: " + gw.split("(")[0].strip()); continue
        u = apply_link(r)
        if u and FORBID.search(urllib.parse.urlsplit(u).hostname or ""): u = ""   # never list or fetch links onto forbidden hosts
        ats, pub, live = ats_check(u) if u else ("", None, True)
        if not live: W("closed on the employer ATS"); continue
        if pub and pub < CUT: W("employer publish date older than window"); continue
        route = "one_click" if ats in ("ashby", "lever") else "bot_hold" if ats in ("greenhouse", "workday", "oracle", "jobvite") else "apply_myself"
        when = time.strftime("%Y-%m-%d", time.gmtime(pub or r["ts"]))
        keep.append({"route": route, "ats": ats, "company": co, "title": t, "url": u or r["page"], "apply_url": "",
                     "note": f"Posted {when} ({'employer ATS' if pub else s}); remote ({lw}); {('pay up to $%.0fK' % (r['pay'] / 1000)) if r['pay'] else 'pay not stated'}; found on {s}."
                             + ("" if u else " Apply from the feed page (no employer link found)."), "feed_page": r["page"]})
keep.sort(key=lambda x: (x["route"], x["company"].lower()))
json.dump(keep, open(os.path.join(OUTD, f"feeds_{tag}.json"), "w"), indent=0)
print(f"feeds {tag}: kept {len(keep)} | refused {sorted(REFUSED)} | dropped {dict(sorted(why.items(), key=lambda x: -x[1]))}")
for x in keep: print(f"  {x['route']:12} | {x['company'][:26]:26} | {x['title'][:58]:58} | {x['note'][:60]:60} | {x['url'][:100]}")
