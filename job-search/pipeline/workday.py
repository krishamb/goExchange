"""workday.py <tag> [days=7] -> Workday career sites (rebuilt 2026-11-28).

Tenants: wd_tenants.json ({url, tenant, site, company}; rows with "skip" are left out; WD_ONLY=<tenant,...> limits the
run). For every tenant, one search per leadership / senior phrase through the public career-site JSON
  POST https://<tenant>.<wdN>.myworkdayjobs.com/wday/cxs/<tenant>/<site>/jobs  {"searchText": w, "limit": 20, "offset": 0, "appliedFacets": {}}
keeps postings whose "Posted ..." age is inside the window and whose titles pass harvest.py's rules and gates.allow;
each survivor's details (GET .../wday/cxs/<tenant>/<site><externalPath>) then give the start date (the employer publish
date governs), the locations, the remote type and the description (remote wording, pay). Remote US or SF Bay Area
only; stated pay maximum >= $180K. Rows are bot_hold rows for the Workday bot (rows.py format) in
<scratchpad>/harvest/wd_<tag>.json. Leadership phrases run first, so the 3-role cap keeps the senior-most roles.
Sequential, 1.3 s apart. The 'myworkdayjobs.com' key in blocks.json pauses every tenant; the first 401 / 403 / 406 /
429 / 503 from any tenant pauses them all for 24 h (Workday tenants share one edge). WD_DAYS overrides the window
(WD_DAYS=1 for same-day re-sweeps)."""
import html, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import gates as g
SC = "/tmp/claude-0/-home-user-goExchange/8d20ffb7-2488-5f8f-a666-35334b9e3ba6/scratchpad"
OUTD = os.path.join(SC, "harvest"); os.makedirs(OUTD, exist_ok=True)
tag = sys.argv[1]; DAYS = float(os.environ.get("WD_DAYS") or (sys.argv[2] if len(sys.argv) > 2 else 7))
NOW = time.time(); CUT_DATE = time.strftime("%Y-%m-%d", time.gmtime(NOW - DAYS * 86400))
WORDS = (os.environ.get("WD_WORDS") or "chief|vice president|head of|director|principal|distinguished|architect|staff").split("|")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "application/json", "Content-Type": "application/json", "Accept-Language": "en-US"}
BLK = os.path.join(HERE, "blocks.json"); FAMILY = "myworkdayjobs.com"
try: BLOCKS = json.load(open(BLK))
except Exception: BLOCKS = {}
def save_block(key, val):
    try: cur = json.load(open(BLK))
    except Exception: cur = {}
    cur[key] = val; BLOCKS[key] = val; json.dump(cur, open(BLK, "w"), indent=1)
if NOW < float(BLOCKS.get(FAMILY, {}).get("until", 0)):
    raise SystemExit(f"workday: all tenants paused until {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(float(BLOCKS[FAMILY]['until'])))}")
src = open(os.path.join(HERE, "harvest.py")).read(); ns = {"re": re}
for nm in ("ENG", "LEVEL", "NO", "NONUS", "USOK", "BAY", "US_CITY", "STAFF", "FRONTIER", "FIN"):
    exec(re.search(rf"^{nm} = re\.compile\(.*\)$", src, re.M).group(0), ns)
exec(src[src.index("def pay_max("):src.index("def txt(")], ns)
pay_max = ns["pay_max"]
STOP = False
def req(u, body=None):
    global STOP
    if STOP: return None
    time.sleep(1.3)
    try:
        r = urllib.request.Request(u, data=json.dumps(body).encode() if body is not None else None, headers=UA, method="POST" if body is not None else "GET")
        with urllib.request.urlopen(r, timeout=40) as f: return json.loads(f.read())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 406, 429, 503):
            STOP = True; save_block(FAMILY, {"until": time.time() + 86400, "code": e.code, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "host": urllib.parse.urlsplit(u).hostname})
            print("  REFUSED", e.code, urllib.parse.urlsplit(u).hostname, "- every Workday tenant paused 24 h")
        return None
    except Exception: return None
def txt(x): return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x or ""))).strip()
def age_days(s):
    s = (s or "").lower()
    if "today" in s: return 0
    if "yesterday" in s: return 1
    m = re.search(r"(\d+)\+?\s*days?", s)
    return int(m.group(1)) + (1 if "+" in s else 0) if m else 99
REMOTE = re.compile(r"\b(remote|virtual|telecommut\w*|work from home|wfh|anywhere in the (us|united states))\b", re.I)
NOT_REMOTE = re.compile(r"\b(not (a )?remote|no remote|non-remote|hybrid|on-?site|in[- ]office|in the office \d|\d days (a|per) week in)\b", re.I)

TEN = [t for t in json.load(open(os.path.join(HERE, "wd_tenants.json"))) if not t.get("skip")]
if os.environ.get("WD_ONLY"): TEN = [t for t in TEN if t["tenant"] in os.environ["WD_ONLY"].split(",")]
keep, why, names = [], {}, {}
def W(k): why[k] = why.get(k, 0) + 1
for t in TEN:
    if STOP: break
    p = urllib.parse.urlsplit(t["url"]); host = p.netloc; site = t["site"]; co = t.get("company") or t["tenant"]
    api = f"https://{host}/wday/cxs/{t['tenant']}/{site}"; seen = set(); n = 0
    ok0, w0 = g.allow(co, "")   # company-level gates (never-apply, interviewing, rejected, cap reached): skip the whole tenant
    if not ok0: W("gate (company): " + w0.split("(")[0].strip()); print(f"{co}: skipped ({w0})"); continue
    for w in WORDS:
        d = req(api + "/jobs", {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": w})
        if d is None:
            if STOP: break
            continue
        for j in d.get("jobPostings") or []:
            path = j.get("externalPath") or ""; ti = (j.get("title") or "").strip()
            if not path or path in seen: continue
            seen.add(path); n += 1
            if age_days(j.get("postedOn")) > DAYS: W("older than window"); continue
            if not ns["ENG"].search(ti) or not ns["LEVEL"].search(ti) or ns["NO"].search(ti): W("title"); continue
            ok, gw = g.allow(co, ti)
            if not ok: W("gate: " + gw.split("(")[0].strip()); continue
            dd = req(api + path)
            if not dd: W("details not read"); continue
            x = dd.get("jobPostingInfo") or {}
            org = ((dd.get("hiringOrganization") or {}).get("name") or "").strip()
            if org: names[t["tenant"]] = org
            start = x.get("startDate") or ""
            if start and start < CUT_DATE: W("employer start date older than window"); continue
            body = txt(x.get("jobDescription"))
            locs = " / ".join(filter(None, [x.get("location") or "", " / ".join(x.get("additionalLocations") or []), j.get("locationsText") or ""]))
            rt = (x.get("remoteType") or "").strip()
            remote = bool(re.search(r"remote|virtual|telecommut", rt, re.I)) or bool(REMOTE.search(locs)) or (bool(REMOTE.search(body[:3000])) and not NOT_REMOTE.search(rt + " " + body[:3000]))
            us = bool(ns["USOK"].search(locs) or ns["US_CITY"].search(locs) or re.search(r"\b(US|USA)\b", locs)) and not (ns["NONUS"].search(locs) and not ns["USOK"].search(locs))
            if ns["BAY"].search(locs) and not (ns["NONUS"].search(locs) and not re.search(r"\bca\b|california|bay area", locs, re.I)): place = "SF Bay Area"
            elif remote and (us or not ns["NONUS"].search(locs)): place = "remote (US)"
            else: W("location: " + ("non-US" if ns["NONUS"].search(locs) and not us else "on-site / hybrid outside the Bay Area")); continue
            pm = pay_max(body)
            if pm and pm < 180000: W("pay below floor"); continue
            if re.search(r"\b(active (secret|ts|top secret)|security clearance (is )?required|ts/sci|polygraph)\b", body, re.I): W("clearance"); continue
            ok, gw = g.allow(co, ti, extra=keep)
            if not ok: W("gate (in-run cap): " + gw.split("(")[0].strip()); continue
            keep.append({"route": "bot_hold", "ats": "workday", "company": co, "title": ti, "url": x.get("externalUrl") or f"https://{host}/{site}{path}", "apply_url": "",
                         "note": f"Posted {start or j.get('postedOn')}; {place} ({locs[:90]}); {('pay up to $%.0fK' % (pm / 1000)) if pm else 'pay not stated'}; Workday (bot)."})
    print(f"{co}: {n} postings read")
if names:   # keep the tenant names the sites report, so the gates match the ledger's company names next time
    T = json.load(open(os.path.join(HERE, "wd_tenants.json")))
    for x in T:
        if x["tenant"] in names and not x.get("company_checked"): x["company_site_name"] = names[x["tenant"]]
    open(os.path.join(HERE, "wd_tenants.json"), "w").write("[\n" + ",\n".join(json.dumps(x) for x in T) + "\n]\n")
json.dump(keep, open(os.path.join(OUTD, f"wd_{tag}.json"), "w"), indent=0)
print(f"workday {tag}: tenants {len(TEN)} | kept {len(keep)} | stopped {STOP} | dropped {dict(sorted(why.items(), key=lambda x: -x[1]))}")
for k in keep: print(f"  {k['company'][:18]:18} | {k['title'][:60]:60} | {k['note'][:90]:90} | {k['url']}")
