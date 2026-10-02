#!/usr/bin/env python3
"""Build the Ashby Run Sheet (job-search/ASHBY_RUN_SHEET.html) from the verified role lists.
usage: python3 build_runsheet.py <verified json files...>
Each input is a list in the a150 output shape; only verdict == "keep" items are used. Roles are de-duplicated by Ashby job
id, capped at 3 per company (earlier real submissions count; per_co from lead_common), grouped into categories and sorted
newest first inside each category. Contact details are never written to the page."""
import json, re, sys, os, time, glob, collections, subprocess
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(os.path.dirname(HERE))
SC = "/tmp/claude-0/-home-user-goExchange/8d20ffb7-2488-5f8f-a666-35334b9e3ba6/scratchpad"
sys.path.insert(0, f"{SC}/lead"); import lead_common as L
ACTIVE_CHECK = True   # confirm each Ashby role is still open on the live board before listing it
_board_cache = {}
def _board_open_ids(slug):
    if slug in _board_cache: return _board_cache[slug]
    import urllib.request
    ids = set()
    try:
        with urllib.request.urlopen(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true", timeout=20) as r:
            d = json.loads(r.read())
        for j in d.get("jobs", []):
            u = j.get("jobUrl") or ""
            m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", u)
            if m: ids.add(m.group(1).lower())
            if j.get("id"): ids.add(str(j["id"]).lower())
    except Exception:
        _board_cache[slug] = None; return None   # board fetch failed: do not drop on a network error
    _board_cache[slug] = ids; return ids
def _is_active(company, jid):
    ids = _board_open_ids(company)
    if ids is None: return True   # could not check: keep (don't drop good roles on a transient error)
    return jid in ids
BRANCH = "claude/ai-founding-engineer-jobs-l1urgc"
try: SHA = subprocess.check_output(["git", "-C", REPO, "rev-parse", "HEAD"], text=True).strip()
except Exception: SHA = BRANCH
DROP = {}   # office-day drops retired (applicant 2026-10-02: hybrid/onsite fine unless strict/enforced wording)
DROP_RX = [(re.compile(r"^nvidia$", re.I), re.compile(r".", re.I), "NVIDIA: already 14 active applications on the applicant's account")]
NAMES = {"kraken.com": "Kraken", "ava-labs": "Ava Labs", "hims-and-hers": "Hims & Hers", "openloophealth": "OpenLoop Health", "council-capital": "Council Capital",
         "thyme-care": "Thyme Care", "wispr-flow": "Wispr Flow", "redpanda-data": "Redpanda", "montecarlodata": "Monte Carlo", "rivianvw.tech": "Rivian and VW Tech",
         "goteleport": "Teleport", "dailypay": "DailyPay", "paxoslabs": "Paxos Labs", "wealth-com": "Wealth.com", "d-matrix": "d-Matrix", "openai": "OpenAI",
         "siftstack": "SiftStack", "1password": "1Password", "netboxlabs": "NetBox Labs", "givebutter": "Givebutter", "gamechanger": "GameChanger"}
_A = open(os.path.join(REPO, "job-search", "tools", "apply.py")).read(); _G = {"re": re}
exec(_A[_A.index("NEVER_APPLY="):_A.index(chr(10), _A.index("NEVER_APPLY="))], _G)
NEVER = _G["NEVER_APPLY"]
jid = lambda u: (re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", u or "") or [None, None])[1]
def pretty(slug):
    s = (slug or "").strip()
    if s.lower() in NAMES: return NAMES[s.lower()]
    if s.isupper() and len(s) > 4: s = s.title()
    return s if re.search(r"[A-Z]", s) else re.sub(r"[-_.]+", " ", s).title()
def mode_label(it):
    m = (it.get("mode") or "").lower(); ev = it.get("mode_ev") or ""
    if m == "remote": return "Remote (US)"
    if m == "remote_option": return "Remote option"
    days = re.search(r"\b(one|two|1|2)\s*(\(\d\)\s*)?days?", ev, re.I)
    if m == "hybrid_le2": return "Hybrid · " + (days.group(0).lower() if days else "2 days or fewer")
    return "Hybrid · days not stated"
# earlier real submissions per company (titles), for "have you applied before?"
prior = collections.defaultdict(list)
for f in glob.glob(f"{SC}/f/out/*_report.json"):
    try: r = json.load(open(f))
    except Exception: continue
    if not r.get("submitted") or re.search(r"NOT SUBMITTED|ALREADY|UNCERTAIN", r.get("result") or ""): continue
    m = re.search(r"jobs\.ashbyhq\.com/([^/]+)", r.get("url") or "")
    if m: prior[m.group(1).lower()].append(re.sub(r"_", " ", r.get("tag", ""))[:60])
items, seen = [], set()
for f in sys.argv[1:]:
    for x in json.load(open(f)):
        if x.get("verdict") != "keep": continue
        j = (jid(x.get("url")) or "").lower()
        if not j or j in seen: continue
        if NEVER.search((x.get("company") or "") + " " + (x.get("title") or "") + " " + (x.get("url") or "")): continue
        if ACTIVE_CHECK and not _is_active(x.get("company"), j): continue
        if j in DROP or any(a.search(x.get("company", "")) and b.search(x.get("title", "")) for a, b, _ in DROP_RX): continue
        seen.add(j); items.append(x)
# at most ONE per company, counting real submissions (applicant rule 2026-10-01)
items.sort(key=lambda x: (x.get("tier", 3), -(x.get("dom") or 0), -(x.get("fit") or 0), -(x.get("posted_ts") or 0)))
per, kept = collections.Counter(), []
for x in items:
    k = re.sub(r"[^a-z0-9]", "", x["company"].lower().replace(".com", ""))
    if L.per_co.get(k, 0) + per[k] >= 1: continue   # applicant (2026-10-02): one application per company per rolling week
    per[k] += 1; kept.append(x)
NOW = time.time()
def row(x):
    u = re.sub(r"/application/?$", "", (x.get("url") or "").split("?")[0]).rstrip("/")
    ts = x.get("posted_ts") or 0
    flag = ""
    if re.search(r"caution|likely 3-day|borderline", (x.get("fit_why") or "") + " " + (x.get("notes") or ""), re.I): flag = "Check office days before submitting"
    return {"id": jid(u), "u": u, "t": x.get("title", ""), "c": pretty(x.get("company")), "loc": (x.get("loc") or "")[:70], "mode": mode_label(x),
            "comp": (x.get("comp") or "")[:40], "ts": int(ts) if ts else None, "fit": x.get("fit"), "p": prior.get(x["company"].lower(), [])[:3], "flag": flag,
            "tier": x.get("tier", 3), "dom": x.get("dom") or 0}
rows = [row(x) for x in kept]
fresh = [r for r in rows if r["ts"] and NOW - r["ts"] <= 7 * 86400]
older = [r for r in rows if not (r["ts"] and NOW - r["ts"] <= 7 * 86400)]
GROUPS = [("Leadership · Fintech & Crypto", lambda r: r["tier"] == 1 and r["dom"] >= 2), ("Leadership · AI & Platform", lambda r: r["tier"] == 1),
          ("Staff & Principal · Payments, Trading & Crypto", lambda r: r["tier"] == 2 and r["dom"] >= 2), ("Staff & Principal · AI Infrastructure", lambda r: r["tier"] == 2 and r["dom"] == 1),
          ("Staff & Principal · Platform & Data", lambda r: r["tier"] == 2), ("Startups · Fintech & Crypto", lambda r: r["dom"] >= 2), ("Startups · AI & Platform", lambda r: True)]
cats, used = [], set()
for name, fn in GROUPS:
    g = sorted([r for r in fresh if r["id"] not in used and fn(r)], key=lambda r: -(r["ts"] or 0))
    for r in g: used.add(r["id"])
    parts = [g[i:i + 16] for i in range(0, len(g), 16)] or []
    for pi, p in enumerate(parts): cats.append({"name": name + (f" · part {pi + 1}" if len(parts) > 1 else ""), "items": p})
if older:
    o = sorted(older, key=lambda r: (r["tier"], -(r["dom"]), -(r["ts"] or 0)))
    parts = [o[i:i + 16] for i in range(0, len(o), 16)]
    for pi, p in enumerate(parts): cats.append({"name": "Still open · posted 8 to 14 days ago" + (f" · part {pi + 1}" if len(parts) > 1 else ""), "items": p})
for c in cats:
    for r in c["items"]: r.pop("tier", None); r.pop("dom", None)
# loader is commit-pinned: jsDelivr serves a SHA fresh, while branch refs can cache up to 12h
data = {"cats": cats, "built": time.strftime("%b %d, %H:%M UTC", time.gmtime()),
        "userscript": f"https://raw.githubusercontent.com/krishamb/goExchange/{BRANCH}/job-search/ashby_fill/ashby_fill.user.js",
        "loader": f"https://cdn.jsdelivr.net/gh/krishamb/goExchange@{SHA}/job-search/ashby_fill/ashby_fill.js"}
html = open(os.path.join(HERE, "runsheet_template.html")).read().replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
out = os.path.join(REPO, "job-search", "ASHBY_RUN_SHEET.html"); open(out, "w").write(html)
json.dump([r for c in cats for r in c["items"]], open(os.path.join(REPO, "job-search", "batches", "ashby_run_sheet.json"), "w"), indent=1)
print(f"{len(rows)} roles ({len(fresh)} within 7 days, {len(older)} older) in {len(cats)} categories -> {out}")
for c in cats: print(f"  {len(c['items']):3}  {c['name']}")
