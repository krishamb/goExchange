"""oracle.py <tag> [days=7] -> Oracle Recruiting Cloud career sites (rebuilt 2026-11-28).

For every tenant in orc_tenants.json (host, siteNumber, company, fin; rows with "skip" are left out) this runs one
keyword search per leadership / senior word, newest first, through the public Candidate Experience REST API:
  https://<host>/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations
      &finder=findReqs;siteNumber=<site>,limit=50,keyword=<word>,sortBy=POSTING_DATES_DESC
Requisitions posted inside the window pass harvest.py's title rules and gates.allow; each survivor's details
(recruitingCEJobRequisitionDetails) then decide location (workplace type, work location, secondary locations and the
text: remote US or SF Bay Area only, financial institutions included) and pay (stated maximum >= $180K). Rows are
bot_hold rows for the Oracle bot (rows.py format) in <scratchpad>/harvest/orc_<tag>.json. The employer publish date is
the window (bot lane: no old-pipeline cutoff, the Gmail ledger drops roles already applied to). Sequential, 1 s apart;
the first 401 / 403 / 406 / 429 / 503 pauses that host 24 h (blocks.json)."""
import datetime, html, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import gates as g
SC = "/tmp/claude-0/-home-user-goExchange/8d20ffb7-2488-5f8f-a666-35334b9e3ba6/scratchpad"
OUTD = os.path.join(SC, "harvest"); os.makedirs(OUTD, exist_ok=True)
tag = sys.argv[1]; DAYS = float(sys.argv[2]) if len(sys.argv) > 2 else 7
CUT = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=DAYS)).strftime("%Y-%m-%d")
WORDS = (os.environ.get("ORC_WORDS") or "director,president,head,chief,principal,architect,staff,distinguished,lead,senior").split(",")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept": "application/json"}
BLK = os.path.join(HERE, "blocks.json")
try: BLOCKS = json.load(open(BLK))
except Exception: BLOCKS = {}
def save_block(key, val):
    try: cur = json.load(open(BLK))
    except Exception: cur = {}
    cur[key] = val; BLOCKS[key] = val; json.dump(cur, open(BLK, "w"), indent=1)
src = open(os.path.join(HERE, "harvest.py")).read(); ns = {"re": re}
for nm in ("ENG", "LEVEL", "NO", "NONUS", "USOK", "BAY", "US_CITY", "STAFF", "FRONTIER", "FIN"):
    exec(re.search(rf"^{nm} = re\.compile\(.*\)$", src, re.M).group(0), ns)
exec(src[src.index("def pay_max("):src.index("def txt(")], ns)
pay_max = ns["pay_max"]
REFUSED = set()
def get(u):
    h = urllib.parse.urlsplit(u).hostname
    if h in REFUSED or time.time() < float(BLOCKS.get(h, {}).get("until", 0)): return None
    time.sleep(1)
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40) as r: return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 406, 429, 503):
            REFUSED.add(h); save_block(h, {"until": time.time() + 86400, "code": e.code, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            print("  REFUSED", e.code, h, "- paused 24 h")
        return None
    except Exception: return None
def txt(x): return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x or ""))).strip()

TEN = [t for t in json.load(open(os.path.join(HERE, "orc_tenants.json"))) if not t.get("skip")]
if os.environ.get("ORC_ONLY"): TEN = [t for t in TEN if t["company"] in os.environ["ORC_ONLY"].split(",")]
keep, why = [], {}
def W(k): why[k] = why.get(k, 0) + 1
for t in TEN:
    host, site, co = t["host"], t["site"], t["company"]; seen = set(); n = 0
    for w in WORDS:
        d = get(f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations"
                f"&finder=findReqs;siteNumber={site},limit=50,keyword={urllib.parse.quote(w)},sortBy=POSTING_DATES_DESC")
        if d is None:
            if host in REFUSED: break
            continue
        for it in d.get("items") or []:
            for r in it.get("requisitionList") or []:
                rid = r.get("Id"); ti = (r.get("Title") or "").strip()
                if rid in seen: continue
                seen.add(rid); n += 1
                if (r.get("PostedDate") or "0000") < CUT: W("older than window"); continue
                if not ns["ENG"].search(ti) or not ns["LEVEL"].search(ti) or ns["NO"].search(ti): W("title"); continue
                ok, gw = g.allow(co, ti)   # company-level gates first (cheap); the in-run cap is checked once the row passes location and pay
                if not ok: W("gate: " + gw.split("(")[0].strip()); continue
                dd = get(f'https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails?expand=all&onlyData=true&finder=ById;Id="{rid}",siteNumber={site}')
                x = ((dd or {}).get("items") or [{}])[0]
                body = txt(" ".join(str(x.get(k) or "") for k in ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr", "CorporateDescriptionStr")))
                wl = " / ".join(", ".join(filter(None, [l.get("TownOrCity"), l.get("Region2"), l.get("Country")])) for l in (x.get("workLocation") or []))
                sec = " / ".join(s.get("Name") or "" for s in (r.get("secondaryLocations") or []))
                locs = " / ".join(filter(None, [r.get("PrimaryLocation") or "", sec, wl]))
                wt = (r.get("WorkplaceTypeCode") or x.get("WorkplaceTypeCode") or r.get("WorkplaceType") or "").upper()
                remote = "REMOTE" in wt or bool(re.search(r"\b(fully remote|remote[- ]first|this (role|position) (is|can be) (fully )?remote|remote within the (us|united states))\b", body, re.I))
                us = (r.get("PrimaryLocationCountry") or "") == "US" or bool(ns["USOK"].search(locs))
                if ns["BAY"].search(locs) and not ("HYBRID" in wt and not ns["BAY"].search(r.get("PrimaryLocation") or "")): place = "SF Bay Area"
                elif remote and us: place = "remote (US)"
                else: W("location: " + ("non-US" if not us else "on-site / hybrid outside the Bay Area")); continue
                pm = pay_max(body)
                if pm and pm < 180000: W("pay below floor"); continue
                ok, gw = g.allow(co, ti, extra=keep)
                if not ok: W("gate (in-run cap): " + gw.split("(")[0].strip()); continue
                keep.append({"route": "bot_hold", "ats": "oracle", "company": co, "title": ti,
                             "url": f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{rid}", "apply_url": "",
                             "note": f"Posted {r.get('PostedDate')}; {place} ({locs[:90]}); {('pay up to $%.0fK' % (pm / 1000)) if pm else 'pay not stated'}; Oracle Recruiting Cloud (bot)."})
    print(f"{co}: {n} requisitions read")
json.dump(keep, open(os.path.join(OUTD, f"orc_{tag}.json"), "w"), indent=0)
print(f"oracle {tag}: tenants {len(TEN)} | kept {len(keep)} | refused {sorted(REFUSED)} | dropped {dict(sorted(why.items(), key=lambda x: -x[1]))}")
for k in keep: print(f"  {k['company'][:16]:16} | {k['title'][:62]:62} | {k['note'][:90]:90} | {k['url']}")
