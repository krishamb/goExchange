"""harvest.py <tag> [days=7] [ats=ashby,lever,greenhouse] -> one sweep of the public board APIs (rebuilt 2026-11-28).

Reads boards.json ({"ashby": [...], "lever": [...], "greenhouse": [...]}), lists every board's jobs, keeps postings
published inside the window that pass the title / location / pay rules and gates.allow, and writes
<scratchpad>/harvest/<tag>.json (rows) plus a one-line summary. Refusal-aware: the FIRST 401 / 403 / 406 / 429 / 503
from a host stops all requests to that host and writes a 24 h pause to blocks.json (kept in the repo, so a container
reset does not forget it). Greenhouse boards-api is read at most every other hour (blocks.json 'gh_last')."""
import json, os, re, sys, time, html, datetime, threading, urllib.request, urllib.error, concurrent.futures as cf
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import gates as g
SC = "/tmp/claude-0/-home-user-goExchange/8d20ffb7-2488-5f8f-a666-35334b9e3ba6/scratchpad"
OUTD = os.path.join(SC, "harvest"); os.makedirs(OUTD, exist_ok=True)
tag = sys.argv[1]; DAYS = float(sys.argv[2]) if len(sys.argv) > 2 else 7
ATS = (sys.argv[3] if len(sys.argv) > 3 else "ashby,lever,greenhouse").split(",")
NOW = time.time(); CUT = NOW - DAYS * 86400
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept": "application/json"}
BLK = os.path.join(HERE, "blocks.json"); LOCK = threading.Lock()
try: BLOCKS = json.load(open(BLK))
except Exception: BLOCKS = {}
def save_block(key, val):   # merge-on-write: other sweeps may have written blocks.json since this one started
    try: cur = json.load(open(BLK))
    except Exception: cur = {}
    cur[key] = val; BLOCKS[key] = val; json.dump(cur, open(BLK, "w"), indent=1)
def paused(host): return NOW < float(BLOCKS.get(host, {}).get("until", 0))
def pause(host, code):
    with LOCK:
        save_block(host, {"until": time.time() + 86400, "code": code, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
REFUSED = set()
def get(u, t=30):
    h = urllib.parse.urlsplit(u).hostname
    if h in REFUSED or paused(h): return None
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=t) as r: return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 406, 429, 503):
            with LOCK:
                if h not in REFUSED: REFUSED.add(h); pause(h, e.code); print("  REFUSED", e.code, h, "- host paused 24 h", flush=True)
        return None
    except Exception: return None
import urllib.parse

ENG = re.compile(r"engineer|engineering|software|platform|infrastructure|\bdata\b|\bai\b|\bml\b|machine learning|architect|\btechnology\b|\btechnical\b|developer|backend|back-end|full[- ]?stack|\bsystems\b|\bcto\b|chief technology|forward deployed", re.I)
LEVEL = re.compile(r"\b(cto|chief|vp|svp|vice president|head of|director|manager|principal|staff|senior|sr\.?|lead|architect|distinguished|fellow)\b", re.I)
NO = re.compile(r"\b(sales|pre-?sales|account (executive|manager|director)|solutions? (engineer|consultant|architect)\w*|customer (success|support|experience|engineer)\w*|support engineer|product (manager|management|owner|marketing|design)|design\w*|security|devsecops|devops|sre\b|site reliability|reliability|\bqa\b|quality|\btest\w*|front[- ]?end|\bios\b|android|mobile|hardware|firmware|mechanical|electrical|manufactur\w*|\basic\b|\bsoc\b|silicon|\bchip|\brtl\b|verification|analog|physical design|\brf\b|research\w*|recruit\w*|talent|marketing|legal|counsel|intern\b|internship|junior|associate|founding|member of technical staff|\bmts\b|co-?founder|contract\w*|clearance|ts/sci|polygraph|field|implementation|professional services|technical writer|teacher|tutor|medical|clinical|nurse|pharma\w*|supply chain|finance\b|financial planning|accounting|risk\b|compliance|business development|partnerships?|creative|advertising|operations\b|people|hr\b|human resources|program manager|project manager|scrum|delivery manager|controls engineer|robotic controls|optical|laser|fiber|amplifier|photonic\w*|power\b|data center|site development|planner|data scientist|developer advocate|developer relations|devrel|advocate|evangelist|governance|payroll|partner\b|consultant|asset management|cooling|safety|r&d|optics|mechatronics|controls\b|analyst|detection|incident response|\bcpu\b|\bgpu (design|architect)|master data|\bepic\b|robotics engineer|deployments\b|network (access|security|engineer\w*|architect\w*|operations|administrat\w*)|\bnac\b|wireless|enterprise connectivity|telecom\w*)", re.I)
FRONTIER = re.compile(r"^(openai|xai|x\.ai|spacex ?si|anthropic|meta|thinking machines|thinkingmachines|ssi|safe superintelligence|mistral|cohere|deepmind|google deepmind)$", re.I)
FIN = re.compile(r"financ|payment|billing|fintech|revenue|treasury|accounting|commerce|monetiz|trading|risk", re.I)
NONUS = re.compile(r"\b(malaysia|kuala lumpur|china|beijing|shanghai|shenzhen|hong kong|taiwan|taipei|thailand|bangkok|new zealand|nz|wellington|auckland|pakistan|bangladesh|egypt|cairo|morocco|saudi|qatar|costa rica|uruguay|guatemala|canada|toronto|vancouver|montreal|mexico|brazil|argentina|colombia|chile|peru|uk|united kingdom|london|england|ireland|dublin|europe|emea|apac|germany|berlin|munich|france|paris|spain|madrid|barcelona|portugal|lisbon|netherlands|amsterdam|poland|warsaw|india|bengaluru|bangalore|hyderabad|pune|singapore|australia|sydney|japan|tokyo|korea|israel|tel aviv|switzerland|zurich|sweden|stockholm|denmark|norway|finland|italy|romania|ukraine|philippines|vietnam|indonesia|uae|dubai|south africa|nigeria|kenya|turkey|czech|hungary|austria|belgium|greece|estonia|latvia|lithuania|serbia|croatia)\b", re.I)
USOK = re.compile(r"united states|\busa?\b|us remote|remote.{0,4}(us|usa|united)|\bamericas\b|north america|anywhere", re.I)
BAY = re.compile(r"san francisco|bay area|palo alto|mountain view|sunnyvale|san jose|santa clara|oakland|menlo park|redwood city|berkeley|emeryville|san mateo|foster city|burlingame|cupertino|fremont|milpitas|south san francisco|san carlos|los gatos|campbell|san rafael|walnut creek|pleasanton|dublin, ca|hayward|newark, ca|union city|livermore", re.I)
US_CITY = re.compile(r", ?(al|ak|az|ar|ca|co|ct|de|fl|ga|hi|id|il|in|ia|ks|ky|la|me|md|ma|mi|mn|ms|mo|mt|ne|nv|nh|nj|nm|ny|nc|nd|oh|ok|or|pa|ri|sc|sd|tn|tx|ut|vt|va|wa|wv|wi|wy|dc)\b|new york|seattle|austin|boston|chicago|denver|atlanta|los angeles|washington|miami|dallas|houston", re.I)

def loc_ok(locs, remote, wp):
    s = " / ".join(l for l in locs if l)
    if BAY.search(s) and not (NONUS.search(s) and not re.search(r"\bca\b|california|bay area", s, re.I)): return True, "bay area"
    w = (wp or "").lower().replace("-", "").replace(" ", "")
    if w in ("hybrid", "onsite", "inoffice"): return False, "on-site / hybrid outside the Bay Area"   # Ashby sets isRemote on hybrid roles too; its workplaceType wins
    is_remote = w == "remote" or remote or re.search(r"remote|anywhere|distributed", s, re.I)
    if not is_remote:
        return False, ("non-US" if NONUS.search(s) and not USOK.search(s) else "on-site / hybrid outside the Bay Area")
    if USOK.search(s): return True, "remote (US)"
    if NONUS.search(s): return False, "non-US"
    if re.fullmatch(r"\s*(remote|anywhere|distributed|global|worldwide)?\s*", re.sub(r"[^a-z ]", " ", s.lower())): return True, "remote (region unstated)"
    if US_CITY.search(s): return True, "remote (US city listed)"
    return False, "remote outside the US"

STAFF = re.compile(r"sourcedirect|raydar|miratech|actionet|devaltus|slalom|deloitte|accenture|cognizant|infosys|wipro|\btcs\b|tata consultancy|capgemini|\bepam\b|globant|provectus|lazer technologies|tech mahindra|ntt data|jobgether|talent solutions|staffing|recruit|headhunt|search partners|true-talent|bjakcareer|lensa|jobot|cybercoders|hackajob|meet-archer|digital waffle|oho group|signify technology|futuretech", re.I)
def pay_max(s):
    v = [float(a.replace(",", "")) * (1000 if k.lower() == "k" else 1) for a, k in re.findall(r"\$\s?([\d,]+(?:\.\d+)?)\s*([kK]?)", s or "")]
    v = [x for x in v if x >= 1000]
    return max(v) if v else None

def txt(x): return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x or ""))).strip()
def iso(ts): return datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%dT%H:%MZ") if ts else ""
def pts(s):
    if not s: return None
    if isinstance(s, (int, float)): return s / (1000 if s > 1e12 else 1)
    try: return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception: return None

def ashby(slug):
    d = get(f"https://api.ashbyhq.com/posting-api/job-board/{urllib.parse.quote(slug)}?includeCompensation=true")
    out = []
    for j in (d or {}).get("jobs", []) or []:
        locs = [j.get("location") or ""] + [x.get("location") or "" for x in j.get("secondaryLocations") or []]
        out.append(dict(ats="ashby", board=slug, company=j.get("organizationName") or slug, title=j.get("title") or "", url=j.get("jobUrl") or "",
                        ts=pts(j.get("publishedAt")), locs=locs, remote=bool(j.get("isRemote")), wp=j.get("workplaceType") or "",
                        emp=j.get("employmentType") or "", pay=(j.get("compensation") or {}).get("compensationTierSummary") or "", jd=txt(j.get("descriptionHtml"))[:6000]))
    return out
def lever(slug):
    d = get(f"https://api.lever.co/v0/postings/{urllib.parse.quote(slug)}?mode=json")
    out = []
    for j in d or []:
        c = j.get("categories") or {}; sr = j.get("salaryRange") or {}
        pay = f"${sr.get('min')} - ${sr.get('max')}" if sr.get("max") else ""
        out.append(dict(ats="lever", board=slug, company=slug, title=j.get("text") or "", url=j.get("hostedUrl") or "", ts=pts(j.get("createdAt")),
                        locs=[c.get("location") or ""] + list(c.get("allLocations") or []), remote=(j.get("workplaceType") == "remote"), wp=j.get("workplaceType") or "",
                        emp=c.get("commitment") or "", pay=pay, jd=txt(j.get("descriptionPlain") or j.get("description"))[:6000]))
    return out
def greenhouse(slug):
    d = get(f"https://boards-api.greenhouse.io/v1/boards/{urllib.parse.quote(slug)}/jobs?content=true", 60)
    out = []
    for j in (d or {}).get("jobs", []) or []:
        jd = txt(j.get("content"))
        out.append(dict(ats="greenhouse", board=slug, company=j.get("company_name") or slug, title=j.get("title") or "", url=j.get("absolute_url") or "",
                        ts=pts(j.get("first_published") or j.get("updated_at")), locs=[(j.get("location") or {}).get("name") or ""], remote=False, wp="",
                        emp="", pay=" ".join(re.findall(r"\$[\d,]+(?:\.\d+)?[kK]?\s*(?:-|–|to)\s*\$[\d,]+(?:\.\d+)?[kK]?", jd))[:80], jd=jd[:6000]))
    return out

FROM = os.environ.get("HARVEST_FROM")   # re-screen saved rows (no requests), e.g. HARVEST_FROM=<scratchpad>/harvest/<tag>_raw.json
if not FROM and "greenhouse" in ATS and NOW - float(BLOCKS.get("gh_last", {}).get("t", 0)) < 7000:
    print("greenhouse skipped (harvested less than 2 h ago; every-other-hour rule)"); ATS = [a for a in ATS if a != "greenhouse"]
B = json.load(open(os.path.join(HERE, "boards.json")))
try: ADDED = {a: {x.lower() for x in v} for a, v in json.load(open(os.path.join(HERE, "boards_added.json"))).items()}   # boards added after the reset
except Exception: ADDED = {}
if os.environ.get("HARVEST_ONLY_ADDED"): B = {a: [x for x in v if x.lower() in ADDED.get(a, set())] for a, v in B.items()}
FN = {"ashby": ashby, "lever": lever, "greenhouse": greenhouse}; WORKERS = {"ashby": 8, "lever": 8, "greenhouse": 4}
jobs, why = [], {}
def W(k): why[k] = why.get(k, 0) + 1
for a in ([] if FROM else ATS):
    with cf.ThreadPoolExecutor(WORKERS[a]) as ex:
        for res in ex.map(FN[a], B.get(a, [])): jobs.extend(res)
    if a == "greenhouse": save_block("gh_last", {"t": time.time()})
if FROM: jobs = json.load(open(FROM))
else: json.dump(jobs, open(os.path.join(OUTD, f"{tag}_raw.json"), "w"))
# 2026-11-28: the old scratchpad pipeline (lost in the reset) had already screened every Ashby / Lever posting published
# before its last cycle (c627, ~03:43Z Nov 28) and every Greenhouse posting before its boards-api pause (04:19:36Z Nov 27);
# those rows are already in the applicant's files, applied, or were dropped on closer reading -> only newer postings are new.
OLD_SCREENED = {"ashby": "2026-11-28T03:40:00", "lever": "2026-11-28T03:40:00", "greenhouse": "2026-11-27T04:19:36"}
OLD_CUT = {a: datetime.datetime.fromisoformat(v).replace(tzinfo=datetime.timezone.utc).timestamp() for a, v in OLD_SCREENED.items()}
RANK = {"exec": 0, "director": 1, "manager": 2, "staff": 3, "senior": 4}
jobs.sort(key=lambda j: (RANK.get(g.level(j.get("title")), 9), -(j.get("ts") or 0)))   # leadership first, so the 3-role cap keeps the senior-most roles
keep, seen = [], set()
for j in jobs:
    if not j["ts"] or j["ts"] < CUT: W("older than window"); continue
    if j["ts"] < OLD_CUT.get(j["ats"], 0) and not os.environ.get("HARVEST_ALL") and j["board"].lower() not in ADDED.get(j["ats"], set()): W("screened by the old pipeline"); continue
    t = j["title"]
    if not ENG.search(t) or not LEVEL.search(t) or NO.search(t): W("title"); continue
    if re.search(r"part[- ]?time|intern|temporary|contract", j["emp"], re.I): W("not full-time"); continue
    ok, lw = loc_ok(j["locs"], j["remote"], j["wp"])
    if not ok: W("location: " + lw); continue
    pm = pay_max(j["pay"])
    if pm is not None and pm < 180000: W("pay below floor"); continue
    if STAFF.search(j["company"] + " " + j["board"]): W("staffing / aggregator"); continue
    if (FRONTIER.search(j["company"].strip()) or FRONTIER.search(j["board"].strip())) and not FIN.search(t): W("frontier lab: finance roles only"); continue
    ok, gw = g.allow(j["company"], t, j["url"], extra=keep)
    if not ok: W("gate: " + gw.split("(")[0].strip()); continue
    k = (g.key(j["company"]), t.lower())
    if k in seen: W("duplicate"); continue
    seen.add(k); j["posted_iso"] = iso(j["ts"]); j["why_loc"] = lw; keep.append(j)
keep.sort(key=lambda j: -j["ts"])
out = os.path.join(OUTD, f"{tag}.json"); json.dump(keep, open(out, "w"), indent=0)
print(f"harvest {tag}: ats {ATS} | boards { {a: len(B.get(a, [])) for a in ATS} } | postings {len(jobs)} | kept {len(keep)} | refused {sorted(REFUSED)} | dropped {dict(sorted(why.items(), key=lambda x: -x[1]))}")
for j in keep: print(f"  {j['posted_iso']} | {j['ats']:10} | {j['company'][:24]:24} | {j['title'][:60]:60} | {' / '.join(x for x in j['locs'] if x)[:40]:40} | {j['pay'][:28]:28} | {j['url']}")
