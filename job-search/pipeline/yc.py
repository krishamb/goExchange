"""yc.py <tag> [days=7] -> YC startup jobs from the public ycombinator.com/jobs pages (rebuilt 2026-11-28).

Public listing pages only (never signed in; Work at a Startup applications need the applicant's own YC sign-in, so
those rows go to the Apply Myself file with the public job link). Each page embeds its postings as JSON (data-page):
title, location, salary range, company, relative creation time ("3 days", "about 1 year"). Postings created inside
the window pass harvest.py's title / location rules, the pay floor and gates.allow. A company whose Greenhouse / Ashby /
Lever board is in boards.json is routed to that lane (the hourly harvest screens its own posting; the row says so);
the rest are apply_myself rows. Rows -> <scratchpad>/harvest/yc_<tag>.json. 2 s apart; the first 401 / 403 / 406 /
429 / 503 pauses www.ycombinator.com 24 h (blocks.json)."""
import html, json, os, re, sys, time, urllib.error, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import gates as g
SC = "/tmp/claude-0/-home-user-goExchange/8d20ffb7-2488-5f8f-a666-35334b9e3ba6/scratchpad"
OUTD = os.path.join(SC, "harvest"); os.makedirs(OUTD, exist_ok=True)
tag = sys.argv[1]; DAYS = float(sys.argv[2]) if len(sys.argv) > 2 else 7
PAGES = ["/jobs/role/software-engineer/san-francisco", "/jobs/role/software-engineer/remote", "/jobs/role/software-engineer"]
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}
BLK = os.path.join(HERE, "blocks.json"); HOST = "www.ycombinator.com"
try: BLOCKS = json.load(open(BLK))
except Exception: BLOCKS = {}
def save_block(key, val):
    try: cur = json.load(open(BLK))
    except Exception: cur = {}
    cur[key] = val; BLOCKS[key] = val; json.dump(cur, open(BLK, "w"), indent=1)
if time.time() < float(BLOCKS.get(HOST, {}).get("until", 0)): raise SystemExit(f"yc: {HOST} paused")
src = open(os.path.join(HERE, "harvest.py")).read(); ns = {"re": re}
for nm in ("ENG", "LEVEL", "NO", "NONUS", "USOK", "BAY", "US_CITY", "STAFF", "FRONTIER", "FIN"):
    exec(re.search(rf"^{nm} = re\.compile\(.*\)$", src, re.M).group(0), ns)
exec(src[src.index("def loc_ok("):src.index("STAFF = re.compile(")], ns)
exec(src[src.index("def pay_max("):src.index("def txt(")], ns)
loc_ok, pay_max = ns["loc_ok"], ns["pay_max"]
def age_days(s):
    s = (s or "").lower()
    if re.search(r"minute|hour|second|just now", s): return 0
    m = re.search(r"(\d+|a|an|about a|one)\s*(day|week|month|year)", s.replace("about ", ""))
    if not m: return 999
    n = 1 if m.group(1) in ("a", "an", "about a", "one") else int(m.group(1))
    return n * {"day": 1, "week": 7, "month": 30, "year": 365}[m.group(2)]

B = json.load(open(os.path.join(HERE, "boards.json"))); idx = {a: {g.norm(s): s for s in v} for a, v in B.items()}
posts, refused = {}, False
for p in PAGES:
    time.sleep(2)
    try:
        b = urllib.request.urlopen(urllib.request.Request("https://" + HOST + p, headers=UA), timeout=40).read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 406, 429, 503):
            save_block(HOST, {"until": time.time() + 86400, "code": e.code, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}); refused = True; print("  REFUSED", e.code); break
        continue
    except Exception: continue
    m = re.search(r'data-page="([^"]+)"', b)
    if not m: continue
    for j in (json.loads(html.unescape(m.group(1))).get("props") or {}).get("jobPostings") or []: posts.setdefault(j.get("id"), j)
keep, why = [], {}
def W(k): why[k] = why.get(k, 0) + 1
for j in posts.values():
    t, co = (j.get("title") or "").strip(), (j.get("companyName") or "").strip()
    if age_days(j.get("createdAt")) > DAYS: W("older than window"); continue
    if (j.get("type") or "Full-time") != "Full-time": W("not full-time"); continue
    if not ns["ENG"].search(t) or not ns["LEVEL"].search(t) or ns["NO"].search(t): W("title"); continue
    loc = j.get("location") or ""
    ok, lw = loc_ok([loc], bool(re.search(r"remote", loc, re.I)), "")
    if not ok: W("location: " + lw); continue
    pm = pay_max(j.get("salaryRange") or "")
    if pm and pm < 180000: W("pay below floor"); continue
    okg, gw = g.allow(co, t, extra=keep)
    if not okg: W("gate: " + gw.split("(")[0].strip()); continue
    ats = next((a for a in ("ashby", "lever", "greenhouse") if idx.get(a, {}).get(g.norm(co)) or idx.get(a, {}).get(g.key(co))), "")
    url = "https://www.ycombinator.com" + (j.get("url") or "")
    keep.append({"route": "apply_myself" if not ats else {"ashby": "one_click", "lever": "one_click", "greenhouse": "bot_hold"}[ats], "ats": ats or "yc",
                 "company": co, "title": t, "url": url, "apply_url": "",
                 "note": f"YC {j.get('companyBatchName') or ''} ({j.get('companyOneLiner') or ''}); created {j.get('createdAt')} ago; {loc} ({lw}); {j.get('salaryRange') or 'pay not stated'}"
                         + (f"; also on its {ats} board: apply there" if ats else "; apply with your YC account")})
json.dump(keep, open(os.path.join(OUTD, f"yc_{tag}.json"), "w"), indent=0)
print(f"yc {tag}: postings {len(posts)} | kept {len(keep)} | refused {refused} | dropped {dict(sorted(why.items(), key=lambda x: -x[1]))}")
for k in keep: print(f"  {k['route']:12} | {k['company'][:22]:22} | {k['title'][:56]:56} | {k['note'][:110]}")
