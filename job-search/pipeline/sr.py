"""sr.py <tag> [days=7] -> SmartRecruiters career sites (rebuilt 2026-11-28).

Companies: sr_companies.json ({id, company}; rows with "skip" are left out). For every company, one search per
leadership / senior word through the public postings API
  https://api.smartrecruiters.com/v1/companies/<id>/postings?q=<word>&limit=100
keeps postings released inside the window whose titles pass harvest.py's rules and gates.allow; each survivor's
details (the posting's API "ref") give the job ad (remote wording, pay) and the public posting URL. Remote US or SF
Bay Area only; stated pay maximum >= $180K. No bot submits SmartRecruiters forms, so rows are apply_myself rows
(rows.py format) in <scratchpad>/harvest/sr_<tag>.json. Sequential, 1 s apart; the first 401 / 403 / 406 / 429 / 503
pauses api.smartrecruiters.com 24 h (blocks.json)."""
import html, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import gates as g
SC = "/tmp/claude-0/-home-user-goExchange/8d20ffb7-2488-5f8f-a666-35334b9e3ba6/scratchpad"
OUTD = os.path.join(SC, "harvest"); os.makedirs(OUTD, exist_ok=True)
tag = sys.argv[1]; DAYS = float(sys.argv[2]) if len(sys.argv) > 2 else 7
CUT = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - DAYS * 86400))
WORDS = (os.environ.get("SR_WORDS") or "chief|vice president|head|director|principal|architect|staff|senior").split("|")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept": "application/json"}
BLK = os.path.join(HERE, "blocks.json"); HOST = "api.smartrecruiters.com"
try: BLOCKS = json.load(open(BLK))
except Exception: BLOCKS = {}
def save_block(key, val):
    try: cur = json.load(open(BLK))
    except Exception: cur = {}
    cur[key] = val; BLOCKS[key] = val; json.dump(cur, open(BLK, "w"), indent=1)
if time.time() < float(BLOCKS.get(HOST, {}).get("until", 0)): raise SystemExit(f"sr: {HOST} paused")
src = open(os.path.join(HERE, "harvest.py")).read(); ns = {"re": re}
for nm in ("ENG", "LEVEL", "NO", "NONUS", "USOK", "BAY", "US_CITY", "STAFF", "FRONTIER", "FIN"):
    exec(re.search(rf"^{nm} = re\.compile\(.*\)$", src, re.M).group(0), ns)
exec(src[src.index("def pay_max("):src.index("def txt(")], ns)
pay_max = ns["pay_max"]
STOP = False
def get(u):
    global STOP
    if STOP: return None
    time.sleep(1)
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40) as r: return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 406, 429, 503):
            STOP = True; save_block(HOST, {"until": time.time() + 86400, "code": e.code, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            print("  REFUSED", e.code, HOST, "- paused 24 h")
        return None
    except Exception: return None
def txt(x): return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x or ""))).strip()
REMOTE = re.compile(r"\b(fully remote|100% remote|remote[- ]first|this (role|position) is (fully )?remote|remote (within|in) the (us|united states)|work from anywhere in the (us|united states))\b", re.I)

COS = [c for c in json.load(open(os.path.join(HERE, "sr_companies.json"))) if not c.get("skip")]
keep, why, names = [], {}, {}
def W(k): why[k] = why.get(k, 0) + 1
for c in COS:
    if STOP: break
    cid = c["id"]; co = c.get("company") or cid; seen = set(); n = 0
    for w in WORDS:
        d = get(f"https://{HOST}/v1/companies/{urllib.parse.quote(cid)}/postings?q={urllib.parse.quote(w)}&limit=100")
        if d is None:
            if STOP: break
            continue
        for p in d.get("content") or []:
            pid = p.get("id"); ti = (p.get("name") or "").strip()
            if pid in seen: continue
            seen.add(pid); n += 1
            nm = ((p.get("company") or {}).get("name") or "").strip()
            if nm: names[cid] = nm; co = nm
            if (p.get("releasedDate") or "0000") < CUT: W("older than window"); continue
            if not ns["ENG"].search(ti) or not ns["LEVEL"].search(ti) or ns["NO"].search(ti): W("title"); continue
            if ns["STAFF"].search(co): W("staffing"); continue
            ok, gw = g.allow(co, ti)
            if not ok: W("gate: " + gw.split("(")[0].strip()); continue
            loc = p.get("location") or {}
            locs = loc.get("fullLocation") or ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")]))
            dd = get(p.get("ref") or f"https://{HOST}/v1/companies/{cid}/postings/{pid}") or {}
            sec = ((dd.get("jobAd") or {}).get("sections") or {})
            body = txt(" ".join((sec.get(k) or {}).get("text") or "" for k in ("companyDescription", "jobDescription", "qualifications", "additionalInformation")))
            us = (loc.get("country") or "").lower() in ("us", "usa", "united states")
            remote = bool(loc.get("remote")) or bool(REMOTE.search(body))
            if ns["BAY"].search(locs) and us: place = "SF Bay Area"
            elif remote and us: place = "remote (US)"
            else: W("location: " + ("non-US" if not us else "on-site / hybrid outside the Bay Area")); continue
            if re.search(r"deferred until (funding|we raise)|unpaid|equity[- ]only|no (base )?salary|appointment type: temporary|temporary exempt|temporary (position|appointment|role)|temp[- ]to[- ]hire|\bcontract (role|position)\b", body, re.I):
                W("unpaid / temporary / contract"); continue
            pm = pay_max(body)
            if pm and pm < 180000: W("pay below floor"); continue
            ok, gw = g.allow(co, ti, extra=keep)
            if not ok: W("gate (in-run cap): " + gw.split("(")[0].strip()); continue
            keep.append({"route": "apply_myself", "ats": "smartrecruiters", "company": co, "title": ti,
                         "url": dd.get("postingUrl") or f"https://jobs.smartrecruiters.com/{cid}/{pid}", "apply_url": dd.get("applyUrl") or "",
                         "note": f"Posted {(p.get('releasedDate') or '')[:10]}; {place} ({locs[:80]}); {('pay up to $%.0fK' % (pm / 1000)) if pm else 'pay not stated'}; SmartRecruiters."})
    print(f"{co}: {n} postings read")
if names:
    C = json.load(open(os.path.join(HERE, "sr_companies.json")))
    for x in C:
        if x["id"] in names: x["company"] = names[x["id"]]
    open(os.path.join(HERE, "sr_companies.json"), "w").write("[\n" + ",\n".join(json.dumps(x) for x in C) + "\n]\n")
json.dump(keep, open(os.path.join(OUTD, f"sr_{tag}.json"), "w"), indent=0)
print(f"sr {tag}: companies {len(COS)} | kept {len(keep)} | stopped {STOP} | dropped {dict(sorted(why.items(), key=lambda x: -x[1]))}")
for k in keep: print(f"  {k['company'][:20]:20} | {k['title'][:60]:60} | {k['note'][:90]:90} | {k['url']}")
