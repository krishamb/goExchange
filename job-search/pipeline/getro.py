"""getro.py <tag> [hours=48] -> VC / crypto portfolio job boards built on Getro (rebuilt 2026-11-28).

Each board's search page (https://<board>/jobs?q=<word>) carries its results in __NEXT_DATA__ (initialState.jobs.found):
organization, title, the employer's own posting URL, createdAt, locations, work mode and pay. For every board and query
word this keeps the leadership / senior roles created inside the window that pass harvest.py's title / location / pay
rules and gates.allow, and it adds the employers' Greenhouse / Ashby / Lever board tokens it sees to boards.json (the
board list the hourly harvest reads). Sequential, 1.5 s apart; the first 401 / 403 / 406 / 429 / 503 from a host pauses
that host 24 h (blocks.json). Never used for the a16z (Consider) board."""
import json, os, re, sys, time, urllib.request, urllib.error, urllib.parse
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import gates as g
SC = "/tmp/claude-0/-home-user-goExchange/8d20ffb7-2488-5f8f-a666-35334b9e3ba6/scratchpad"
OUTD = os.path.join(SC, "harvest"); os.makedirs(OUTD, exist_ok=True)
tag = sys.argv[1]; HOURS = float(sys.argv[2]) if len(sys.argv) > 2 else 48
NOW = time.time(); CUT = NOW - HOURS * 3600
OLD_GETRO = 1795800480.0   # 2026-11-27T17:28Z: the old pipeline's last Getro VC / crypto run (vc1127a / crypto1127a) screened everything created before it
VC = ["jobs.generalcatalyst.com", "jobs.khoslaventures.com", "jobs.accel.com", "jobs.thrivecap.com", "jobs.luxcapital.com", "jobs.insightpartners.com",
      "jobs.menlovc.com", "careers.antler.co", "careers.bitkraft.vc", "jobs.8vc.com", "jobs.ggvc.com"]
CRYPTO = ["jobs.solana.com", "jobs.variant.fund", "jobs.multicoin.capital", "jobs.electriccapital.com", "jobs.dragonfly.xyz", "jobs.coinfund.io",
          "jobs.polychain.capital", "jobs.framework.ventures", "jobs.avax.network", "jobs.blockchaincapital.com", "jobs.dcg.co", "jobs.castleisland.vc",
          "jobs.placeholder.vc", "jobs.archetype.fund", "jobs.delphiventures.io", "jobs.nascent.xyz"]
BOARDS = [b for b in (os.environ.get("GETRO_BOARDS") or ",".join(VC + CRYPTO)).split(",") if b]
QUERIES = (os.environ.get("GETRO_QUERIES") or "CTO,VP,head,director,principal,staff,architect,manager,lead").split(",")   # single words (multi-word queries act as exact phrases)
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
BLK = os.path.join(HERE, "blocks.json")
try: BLOCKS = json.load(open(BLK))
except Exception: BLOCKS = {}
def save_block(key, val):   # merge-on-write: other sweeps may have written blocks.json since this one started
    try: cur = json.load(open(BLK))
    except Exception: cur = {}
    cur[key] = val; BLOCKS[key] = val; json.dump(cur, open(BLK, "w"), indent=1)
src = open(os.path.join(HERE, "harvest.py")).read()
ns = {"re": re}
for nm in ("ENG", "LEVEL", "NO", "NONUS", "USOK", "BAY", "US_CITY", "STAFF", "FRONTIER", "FIN"):
    exec(re.search(rf"^{nm} = re\.compile\(.*\)$", src, re.M).group(0), ns)
exec(src[src.index("def loc_ok("):src.index("STAFF = re.compile(")], ns)
exec(src[src.index("def pay_max("):src.index("def txt(")], ns)
loc_ok, pay_max = ns["loc_ok"], ns["pay_max"]

def fetch(u):
    h = urllib.parse.urlsplit(u).hostname
    if time.time() < float(BLOCKS.get(h, {}).get("until", 0)): return None, "paused"
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40) as r: return r.read().decode("utf-8", "replace"), 200
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 406, 429, 503):
            save_block(h, {"until": time.time() + 86400, "code": e.code, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        return None, e.code
    except Exception as e: return None, type(e).__name__

TOKRX = [(re.compile(r"(?:job-)?boards\.greenhouse\.io/(?:embed/job_app\?for=)?([A-Za-z0-9_-]+)"), "greenhouse"),
         (re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9%._-]+)"), "ashby"), (re.compile(r"jobs\.lever\.co/([A-Za-z0-9_.-]+)"), "lever")]
B = json.load(open(os.path.join(HERE, "boards.json"))); known = {a: set(x.lower() for x in v) for a, v in B.items()}
newb = {a: set() for a in ("greenhouse", "ashby", "lever")}
seen, keep, why, read = set(), [], {}, 0
def W(k): why[k] = why.get(k, 0) + 1
for b in BOARDS:
    nb = 0
    for q in QUERIES:
        h, code = fetch(f"https://{b}/jobs?q={urllib.parse.quote(q)}")
        if h is None:
            print(f"  {b} q={q}: {code}");
            if code in (401, 403, 406, 429, 503, "paused"): break
            continue
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
        try: found = json.loads(m.group(1))["props"]["pageProps"]["initialState"]["jobs"]["found"]
        except Exception: found = []
        for j in found:
            jid = j.get("id")
            if jid in seen: continue
            seen.add(jid); read += 1; nb += 1
            u = j.get("url") or ""
            for rx, a in TOKRX:
                mm = rx.search(u)
                if mm and mm.group(1).lower() not in known[a] and mm.group(1).lower() not in ("v1", "embed", "jobs"): newb[a].add(mm.group(1))
            ts = float(j.get("createdAt") or 0)
            if ts < CUT: W("older than window"); continue
            if ts < OLD_GETRO and not os.environ.get("HARVEST_ALL"): W("screened by the old pipeline"); continue
            co = (j.get("organization") or {}).get("name") or ""; t = j.get("title") or ""
            if not ns["ENG"].search(t) or not ns["LEVEL"].search(t) or ns["NO"].search(t): W("title"); continue
            if ns["STAFF"].search(co): W("staffing"); continue
            if ns["FRONTIER"].search(co.strip()) and not ns["FIN"].search(t): W("frontier lab: finance roles only"); continue
            locs = list(j.get("searchableLocations") or []) or [x.get("name") or "" for x in j.get("locationDetails") or []]
            wm = (j.get("workMode") or "").replace("_", "")
            ok, lw = loc_ok(locs, wm == "remote", {"remote": "Remote", "hybrid": "Hybrid", "onsite": "OnSite"}.get(wm, ""))
            if not ok: W("location: " + lw); continue
            mx = j.get("compensationAmountMaxCents")
            if mx and (j.get("compensationCurrency") or "USD") == "USD" and mx / 100 < 180000 and (j.get("compensationPeriod") or "year") in ("year", "period_not_defined"): W("pay below floor"); continue
            okg, gw = g.allow(co, t, u, extra=keep)
            if not okg: W("gate: " + gw.split("(")[0].strip()); continue
            keep.append({"board": b, "company": co, "title": t, "url": u, "created": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(ts)), "locs": locs, "work_mode": wm,
                         "pay": f"{(j.get('compensationAmountMinCents') or 0)/100:.0f}-{(mx or 0)/100:.0f} {j.get('compensationCurrency') or ''}".strip() if mx else "", "why_loc": lw})
        time.sleep(1.5)
    print(f"{b}: {nb} jobs")
added = {a: sorted(v) for a, v in newb.items()}
for a, v in added.items(): B[a] = sorted(set(B.get(a, [])) | set(v))
json.dump(B, open(os.path.join(HERE, "boards.json"), "w"), indent=0)
keep.sort(key=lambda r: r["created"], reverse=True)
json.dump(keep, open(os.path.join(OUTD, f"getro_{tag}.json"), "w"), indent=0)
print(f"getro {tag}: boards {len(BOARDS)} | jobs read {read} | kept {len(keep)} | new ATS boards { {a: len(v) for a, v in added.items()} } | dropped {dict(sorted(why.items(), key=lambda x: -x[1]))}")
for r in keep: print(f"  {r['created']} | {r['company'][:26]:26} | {r['title'][:60]:60} | {' / '.join(r['locs'])[:40]:40} | {r['pay'][:18]:18} | {r['url'][:110]}")
