"""Oracle Recruiting Cloud (Candidate Experience) application filler: *.oraclecloud.com/hcmUI/CandidateExperience/...
(and company vanity hosts that serve the same CE app, e.g. enterprise platform hosts).

usage: apply_oraclecloud.py <queue.json> [--submit] [--headed] [--pace MIN MAX]
  queue items: {"ats","url","tag","company","title","loc","where","src","resume"}   (resume: exec | main | blockchain)
  optional per item: "answers": {"<label substring>": "<answer>" | [...]} - the applicant's own answers to questions the
  rules leave open (reported as unanswered by a dry run); they win over the rules.
env: CODE_WAIT (s, default 420), ORC_DUMP=1 (save each page's screenshot + HTML in out/), JOBS_DIR, ME_JSON.

Flow: /job/<id>/apply/email asks for an email and the terms checkbox (no account). A returning email gets a one-time
code by email ("Confirm Your Identity"): the filler prints CODE REQUEST <tag> and waits for out/<tag>_code.txt (same
convention as apply.py). The CE session of each tenant host is kept in out/orc_state/<host>[.session].json (outside the
repository: cookies + localStorage + the CE sessionStorage) so a rerun on the same host continues the draft without a new code
while the CE session lasts (a few hours); after that a code is needed again. The form is one long page (standard flow)
or several pages joined by Next; every field is answered from apply.py's reviewed rule tables (TEXT_RULES /
CHOICE_RULES / tech_answer), the resume is uploaded, and the filler stops before Submit: a dry run (default) writes
out/<tag>_oraclecloud_dry.png and reports what is missing. With --submit it clicks Submit and reports submitted only
after the site's own confirmation. A required question with no rule is never guessed; AI-use / "I personally
completed this application" certifications are never ticked (left for the applicant and reported). A CAPTCHA is never
touched: the item is reported as "NOT SUBMITTED: captcha". The hidden honey-pot input is never filled.
Contact details come from /root/jobs-private/me.json (email, phone) and JOBS_DIR/profile.json at run time only.

Output: one JSON line per item on stdout {"tag","ats","url","submitted","result","unanswered","errors"}; CODE REQUEST
lines also go to stdout; every other log line goes to stderr."""
import asyncio, json, os, re, sys, time, random, datetime
from urllib.parse import urlparse
from playwright.async_api import async_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.expanduser(os.environ.get("JOBS_DIR", "/tmp/claude-0/-home-user-goExchange/8d20ffb7-2488-5f8f-a666-35334b9e3ba6/scratchpad/f"))
OUT = os.path.join(JOBS_DIR, "out"); os.makedirs(OUT, exist_ok=True)
STATE_DIR = os.path.join(OUT, "orc_state"); os.makedirs(STATE_DIR, exist_ok=True)
ME_FILE = os.environ.get("ME_JSON", "/root/jobs-private/me.json")
P = json.load(open(os.path.join(JOBS_DIR, "profile.json")))
for _k in ("resume", "cover_letter"):
    if P.get(_k): P[_k] = os.path.expanduser(P[_k])
try:   # contact details: the private me.json wins over profile.json
    _me = json.load(open(ME_FILE))
    for _k in ("email", "phone"):
        if _me.get(_k): P[_k] = _me[_k]
except Exception:
    pass
ANS = json.load(open(os.path.join(JOBS_DIR, "answers.json"))) if os.path.exists(os.path.join(JOBS_DIR, "answers.json")) else {}
SUBMIT = "--submit" in sys.argv
HEADED = "--headed" in sys.argv
PACE = (float(sys.argv[sys.argv.index("--pace") + 1]), float(sys.argv[sys.argv.index("--pace") + 2])) if "--pace" in sys.argv else (20, 60)
CODE_WAIT = int(os.environ.get("CODE_WAIT", "420"))
JOB_TIMEOUT = int(os.environ.get("ORC_JOB_TIMEOUT", str(CODE_WAIT + 600)))
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
ATS = "oraclecloud"

# ---- the shared answer rules, taken from apply.py's source (apply.py runs its CLI at import time, so it is not imported)
_src = open(os.path.join(HERE, "apply.py")).read()
def _seg(a, b):
    i = _src.index(a); return _src[i:_src.index(b, i)]
G = {"re": re, "json": json, "os": os, "time": time, "datetime": datetime, "date": datetime.date, "P": P, "ANS": ANS}
exec(_src[_src.index("first,last="):_src.index("\n", _src.index("first,last="))], G)
exec(_seg("TEXT_RULES=[", "\ndef pick("), G)          # TEXT_RULES, CHOICE_RULES and tech_answer()
exec(_seg("def pick(", "\nLABEL_JS"), G)
exec(_seg("EDU_START=", "\nasync def is_edu_date"), G)
exec(_seg("def _match(", "\nasync def open_menu"), G)
exec(_seg("HEAR_Q=", "\nasync def choose_react_select"), G)
exec(_seg("NEVER_APPLY=", "\n"), G)
exec(_seg("NJ_LOC=", "\n    return None\n") + "\n    return None\n", G)
TEXT_RULES, CHOICE_RULES, pick, best_index, _match, mask_hear, NEVER_APPLY, tech_answer, location_block = (G[k] for k in ("TEXT_RULES", "CHOICE_RULES", "pick", "best_index", "_match", "mask_hear", "NEVER_APPLY", "tech_answer", "location_block"))
HEAR_Q, HEAR_BAD, EDU_START, EDU_END = G["HEAR_Q"], G["HEAR_BAD"], G["EDU_START"], G["EDU_END"]
FIRST, LAST = G["first"], G["last"]
# salary in a numeric-only field: the low end of the rules' salary range ("$220,000 - $350,000 ...") as digits
_sal = pick("salary expectations", TEXT_RULES) or ""
_m = re.search(r"\d[\d,]{4,}", _sal)
SALARY_NUM = _m.group(0).replace(",", "") if _m else None

RESUME_VARIANTS = {"exec": "Ambarish_Krishnamurthy_Executive_Resume.pdf", "main": "Ambarish_Krishnamurthy_Resume.pdf", "blockchain": "Ambarish_Krishnamurthy_Blockchain_AI_Resume.pdf"}
EXEC_RESUME = os.path.join(JOBS_DIR, RESUME_VARIANTS["exec"])
def resume_for(item):
    v = RESUME_VARIANTS.get(str(item.get("resume") or ""))
    if v and os.path.exists(os.path.join(JOBS_DIR, v)): return os.path.join(JOBS_DIR, v)
    title = item.get("title") or ""
    if os.path.exists(EXEC_RESUME) and re.search(r"\b(CTO|Chief|VP|SVP|Vice President|Head of|Director|Manager)\b", title, re.I) and not re.search(r"Architect", title, re.I):
        return EXEC_RESUME
    return P["resume"]

# ---- guards (never answered by the filler; the applicant answers these)
AI_CERT = re.compile(r"personally (completed|filled|prepared|written|wrote|answered)|(completed|filled( out)?|written|prepared) (this|the|my) (application|form) (myself|personally|on my own|without)|"
                     r"no (ai|artificial intelligence)\b|without (the )?(use of |help of |assistance of )?(any )?(ai|artificial intelligence|generative)|(ai|artificial intelligence) (was|were|has been|have been) (not )?used|"
                     r"(did|have) (not |n.t )?use[d]? (any )?(ai|artificial intelligence|chatgpt|generative)|are you an ai\b|ai agent (is|was) (applying|completing)|ai policy|ai assistance|"
                     r"(certify|attest|confirm) .{0,60}(own words|not (been )?(generated|written)|myself)", re.I)
# the core 'I did it myself / no AI' certifications: these stay with the applicant even when the same sentence also gives an AI consent
AI_CERT_STRONG = re.compile(r"personally (completed|filled|prepared|written|wrote|answered)|(completed|filled( out)?|written|prepared) (this|the|my) (application|form) (myself|personally|on my own|without)|"
                            r"no (ai|artificial intelligence)\b|without (the )?(use of |help of |assistance of )?(any )?(ai|artificial intelligence|generative)|(did|have) (not |n.t )?use[d]? (any )?(ai|artificial intelligence|chatgpt|generative)|"
                            r"(answers|responses|application|statements|work|writing) (provided |given |submitted )?(here(in)? )?(are|is|were|was) (entirely |all |wholly |solely )?my own|(certify|attest|confirm) .{0,60}(own words|my own|not (been )?(generated|written)|myself)", re.I)
AI_CONSENT = re.compile(r"transcri|note-?tak|record(ing)? (of )?(your|the|my) interview|interview (notes|recordings?)|(ai|artificial intelligence) (to|in) (screen|review|evaluat|assess|match)", re.I)
VISA_STATUS_Q = re.compile(r"\b(based on|because of|by virtue of|derived from|depend\w* on|through|status as)\b.{0,60}\b(spouse|dependent|h-?1b|h-?4|l-?1|l-?2|f-?1|j-?1|opt|cpt|ead|tn|visa|asylum|refugee|daca|tps)\b", re.I)
COMMUTE_Q = re.compile(r"^(?!.*\b(willing to relocate|or relocate|able to relocate)\b).*\b(live|living|reside|residing|located|based)\b.{0,30}\b(within|in|near)\b.{0,50}\b(commut\w*|the office|office location|this location|job location|(the|our|designated|nearest)\b.{0,30}\b(office|hub|site|location))", re.I)
# 'can you work on site 5 days a week?': apply.py answers Yes (Bay Area: any work mode); outside the Bay Area the applicant never
# works 5 days in an office, so there the question is left for the applicant instead
FIVE_DAYS_Q = re.compile(r"(5|five) days? (per|a|each|every) week|5 days/week|(5|five)[- ]days?[- ](on-?site|in[- ]office|in[- ]person|in the office)|\b5x\b|fully on-?site|100% (on-?site|in[- ]office)", re.I)
BAY = re.compile(r"san francisco|bay area|palo alto|menlo park|mountain view|sunnyvale|san jose|santa clara|redwood city|san mateo|oakland|foster city|cupertino|milpitas|fremont|pleasanton|emeryville|bay-", re.I)
DISC = re.compile(r"non-?compete|non-?solicit|financial interest|conflict of interest|relatives?\b|family member|government official|convicted|felony|yes, i (have|had) (a |an )?(disabilit|relative|conflict|criminal|conviction)|^\s*i have a disability", re.I)
ACK = re.compile(r"i (have read|acknowledge|agree|understand|consent|certify|confirm|accept)|terms and conditions|privacy (notice|policy|statement)|^accept\*?$|by (selecting|checking|clicking)", re.I)
# the current employer's business with the hiring company (reseller / customer / partner / its staff on site): facts the
# applicant knows and the rules do not (a generic 'may we contact your employer' rule once answered 'reseller of Dell?' Yes)
EMPLOYER_REL = re.compile(r"(current|previous|past|your) employer.{0,90}\b(a |an )?(reseller|partner|customer|client|vendor|supplier|distributor|competitor|relationship|business with)\b|\b(reseller|distributor|supplier|vendor) of\b|personnel .{0,90}(on ?site|at your employer|your employer)|interact with .{0,80}personnel|provides? (services|products) to your employer", re.I)
CONSENT_Q = re.compile(r"\b(consent|permission|i agree|agree to|acknowledge|i understand)\b|grant(ing)? .{0,40}permission|"
                       r"(keep|retain|store|hold) (on to )?your (application|information|data|resume|profile|details)|reach out (to you )?(about|if|when|for) .{0,40}(roles?|positions?|opportunit)|"
                       r"considered for other (roles|positions|opportunities|openings|jobs)", re.I)
ACK_OPT = re.compile(r"^\s*(yes,? )?i (hereby )?(understand|acknowledge|agree|consent|accept)|^\s*(i agree|agree|accept|acknowledged?)\.?\s*$", re.I)
ACK_TOPIC = re.compile(r"record|interview|video|audio|photograph|screenshot|consent|acknowledg|privacy|policy|terms|notice|understand|agree|permission|disclos", re.I)
ACK_ASK = re.compile(r"please acknowledge|acknowledge (this|the|that|receipt)|confirm (your )?(understanding|acknowledg|acceptance)|indicate (your )?(acknowledg|acceptance|understanding)", re.I)
# questions about someone else (a parent's education, a family member's status): never answered with the applicant's facts
OTHER_PERSON_Q = re.compile(r"\b(parent|caregiver|guardian|mother|father|spouse|partner)s?\b.{0,40}\b(education|degree|school|occupation|employ|status|served|veteran|military)|\b(education|degree)\b.{0,30}\b(of|for) (your )?(parent|caregiver|guardian|mother|father)", re.I)
SALARY_SHARE = re.compile(r"(would you like|do you want|are you willing|willing) to (share|provide|disclose) (your )?(salary|compensation|pay)", re.I)
MARKETING = re.compile(r"marketing|newsletter|job alerts?|updates about new job|new job opportunities|talent community|text messages?|\bsms\b|whatsapp|news and events|promotional|"
                       r"\b(receive|get|send me|sign me up|sign up for|subscribe( to)?)\b.{0,40}\b(career|careers|recruiting|e-?mails?|news|updates|communications?|messages|alerts|events|offers|promotions?)\b", re.I)   # e.g. Oracle: 'I agree to receive careers emails with news and events'
VET_Q = re.compile(r"veteran|military", re.I)
VET_BAD = re.compile(r"^\s*(i am a |i identify as (a|one)|yes\b|protected veteran$)|^\s*(disabled|recently separated|active duty|armed forces)", re.I)
DIS_Q = re.compile(r"disabilit", re.I)
DIS_BAD = re.compile(r"^\s*yes\b|^\s*i have a disability", re.I)
RACE_Q = re.compile(r"\brace\b|races|racial|ethnic", re.I)
NEG_OPT = re.compile(r"^\s*no\b|\bnot\b|\bnever\b|\bdon'?t\b|\bdo not\b|\bhave not\b|\bhaven'?t\b|\bnone\b", re.I)

def log(tag, msg): print(f"[orc {tag}] {msg}", file=sys.stderr, flush=True)
PRINTED = set()   # tags whose one stdout JSON line has been printed
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
def loose(s):
    s = re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
    s = re.sub(r"^(i am|i m|im|i)\s+", "", s)
    return re.sub(r"\bdeclines\b", "decline", s)

def usable(texts, label):
    out = mask_hear(texts, label)
    if VET_Q.search(label or ""): out = ["" if VET_BAD.search(t or "") else t for t in out]
    if DIS_Q.search(label or ""): out = ["" if DIS_BAD.search(t or "") else t for t in out]
    return out
def rank(texts, prefs, label):
    """Index of the option matching the earliest preference: exact / leading / whole-word (apply.py's best_index), then a
    loose match ('I am not a protected veteran' = 'Not a Protected Veteran'). A positive preference never picks a negated
    option. A plain 'No' with no matching option picks the single negative option ('I have never worked for X')."""
    u0 = usable(texts, label)
    for p in prefs or []:
        if not isinstance(p, str) or p == "__ASK__": continue
        u = [t if not (t and NEG_OPT.search(t) and not NEG_OPT.search(p)) else "" for t in u0]
        k = best_index(u, p)
        if k is not None: return k
        lp = loose(p)
        k = next((i for i, t in enumerate(u) if t and lp and (loose(t) == lp or loose(t).startswith(lp + " "))), None)
        if k is not None: return k
    if prefs and isinstance(prefs[0], str) and re.fullmatch(r"\s*no\s*", prefs[0], re.I):
        neg = [i for i, t in enumerate(u0) if t and NEG_OPT.search(t)]
        if len(neg) == 1: return neg[0]
    return None
def choice_for(label):
    v = pick(label, CHOICE_RULES)
    if v is None: return None
    return v if isinstance(v, list) else [v]
def text_for(label):
    v = pick(label, TEXT_RULES)
    return v if isinstance(v, str) and v.strip() else None

# ---- page helpers
CAPTCHA = 'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="challenges.cloudflare"], iframe[src*="turnstile"], iframe[title*="captcha" i], #px-captcha, .g-recaptcha, .h-captcha, .cf-turnstile'
async def text(page):
    try: return await page.evaluate("()=>document.body.innerText")
    except Exception: return ""
async def captcha_visible(page):
    try:
        loc = page.locator(CAPTCHA)
        for i in range(await loc.count()):
            if await loc.nth(i).is_visible(): return True
    except Exception: pass
    return False
async def dismiss_cookies(page):
    """Cookie banners: strictly necessary cookies only (Decline / Opt Out / Reject). Never a button inside the application
    form: a 'Decline' answer pill or a terms dialog's 'Decline' is not a cookie banner."""
    try:
        h = await page.evaluate_handle(r"""()=>{const re=/^(decline|decline all|reject|reject all|opt out|necessary only|only necessary.*)$/i;
          return [...document.querySelectorAll('button, [role="button"]')].find(b=>!b.closest('apply-flow-block, .apply-flow-block, .cx-select-pills-container, .input-row, .apply-flow-dialog, [role="dialog"]:not([aria-label*="cookie" i]):not([class*="cookie" i]), form')
            && (b.offsetParent||b.getClientRects().length) && re.test(((b.innerText||'').trim()||b.getAttribute('aria-label')||'').replace(/\s+/g,' ').trim()))||null}""")
        el = h.as_element()
        if el:
            await el.click(timeout=2500); await page.wait_for_timeout(600); return True
    except Exception: pass
    return False

FIELDS_JS = r"""()=>{
 const root=document.querySelector('.apply-flow__content')||document.querySelector('main')||document.body;
 const vis=e=>!!(e&&(e.offsetParent||e.getClientRects().length));
 const clean=s=>(s||'').replace(/\s+/g,' ').replace(/[*✱]/g,'').trim();
 document.querySelectorAll('[data-orc]').forEach(e=>e.removeAttribute('data-orc'));   // indices from an earlier page / render are stale
 let rows=[...root.querySelectorAll('.input-row')].filter(r=>vis(r)&&!r.closest('.input-row--invisible')&&!r.querySelector('input[name="honey-pot"]'));
 rows=rows.filter(r=>!rows.some(o=>o!==r&&o.contains(r)));
 const out=[];
 rows.forEach((r,i)=>{
  r.setAttribute('data-orc',String(i));
  const blk=r.closest('apply-flow-block'); const bt=blk?clean((blk.querySelector('.apply-flow-block__title')||{}).innerText):'';
  const comp=blk?(((blk.querySelector('.apply-flow-block')||{}).className||'').match(/apply-flow-block--([a-z0-9-]+)/)||[])[1]||'':'';
  const labEl=r.querySelector('.input-row__label');
  let label=''; if(labEl){const t=labEl.querySelector('.input-row__linebreak, .input-row__label-text'); label=clean((t||labEl).innerText);}
  const hint=clean((r.querySelector('.input-row__instructions')||{}).innerText||'');
  let req=!!(r.querySelector('.input-row__label--required, .cx-select__label--required, .input-row__label--required-star, [aria-required="true"], [required]'));
  let kind='unknown', opts=[], val='', multi=false, itype='';
  const pills=r.querySelector('.cx-select-pills-container');
  const db=(r.querySelector('[data-bind*="cx-select-pills"]')||{getAttribute:()=>''}).getAttribute('data-bind')||'';
  if(pills){kind='pills'; multi=/isMultiselect\s*:\s*true/.test(db);
    const bs=[...pills.querySelectorAll('button')]; opts=bs.map(b=>clean(b.innerText));
    val=bs.filter(b=>b.getAttribute('aria-checked')==='true'||b.getAttribute('aria-pressed')==='true'||/selected|active|checked/.test(b.className)).map(b=>clean(b.innerText)).join('; ');
    if(!label) label=clean(pills.getAttribute('aria-label'));}
  else if(r.querySelector('.datepicker-row__input')){kind='monthyear'; val=[...r.querySelectorAll('.datepicker-row__input input.cx-select-input')].map(x=>x.value).filter(x=>x).join(' ');
    opts=[...r.querySelectorAll('.datepicker-row__input')].map(x=>((x.className.match(/datepicker-row__input--(\w+)/)||[])[1]||''));}
  else if(r.querySelector('.phone-row')){kind='phone'; const t=r.querySelector('input[type=tel]'); val=t?t.value:''; const pf=r.querySelector('input.cx-select-input'); opts=[pf?pf.value:''];}
  else if(r.querySelector('input.cx-select-input')){const inp=r.querySelector('input.cx-select-input'); kind=(/isAutoSuggest\s*:\s*true/.test((r.querySelector('[data-bind*="cx-select"]')||{getAttribute:()=>''}).getAttribute('data-bind')||''))?'autosuggest':'select'; val=inp.value; if(!label) label=clean(inp.getAttribute('aria-label'));}
  else if(r.querySelector('input[type=checkbox]')){kind='checkbox'; const cbs=[...r.querySelectorAll('input[type=checkbox]')];
    opts=cbs.map(c=>{const l=(c.id&&r.querySelector('label[for="'+CSS.escape(c.id)+'"]'))||c.closest('label')||c.parentElement; return clean((l.querySelector('.apply-flow-input-checkbox__label')||l).innerText);});
    val=cbs.map((c,j)=>c.checked?opts[j]:null).filter(x=>x).join('; '); multi=cbs.length>1; if(!label) label=cbs.length===1?opts[0]:'';
    if(r.getAttribute('aria-labelledby')&&!label){const l=document.getElementById(r.getAttribute('aria-labelledby')); if(l) label=clean(l.innerText);}
    if(cbs.some(c=>c.required||c.getAttribute('aria-required')==='true')) req=true;}
  else if(r.querySelector('input[type=radio]')){kind='radio'; const rs=[...r.querySelectorAll('input[type=radio]')];
    opts=rs.map(c=>{const l=(c.id&&document.querySelector('label[for="'+CSS.escape(c.id)+'"]'))||c.closest('label')||c.parentElement; return clean(l.innerText);});
    val=rs.map((c,j)=>c.checked?opts[j]:null).filter(x=>x).join('; ');}
  else if(r.querySelector('textarea.input-row__control:not(.input-row__control--helper), oj-text-area')){kind='textarea'; const t=r.querySelector('textarea.input-row__control:not(.input-row__control--helper), oj-text-area textarea'); val=t?t.value:'';}
  else if(r.querySelector('input[type=date], oj-input-date, [class*="date-picker"], [class*="datepicker"]')){kind='date'; const t=r.querySelector('input'); val=t?t.value:'';}
  else if(r.querySelector('input.input-row__control, input[type=text], input[type=email], input[type=url], input[type=number], input[type=tel]')){
    const t=r.querySelector('input.input-row__control, input[type=text], input[type=email], input[type=url], input[type=number], input[type=tel]');
    kind='text'; val=t.value; itype=(t.getAttribute('type')||'text')+'|'+(t.getAttribute('inputmode')||'')+'|'+(t.getAttribute('name')||'');
    if(t.readOnly||t.disabled) kind='readonly';}
  else if(r.querySelector('select')){kind='nselect'; const s=r.querySelector('select'); opts=[...s.options].map(o=>clean(o.text)); val=s.selectedIndex>0?clean(s.options[s.selectedIndex].text):'';}
  if(!label&&r.getAttribute('aria-labelledby')){const l=document.getElementById(r.getAttribute('aria-labelledby').split(' ')[0]); if(l) label=clean(l.innerText);}
  if(kind==='unknown'&&r.classList.contains('input-row--filled')) val=clean((r.querySelector('.input-row__control-container')||r).innerText)||'(filled)';
  out.push({i, label, hint:hint.slice(0,300), kind, req, val:clean(val), opts, multi, itype, block:bt, comp, html:kind==='unknown'?r.outerHTML.replace(/<!--.*?-->/g,'').replace(/\s+/g,' ').slice(0,1500):''});
 });
 return out;}"""

ROW = lambda i: f'[data-orc="{i}"]'

async def fill_text(page, loc, val):
    try:
        await loc.scroll_into_view_if_needed(timeout=3000)
        await loc.click(timeout=3000)
        await loc.fill("")
        await loc.type(val, delay=8) if len(val) < 120 else await loc.fill(val)
        await loc.press("Tab"); await page.wait_for_timeout(150)
        return (await loc.input_value()).strip() != ""
    except Exception:
        return False

async def cx_options(page, inp):
    lid = await inp.get_attribute("aria-controls")
    if not lid: return None, []
    cells = page.locator(f'[id="{lid}"] [role="gridcell"], [id="{lid}"] [role="option"]')
    texts = []
    for i in range(min(await cells.count(), 300)):
        try: texts.append(re.sub(r"\s+", " ", await cells.nth(i).inner_text()).strip())
        except Exception: texts.append("")
    return cells, texts

async def cx_choose(page, row, prefs, label, queries=(), ranker=None, inp=None):
    """cx-select (react combobox): open it, optionally type a search, click the best option, verify the input shows it.
    Returns (chosen text or None, options seen)."""
    inp = inp or row.locator("input.cx-select-input").first
    seen = []
    for q in [None] + [x for x in queries if x]:
        try:
            await inp.scroll_into_view_if_needed(timeout=3000)
            await inp.click(timeout=3000)
            if q is not None:
                await inp.fill(""); await inp.type(q, delay=50)
            await page.wait_for_timeout(1300 if q else 700)
            cells, texts = await cx_options(page, inp)
            if texts: seen = texts
            k = ranker(texts) if ranker else rank(texts, prefs, label)
            if k is None:
                await page.keyboard.press("Escape"); await page.wait_for_timeout(200); continue
            want = texts[k]
            await cells.nth(k).scroll_into_view_if_needed(timeout=3000)
            await cells.nth(k).click(timeout=4000); await page.wait_for_timeout(900)
            got = (await inp.input_value()).strip()
            if got and (norm(got) in norm(want) or norm(want) in norm(got) or norm(got.split(",")[0]) == norm(want.split(",")[0])):
                return got, seen
            if got: return got, seen
        except Exception:
            try: await page.keyboard.press("Escape")
            except Exception: pass
    return None, seen

async def pills_choose(page, row, prefs, label, multi=False):
    btns = row.locator(".cx-select-pills-container button")
    texts = [re.sub(r"\s+", " ", await btns.nth(i).inner_text()).strip() for i in range(await btns.count())]
    k = rank(texts, prefs, label)
    if k is None: return None, texts
    b = btns.nth(k)
    async def on():
        return (await b.get_attribute("aria-checked")) == "true" or (await b.get_attribute("aria-pressed")) == "true" or bool(re.search(r"selected|active|checked", await b.get_attribute("class") or ""))
    if not await on():
        await b.scroll_into_view_if_needed(timeout=3000); await b.click(timeout=3000); await page.wait_for_timeout(500)
    return (texts[k] if await on() else None), texts

async def set_checkbox(page, row, idx, want=True, kind="checkbox"):
    cb = row.locator(f'input[type="{kind}"]').nth(idx)
    try:
        if await cb.is_checked() == want: return True
        cid = await cb.get_attribute("id")
        targets = []
        if cid: targets += [row.locator(f'label[for="{cid}"] [class*="__button"]'), row.locator(f'label[for="{cid}"]')]
        targets += [cb.locator("xpath=following-sibling::*[1]//*[contains(@class,'__button')]"),
                    cb.locator("xpath=following-sibling::*[contains(@class,'__button')]"),
                    cb.locator("xpath=following-sibling::label[1]"),
                    cb.locator("xpath=ancestor::label[1]//*[contains(@class,'__button')]"),
                    cb.locator("xpath=ancestor::label[1]")]
        for t in targets:
            try:
                if await t.count():
                    await t.first.scroll_into_view_if_needed(timeout=2000); await t.first.click(timeout=3000); await page.wait_for_timeout(300)
                    if await cb.is_checked() == want: return True
            except Exception: pass
        await cb.evaluate("(e)=>e.click()"); await page.wait_for_timeout(300)
        return await cb.is_checked() == want
    except Exception:
        return False

class Job:
    def __init__(self, item):
        self.item = item; self.tag = item["tag"]; self.url = item["url"]; self.title = item.get("title", "")
        self.report = {"tag": self.tag, "ats": ATS, "url": self.url, "submitted": False, "result": "", "unanswered": [], "errors": [], "answers": {}}
        self.opts_seen = {}   # label -> options read from a list that had no rule
    def ans(self, label, val): self.report["answers"][(label or "")[:140]] = val
    def miss(self, f, why=None):
        u = {"label": (f.get("label") or f.get("block") or "?")[:300], "type": f.get("kind")}
        if f.get("opts"): u["options"] = f["opts"][:25]
        elif self.opts_seen.get(u["label"]): u["options"] = self.opts_seen[u["label"]][:25]
        if why: u["why"] = why
        if not any(x["label"] == u["label"] for x in self.report["unanswered"]): self.report["unanswered"].append(u)

def contact_value(f):
    """The fixed contact / address / signature fields, by label (None: not one of them)."""
    low = (f["label"] or "").lower().strip()
    if re.search(r"(postal|zip) code extension|zip ?\+ ?4|plus ?4|^\+4$|preferred middle name|middle initial|pronunciation|phonetic|maiden name|former (last )?name|other names?", low): return ""
    if re.fullmatch(r"(legal |preferred )?last name|family name|surname", low): return LAST
    if re.fullmatch(r"(legal )?first name|given name", low): return FIRST
    if re.fullmatch(r"preferred (first )?name|known as|nickname|preferred name", low): return text_for(f["label"]) or FIRST
    if re.fullmatch(r"middle name|suffix|name suffix|title|prefix|honorific|address ?(line ?)?[2-9]|second last name|previous last name", low): return ""   # optional: left empty ('Address2' / 'Address3' too: a TEXT_RULES 'address' rule would put the city there)
    if re.fullmatch(r"e-?mail( address)?", low): return P["email"]
    if re.fullmatch(r"address line 1|street( address)?|address|street (number and )?name( or p\.?o\.? box)?|street number and name|address 1", low): return P.get("street") or ""
    if re.fullmatch(r"(zip|postal)( code)?|zip/postal code", low): return P.get("zip") or ""
    if re.fullmatch(r"city|town|city/town", low): return P.get("city") or "Santa Clara"
    if re.fullmatch(r"county", low): return "Santa Clara"
    if re.fullmatch(r"state|state/province|province|region", low): return "California"
    if re.fullmatch(r"country|country/region|country of residence", low): return "United States"
    if re.fullmatch(r"full name|legal full name|signature|e-?signature|your (full )?name", low): return P["name"]
    if re.fullmatch(r"link [2-9]\d*", low): return ""   # one link is enough: the LinkedIn profile goes in Link 1
    if re.search(r"linkedin", low) or re.fullmatch(r"link 1|link|url|website|web site", low): return P["linkedin"]
    return None

async def answer_field(page, job, f):
    """Answer one CE field. Returns the answer, '' when deliberately left empty, or None when it stays unanswered."""
    row = page.locator(ROW(f["i"])).first
    label, kind, cur, low = f["label"] or "", f["kind"], f["val"] or "", (f["label"] or "").lower()
    q = (label + " " + (f.get("hint") or "")).strip()
    key = label or f["block"]
    def keep(v): job.ans(key, v); return v
    if kind in ("readonly",): return keep(cur) if cur else ""
    # AI-use / "I personally completed this application" certifications: always the applicant's (never ticked or typed)
    if (AI_CERT.search(q) and not AI_CONSENT.search(q)) or AI_CERT_STRONG.search(q) or EMPLOYER_REL.search(q):
        job.report.setdefault("left_for_applicant", []).append(key[:200])
        if cur:   # a value from an earlier run or the site's draft: never vouched for by the filler
            job.miss(f, why=f"left for the applicant; the form already shows {cur[:80]!r} (from a draft or earlier run): check it")
        return None
    # ---- a per-item "answers" override from the queue file ({"label substring": answer}): the applicant's own answer to
    # a question the rules leave open (never used for the AI-use certifications above)
    ov = next((v for k, v in (job.item.get("answers") or {}).items() if k and k.lower() in q.lower()), None)
    if ov is not None:
        ovl = [ov] if isinstance(ov, str) else [str(x) for x in ov]
        v = None
        if kind in ("text", "textarea"):
            v = ovl[0] if (cur and norm(cur) == norm(ovl[0])) or await fill_text(page, row.locator("textarea.input-row__control:not(.input-row__control--helper), input").first, ovl[0]) else None
        elif kind == "pills": v, _ = await pills_choose(page, row, ovl, label)
        elif kind == "select": v, _ = await cx_choose(page, row, ovl, label, queries=ovl[:1])
        elif kind == "radio":
            k = rank(f["opts"], ovl, label)
            if k is not None and await set_checkbox(page, row, k, True, kind="radio"): v = f["opts"][k]
        elif kind == "checkbox":
            if f["multi"]:
                k = rank(f["opts"], ovl, label)
                if k is not None and await set_checkbox(page, row, k, True): v = f["opts"][k]
            elif re.match(r"\s*(yes|true|checked?|i agree|agree|i acknowledge)", ovl[0], re.I) and await set_checkbox(page, row, 0, True): v = "checked"
        if v: job.report.setdefault("overrides_used", []).append(key[:120]); return keep(v)
        job.report["errors"].append(f"override matched no option: {key[:80]}")
        return None
    # ---- contact, address, e-signature
    cv = contact_value(f)
    if cv is not None and kind != "checkbox":
        if cv == "" and cur and kind in ("text", "textarea") and re.fullmatch(r"address ?(line ?)?[2-9]", low.strip()) and re.search(r"santa clara,? (ca|california)\b", cur, re.I):
            # an earlier version put the city line into Address2 / Address3 of the draft: clear it
            await fill_text(page, row.locator("input.input-row__control, input").first, "")   # returns False for an empty field: expected
            job.report.setdefault("cleared", []).append(key[:120]); return ""
        if cv == "": return ""
        if kind == "phone": pass
        elif kind in ("text", "textarea"):
            if cur and norm(cur) == norm(cv): return keep(cur)
            loc = row.locator("input.input-row__control, textarea.input-row__control:not(.input-row__control--helper), input").first
            return keep(cv) if await fill_text(page, loc, cv) else None
        elif kind == "autosuggest":   # Address Line 1 (Oracle Maps suggestions): type the street, pick a matching suggestion if one appears
            if cur and norm(cv) and norm(cur).startswith(norm(cv)[:8]): return keep(cur)
            inp = row.locator("input.cx-select-input").first
            await inp.scroll_into_view_if_needed(timeout=3000); await inp.click(timeout=3000); await inp.fill(""); await inp.type(cv, delay=40)
            await page.wait_for_timeout(2000)
            cells, texts = await cx_options(page, inp)
            k = next((i for i, t in enumerate(texts) if norm(cv)[:10] in norm(t) and (re.search(r"santa clara|\bca\b|california", t, re.I) or (P.get("zip") and P["zip"] in t))), None)
            if k is not None:
                await cells.nth(k).click(timeout=4000); await page.wait_for_timeout(1500)
            else:
                await page.keyboard.press("Escape"); await inp.press("Tab"); await page.wait_for_timeout(500)
            got = (await inp.input_value()).strip()
            return keep(got) if got else None
        elif kind == "select":
            if low.startswith("zip") or low.startswith("postal"):
                if cur and norm(cv) in norm(cur): return keep(cur)
                v, seen = await cx_choose(page, row, [cv], label, queries=[cv], ranker=lambda t: next((i for i, x in enumerate(t) if norm(x).startswith(norm(cv)) and re.search(r"santa clara", x, re.I)), next((i for i, x in enumerate(t) if norm(x).startswith(norm(cv))), None)))
                return keep(v) if v else None
            if low == "state" or low.startswith("state/") or low in ("province", "region"):
                if cur and re.fullmatch(r"(ca|california)", cur.strip(), re.I): return keep(cur)
                v, seen = await cx_choose(page, row, ["California", "CA"], label, queries=["Calif", "CA"], ranker=lambda t: next((i for i, x in enumerate(t) if re.fullmatch(r"(ca|california)(,.*)?", x.strip(), re.I)), None))
                return keep(v) if v else None
            if low.startswith("country"):
                if cur and re.search(r"united states", cur, re.I): return keep(cur)
                v, seen = await cx_choose(page, row, ["United States", "United States of America", "USA"], label, queries=["United States"])
                return keep(v) if v else None
            if low in ("city", "town", "city/town", "county"):
                if cur and re.fullmatch(r"\s*santa clara( county)?\s*(,.*)?", cur, re.I): return keep(cur)
                def _city(t):
                    for test in (lambda x: norm(x) == "santaclara",
                                 lambda x: re.match(r"santa clara\s*(,|$)", x, re.I) and (low == "county" or re.search(r"\bca\b|california", x, re.I)),
                                 lambda x: re.match(r"santa clara\s*(,|$)", x, re.I),
                                 lambda x: re.match(r"santa clara\b", x, re.I)):
                        k = next((i for i, x in enumerate(t) if x and test(x)), None)
                        if k is not None: return k
                    return None
                v, seen = await cx_choose(page, row, [cv], label, queries=[cv], ranker=_city)
                return keep(v) if v else None
            v, seen = await cx_choose(page, row, [cv], label, queries=[cv])
            return keep(v) if v else None
    if kind == "phone":
        digits = re.sub(r"\D", "", P["phone"])[-10:]
        pf = row.locator("input.cx-select-input").first
        try:
            pv = (await pf.input_value()).strip()
            if not re.search(r"\+1\b|united states", pv, re.I):
                await cx_choose(page, row, ["+1 (United States)"], "phone country code", queries=["United States"], ranker=lambda t: next((i for i, x in enumerate(t) if re.search(r"\+1\b.*united states|united states.*\+1\b", x, re.I)), None))
        except Exception: pass
        tel = row.locator('input[type="tel"]').first
        if norm(cur)[-10:] == digits: return keep(cur)
        return keep(digits) if await fill_text(page, tel, digits) else None
    # ---- EEO / voluntary self-identification
    if kind == "radio" and RACE_Q.search(q):
        decl = [i for i, t in enumerate(f["opts"]) if re.search(r"wish|decline|prefer not|not to (say|answer|disclose|identify)|choose not", t, re.I)]
        if decl and await set_checkbox(page, row, decl[0], True, kind="radio"): return keep(f["opts"][decl[0]])
    if kind == "checkbox" and f["multi"] and RACE_Q.search(q):
        prefs = choice_for(label) or []
        decl = [i for i, t in enumerate(f["opts"]) if re.search(r"wish|decline|prefer not|not to (say|answer|disclose)|choose not", t, re.I)]
        if decl:
            return keep(f["opts"][decl[0]]) if await set_checkbox(page, row, decl[0], True) else None
        if not f["req"]: return keep("(declined: left blank)")   # voluntary: declining = no box ticked
        k = rank(f["opts"], prefs, label)
        if k is not None and await set_checkbox(page, row, k, True): return keep(f["opts"][k])
        return None
    if kind == "checkbox" and not f["multi"] and re.fullmatch(r"(ethnicity|hispanic or latino)", low.strip()) and re.search(r"hispanic", " ".join(f["opts"]), re.I):
        return keep("(not Hispanic or Latino: left blank)")   # a lone 'Hispanic or Latino' box: unticked is the true answer
    # ---- single checkbox: an acknowledgement / consent is ticked; a disclosure, marketing or alerts opt-in never is
    if kind == "checkbox" and not f["multi"]:
        t = f["opts"][0] if f["opts"] else label
        if MARKETING.search(t) and not f["req"]:
            if cur and await set_checkbox(page, row, 0, False):   # ticked in the draft (an earlier run): untick it
                job.report.setdefault("cleared", []).append(key[:120])
            return ""
        if DISC.search(t): return None if f["req"] else ""
        if ACK.search(t) or ACK.search(label) or AI_CONSENT.search(t):
            if await set_checkbox(page, row, 0, True): return keep("checked: " + t[:80])
            return None
        if not f["req"]: return ""
        prefs = choice_for(t)
        if prefs and re.match(r"\s*(yes|i agree|agree|i acknowledge|i consent|accept)", prefs[0], re.I):
            if await set_checkbox(page, row, 0, True): return keep("checked: " + t[:80])
        return None
    # ---- choice questions (pills / select / radio / checkbox group)
    if kind in ("pills", "select", "radio", "checkbox", "nselect"):
        prefs = choice_for(q) if not choice_for(label) else choice_for(label)
        ack = [o for o in (f.get("opts") or []) if ACK_OPT.search(o) and not NEG_OPT.search(o)]
        if ACK_ASK.search(q) and len(ack) == 1 and not DISC.search(q):
            prefs = ack   # 'Please acknowledge this ...': the acknowledgement (never 'I decline to acknowledge')
        elif SALARY_SHARE.search(q) and any(re.fullmatch(r"\s*yes\s*", o, re.I) for o in f.get("opts") or []):
            prefs = ["Yes", "yes"]   # the rules give a salary range ($220K-$350K): it is shared
        if OTHER_PERSON_Q.search(q):
            opts = f.get("opts") or []
            if kind == "select":   # read the list: a decline option is the answer
                try:
                    inp = row.locator("input.cx-select-input").first
                    await inp.click(timeout=3000); await page.wait_for_timeout(900)
                    _, opts = await cx_options(page, inp); await page.keyboard.press("Escape")
                except Exception: opts = []
            decl = [o for o in opts if re.search(r"wish|decline|prefer not|not to (say|answer|disclose)|choose not|don.t know|do not know|unknown", o, re.I)]
            prefs = decl[:1] or None
            if not prefs and kind == "select" and cur:   # no decline option: clear a value an earlier run or the draft put there
                try:
                    await row.locator("button.icon-clear").first.click(timeout=3000); await page.wait_for_timeout(500)
                    job.report.setdefault("cleared", []).append(key[:120]); cur = ""
                except Exception: pass
            if not prefs:
                job.report.setdefault("left_for_applicant", []).append(key[:200])
                if cur: job.miss(f, why=f"about another person; the form already shows {cur[:60]!r}: check it")
                return None
        if not prefs and len(low) < 90 and re.search(r"\bjob ?boards?\b|\bjob (site|website)s?\b|(which|what|name of the|specify( the)?) (website|site|social (media|network)|online source|source)|^(source|referral source)( name)?\??$", low) and not re.search(r"\b(yes|no)\b", " ".join(f.get("opts") or []), re.I):
            prefs = choice_for("How did you hear about this position?")   # the follow-up to 'How did you hear ...? Job Board': LinkedIn
        if prefs == ["__ASK__"]:
            job.report.setdefault("left_for_applicant", []).append(key[:200]); return None
        if prefs is None and kind != "checkbox":
            t = text_for(label)   # a Yes/No rule written for free text ('No', 'Yes. I am a US citizen ...') also answers the choice
            if t and re.match(r"\s*(yes|no)\b", t, re.I): prefs = [re.match(r"\s*(yes|no)\b", t, re.I).group(1).capitalize()]
        if not prefs and ack and ACK_TOPIC.search(q) and not DISC.search(q) and len(ack) == 1:
            prefs = ack; job.report.setdefault("consent_fallback", []).append(key[:120])
        if not prefs and CONSENT_Q.search(q) and not DISC.search(q) and not MARKETING.search(q):
            prefs = ["Yes", "I agree", "I consent", "I acknowledge", "Agree", "Accept", "I accept"]   # consent / acknowledgement: Yes
            job.report.setdefault("consent_fallback", []).append(key[:120])
        if not prefs:
            if kind == "select" and not cur:   # read the list (nothing is chosen) so a rule can be written
                try:
                    inp = row.locator("input.cx-select-input").first
                    await inp.click(timeout=3000); await page.wait_for_timeout(1200)
                    _, texts = await cx_options(page, inp)
                    if not texts:   # some lists open only from the arrow button
                        await row.locator("button.icon-dropdown-arrow").first.click(timeout=3000); await page.wait_for_timeout(1500)
                        _, texts = await cx_options(page, inp)
                    await page.keyboard.press("Escape")
                    if texts: job.opts_seen[key[:300]] = texts[:30]
                    else: job.report.setdefault("errors", []).append(f"could not read the options of {key[:60]!r}")
                except Exception: pass
            return keep(cur) if cur else None
        if (VISA_STATUS_Q.search(q) and re.match(r"\s*yes", prefs[0], re.I)) or (COMMUTE_Q.search(q) and re.match(r"\s*no\b", prefs[0], re.I)) or \
           (FIVE_DAYS_Q.search(q) and isinstance(prefs[0], str) and re.match(r"\s*yes", prefs[0], re.I) and not BAY.search(str(job.item.get("where") or "") + " " + str(job.item.get("loc") or ""))):
            job.report.setdefault("rule_conflicts", []).append(f"{key[:150]} -> rule says {prefs[0]!r}; left unanswered"); return None
        if cur and rank([x.strip() for x in cur.split(";")][:1], prefs[:1], label) is not None: return keep(cur)
        if kind == "pills":
            v, texts = await pills_choose(page, row, prefs, label, f["multi"])
        elif kind == "select":
            v, texts = await cx_choose(page, row, prefs, label, queries=[p for p in prefs[:2] if isinstance(p, str) and len(p) > 2])
            if not v:
                if not texts:   # read the full list without typing, for the report
                    try:
                        inp = row.locator("input.cx-select-input").first
                        await inp.click(timeout=3000); await inp.fill(""); await page.wait_for_timeout(1200)
                        _, texts = await cx_options(page, inp); await page.keyboard.press("Escape")
                    except Exception: pass
                if texts: job.opts_seen[key[:300]] = texts[:30]
                job.report.setdefault("no_matching_option", []).append({"label": key[:150], "rule": [str(x) for x in prefs[:6]]})
        elif kind == "radio":
            k = rank(f["opts"], prefs, label); v = None
            if k is not None and await set_checkbox(page, row, k, True, kind="radio"): v = f["opts"][k]
        elif kind == "nselect":
            k = rank(f["opts"], prefs, label); v = None
            if k is not None:
                try: await row.locator("select").first.select_option(index=k); v = f["opts"][k]
                except Exception: pass
        else:   # checkbox group (not race): tick every option the rules name, in order of preference, at least one
            v = None; ticked = []
            for p in prefs:
                k = rank(f["opts"], [p], label)
                if k is not None and f["opts"][k] not in ticked and await set_checkbox(page, row, k, True):
                    ticked.append(f["opts"][k])
                    if not re.search(r"select all|check all|all that apply", q, re.I): break
            v = "; ".join(ticked) or None
        if not v and len(ack) == 1 and ACK_TOPIC.search(q) and not DISC.search(q) and isinstance(prefs[0], str) and re.match(r"\s*(yes|i agree|agree|i consent|i acknowledge|accept|i understand|opt in)", prefs[0], re.I) and ack[0] not in prefs:
            job.report.setdefault("consent_fallback", []).append(key[:120])
            return await answer_choice_retry(page, job, f, row, ack, label, key)
        return keep(v) if v else None
    # ---- free text
    if kind in ("text", "textarea", "date"):
        if kind == "date": return keep(cur) if cur else None
        numeric = bool(re.match(r"number\||[^|]*\|(numeric|decimal)\|", f.get("itype") or "")) or bool(re.search(r"numeric|number only|numbers only|digits only|whole number", q, re.I))
        v = text_for(label) or (text_for(q) if q != label else None)
        if v is None:
            c = choice_for(label) or choice_for(q)
            if c and c != ["__ASK__"] and isinstance(c[0], str) and re.fullmatch(r"(yes|no|none|n/a)", c[0].strip(), re.I): v = c[0]
        if v is None and f["req"] and not cur:
            v = tech_answer(label)
            if v: job.report.setdefault("tech_fallback", []).append(key[:120])
        if v and numeric:
            if re.search(r"salary|compensation|pay|remuneration|\bbase\b|\bote\b", q, re.I) and SALARY_NUM: v = SALARY_NUM
            else:
                m = re.search(r"\d[\d,]*(\.\d+)?", v); v = m.group(0).replace(",", "") if m else None
        if not v: return keep(cur) if cur else None
        if cur and norm(cur) == norm(v): return keep(cur)
        loc = row.locator("textarea.input-row__control:not(.input-row__control--helper), oj-text-area textarea, input.input-row__control, input").first
        return keep(v) if await fill_text(page, loc, v) else None
    return keep(cur) if cur else None

async def answer_choice_retry(page, job, f, row, prefs, label, key):
    kind = f["kind"]; v = None
    if kind == "pills": v, _ = await pills_choose(page, row, prefs, label)
    elif kind == "select": v, _ = await cx_choose(page, row, prefs, label, queries=prefs[:1])
    elif kind == "radio":
        k = rank(f["opts"], prefs, label)
        if k is not None and await set_checkbox(page, row, k, True, kind="radio"): v = f["opts"][k]
    if v: job.ans(key, v)
    return v

async def fields(page):
    try: return await page.evaluate(FIELDS_JS)
    except Exception: return []

async def fill_all(page, job):
    """Answer every visible field; answers can reveal follow-up questions (and ZIP fills City/State), so re-read the
    fields until nothing new appears. Returns the fields that are still required and empty."""
    tried = {}
    for rnd in range(4):
        fs = await fields(page)
        todo = [f for f in fs if (f["label"], f["block"], f["kind"]) not in tried]
        if not todo: break
        for f in todo:
            k = (f["label"], f["block"], f["kind"])
            if f["kind"] == "unknown": continue   # not rendered yet (a dependent list still loading): read again next round
            try: v = await answer_field(page, job, f)
            except Exception as e:
                v = None; job.report["errors"].append(f"{(f['label'] or f['block'])[:60]}: {type(e).__name__}: {str(e)[:80]}")
            tried[k] = v
        await page.wait_for_timeout(800)
    # what is still required and empty (re-read: dependent lists may have filled themselves)
    missing = []
    for f in await fields(page):
        if f["req"] and not f["val"] and f["kind"] not in ("readonly",):
            missing.append(f)
            if f["kind"] == "unknown": job.report.setdefault("debug", []).append({"label": f["label"], "block": f["block"], "html": f["html"][:400]})
    return missing

async def profile_items_review(page, job):
    """Items the site's resume parser added (Experience / Education / Skills tiles): listed in the report so the
    applicant can see them; an item the parser could not name ('Unnamed Job Title') is flagged for review."""
    try:
        items = await page.evaluate(r"""()=>[...document.querySelectorAll('apply-flow-block')].filter(b=>/tile-profile-items|work-and-education|skill|profile-items/.test(((b.querySelector('.apply-flow-block')||{}).className||'')))
          .map(b=>({block:((b.querySelector('.apply-flow-block__title')||{}).innerText||'').trim(), n:b.querySelectorAll('button[aria-label*="Remove" i], button[title*="Remove" i], [class*="tile"] [class*="remove"], [class*="pill"] button, .profile-item-tile').length,
                    text:(b.innerText||'').replace(/\s+/g,' ').slice(0,1500)}))""")
        job.report["profile_items"] = [{"block": x["block"], "text": x["text"][:600]} for x in items if x["text"]]
        for x in items:
            note = f"{x['block']}: the site's resume parser added an item without a name (check before submitting)"
            if re.search(r"unnamed|untitled", x["text"], re.I) and note not in job.report.setdefault("review_notes", []):
                job.report["review_notes"].append(note)
    except Exception: pass

async def upload_resume(page, job):
    """The resume goes into the 'Upload Resume' file input (Supporting Documents); the cover letter only when required."""
    path = resume_for(job.item)
    stem = os.path.splitext(os.path.basename(path))[0]
    if stem.lower() in (await page.content()).lower():   # attached already (a draft from an earlier run)
        job.ans("Resume", os.path.basename(path) + " (already attached)"); return True
    fin = page.locator('input[type="file"]')
    n = await fin.count(); done = False
    for i in range(n):
        el = fin.nth(i)
        lab = await el.evaluate("(e)=>{const l=e.id&&document.querySelector('label[for=\"'+CSS.escape(e.id)+'\"]'); const box=e.closest('resume-upload-button, cover-letter-upload-button, .attachment-upload-button, .file-upload-wrapper__section, apply-flow-block'); return ((l?l.innerText:'')+' | '+(box?box.tagName+' '+(box.innerText||'').slice(0,120):'')).replace(/\\s+/g,' ')}")
        if re.search(r"cover letter", lab, re.I) and not re.search(r"resume|cv\b", lab.split("|")[0], re.I): continue
        if re.search(r"resume|cv\b|RESUME-UPLOAD", lab, re.I) or (n == 1):
            if os.path.basename(path).lower() in (await text(page)).lower(): done = True; break
            await el.set_input_files(path); done = True
            for _ in range(30):
                await page.wait_for_timeout(1000)
                if os.path.basename(path).lower() in (await text(page)).lower() or os.path.splitext(os.path.basename(path))[0].lower() in (await text(page)).lower(): break
            break
    if done:
        job.ans("Resume", os.path.basename(path))
        stem = os.path.splitext(os.path.basename(path))[0]
        for _ in range(10):   # the file name shows in the upload tile (text, or the Remove button's aria-label / title)
            if stem.lower() in (await page.content()).lower(): break
            await page.wait_for_timeout(1000)
        else:
            job.report["errors"].append("resume upload not confirmed on the page")
            job.report["unanswered"].append({"label": "Resume upload (not confirmed on the page)", "type": "file"})
    else:
        job.report["unanswered"].append({"label": "Resume upload (no resume file input found)", "type": "file"})
    return done

async def cover_letter_if_required(page, job):
    req = await page.evaluate(r"""()=>{const b=document.querySelector('cover-letter-upload-button'); if(!b) return false; return !!b.querySelector('.attachment-upload-button__drag-and-drop-label--required, [aria-required="true"]');}""")
    if not req: return
    cl = P.get("cover_letter")
    if not cl or not os.path.exists(cl):
        job.report["unanswered"].append({"label": "Cover Letter (required upload)", "type": "file"}); return
    el = page.locator('cover-letter-upload-button input[type="file"]').first
    try:
        await el.set_input_files(cl); await page.wait_for_timeout(4000); job.ans("Cover Letter", os.path.basename(cl))
    except Exception as e: job.report["errors"].append(f"cover letter upload: {type(e).__name__}")

async def required_blocks(page):
    """Profile-item blocks marked required (Experience / Education / Skills / Licenses) and how many items they hold."""
    # only the blocks of the page on screen: a multi-page flow keeps later pages' blocks in the DOM, hidden (their tiles then
    # count 0 and 'Add Education' cannot be clicked)
    return await page.evaluate(r"""()=>[...document.querySelectorAll('apply-flow-block')].map(b=>{
      const t=b.querySelector('.apply-flow-block__title'); const c=((b.querySelector('.apply-flow-block')||{}).className||'').match(/apply-flow-block--([a-z0-9-]+)/);
      const vis=!!(t&&(t.offsetParent||t.getClientRects().length));
      return {title:t?t.innerText.replace(/\s+/g,' ').trim():'', req:vis&&!!(t&&t.classList.contains('apply-flow-block__title--required')), comp:c?c[1]:'',
              invalid:vis?[...b.querySelectorAll('article.apply-flow-profile-item-tile--invalid')].filter(e=>e.offsetParent||e.getClientRects().length).map(e=>e.innerText.replace(/\s+/g,' ').trim().slice(0,140)):[],
              items:[...b.querySelectorAll('article.apply-flow-profile-item-tile, [class*="timeline__item"], .skill-pill, [class*="cx-select-pill"]')].filter(e=>e.offsetParent).length,
              text:(b.innerText||'').replace(/\s+/g,' ').slice(0,300)};}).filter(x=>x.req||x.invalid.length)""")

# ---- profile items (Experience / Education) for a required block the site's resume parser left empty. Values come from
# apply.py's rules: current employer and title, start year (start month: January, as in apply_workday.py), the degree,
# school and field of study, and EDU_START / EDU_END. Nothing else is entered.
_DEG_TXT = text_for("Degree") or ""
FIELD_OF_STUDY = _DEG_TXT.split(",", 1)[1].strip() if "," in _DEG_TXT else ""
WORK_ENTRY = {"employer": text_for("What is your current employer?") or P.get("org") or "", "title": text_for("title of your current position") or "",
              "start": ("January", (text_for("start year") or "").strip())}
SCHOOL = (choice_for("School") or [""])[0]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

async def set_monthyear(page, row, month, year):
    ok = True
    for part, want in (("month", month), ("year", str(year))):
        inp = row.locator(f'.datepicker-row__input--{part} input.cx-select-input').first
        if not await inp.count(): continue
        mi = MONTHS.index(month) + 1 if part == "month" and month in MONTHS else None
        def rk(t, want=want, mi=mi):
            for i, x in enumerate(t):
                xs = x.strip().lower()
                if xs == want.lower() or (mi and (xs in (want[:3].lower(), str(mi), f"{mi:02d}"))): return i
            return None
        v, _ = await cx_choose(page, row, [want], part, queries=[want[:3] if part == "month" else want], ranker=rk, inp=inp)
        ok = ok and bool(v)
    return ok

def entry_value(kind, f):
    """(how, value) for a field of an Experience / Education entry; (None, None) = leave it empty."""
    low = (f["label"] or "").lower()
    if kind == "experience":
        if re.search(r"employer|company", low): return "text", WORK_ENTRY["employer"]
        if re.search(r"job title|^title$|position", low): return "text", WORK_ENTRY["title"]
        if re.search(r"start", low) and WORK_ENTRY["start"][1]: return "date", WORK_ENTRY["start"]
        if re.search(r"current|present|currently work", low): return "check", True
        if re.fullmatch(r"country", low): return "choice", ["United States", "United States of America"]
        if re.fullmatch(r"state|state/province", low): return "choice", ["California", "CA"]
        if re.fullmatch(r"city|town", low): return "text", P.get("city") or "Santa Clara"
        return None, None
    if re.search(r"degree|education level|qualification", low): return "choice", choice_for("Degree") or []
    if re.search(r"major|field of study|area of study|discipline|specialization", low):
        return ("text", FIELD_OF_STUDY) if f["kind"] in ("text", "textarea") else ("choice", [FIELD_OF_STUDY] + (choice_for("Major") or []))
    if re.search(r"school|institution|university|college", low): return ("text", SCHOOL) if f["kind"] in ("text", "textarea") else ("choice", choice_for("School") or [])
    if re.search(r"start|from", low): return "date", (EDU_START[1], EDU_START[0])
    if re.search(r"end|to\b|graduation|completion|completed", low) and f["kind"] in ("monthyear", "date", "select"): return "date", (EDU_END[1], EDU_END[0])
    if re.search(r"graduated|completed|degree (obtained|awarded)", low) and f["kind"] == "checkbox": return "check", True
    if re.fullmatch(r"country", low) and re.search(r"madras", SCHOOL, re.I): return "choice", ["India"]   # the University of Madras is in Chennai, India
    if re.fullmatch(r"city|town", low) and re.search(r"madras", SCHOOL, re.I): return "text", "Chennai"
    return None, None

async def add_profile_entry(page, job, title, kind):
    """Click 'Add Experience' / 'Add Education' in a required, empty block, fill the inline form, and save it."""
    blk = page.locator("apply-flow-block").filter(has=page.locator(".apply-flow-block__title", has_text=re.compile("^\\s*" + re.escape(title.strip()), re.I))).first
    add = blk.locator("button.apply-flow-profile-item-tile__new-tile").first
    if not await add.count(): return False
    await add.scroll_into_view_if_needed(timeout=3000); await add.click(timeout=4000); await page.wait_for_timeout(2000)
    filled = {}
    for _ in range(2):   # 'Current Job' can hide End Date: read the form twice
        for f in await fields(page):
            if (f["block"] or "").strip().lower() != title.strip().lower() or f["label"] in filled: continue
            how, v = entry_value(kind, f)
            row = page.locator(ROW(f["i"])).first; got = None
            try:
                if how == "text" and v and f["kind"] in ("text", "textarea"):
                    got = v if (norm(f["val"]) == norm(v) or await fill_text(page, row.locator("input, textarea").first, v)) else None
                elif how == "text" and v and f["kind"] == "select":
                    got, _ = await cx_choose(page, row, [v], f["label"], queries=[v])
                elif how == "choice" and v:
                    def strict(t, v=v):   # entries: an exact or leading match only ('Computer Science' never picks 'Applied Computer Science')
                        for pv in v:
                            k = next((i for i, x in enumerate(t) if x and (norm(x) == norm(pv) or _match(x, pv, True))), None)
                            if k is not None: return k
                        return None
                    if f["kind"] == "select":
                        got, seen = await cx_choose(page, row, v, f["label"], queries=[x for x in v[:2] if len(x) > 2] + ["Other"], ranker=strict)
                        if not got: job.report.setdefault("entry_options", {})[f"{title}/{f['label']}"] = seen[:40]
                    elif f["kind"] == "pills": got, _ = await pills_choose(page, row, v, f["label"])
                elif how == "date" and v:
                    if f["kind"] == "monthyear": got = f"{v[0]} {v[1]}" if await set_monthyear(page, row, v[0], v[1]) else None
                elif how == "check" and f["kind"] == "checkbox":
                    got = "checked" if await set_checkbox(page, row, 0, True) else None
            except Exception as e:
                job.report["errors"].append(f"{title} entry {f['label'][:40]}: {type(e).__name__}")
            filled[f["label"]] = got
        await page.wait_for_timeout(800)
    job.report.setdefault("entries_added", []).append({"block": title, "fields": filled})
    save = blk.get_by_role("button", name=re.compile(r"^(add|save|done)\b", re.I))
    for i in range(await save.count()):
        b = save.nth(i)
        if await b.is_visible() and "new-tile" not in (await b.get_attribute("class") or ""):
            await b.click(timeout=4000); await page.wait_for_timeout(2500); break
    n = await blk.locator("article.apply-flow-profile-item-tile:visible").count()
    if not n:
        errs = await blk.evaluate(r"""(b)=>[...b.querySelectorAll('.input-row--invalid')].filter(e=>e.offsetParent).map(e=>e.innerText.replace(/\s+/g,' ').trim().slice(0,120))""")
        job.report["errors"].append(f"{title}: entry not saved ({'; '.join(errs[:4])})")
        c = blk.get_by_role("button", name=re.compile(r"^cancel$", re.I))
        if await c.count(): await c.first.click(timeout=3000)
        return False
    return True

async def page_buttons(page):
    loc = page.locator(".apply-flow-pagination button:visible, .apply-flow-pagination__buttons button:visible")
    out = []
    for i in range(await loc.count()):
        try: out.append((re.sub(r"\s+", " ", await loc.nth(i).inner_text()).strip(), loc.nth(i)))
        except Exception: pass
    return out

async def verify_code(page, job):
    """'Confirm Your Identity': hand the one-time code request over (CODE REQUEST <tag>), wait for out/<tag>_code.txt."""
    tag = job.tag; req = f"{OUT}/{tag}_code_request.json"; ans = f"{OUT}/{tag}_code.txt"
    if os.path.exists(ans): os.remove(ans)
    json.dump({"tag": tag, "ats": ATS, "email": P["email"], "url": job.url, "company": job.item.get("company"), "ts": time.time(),
               "note": "Oracle Recruiting Cloud one-time verification code (subject usually 'Confirm your identity' / 'verification code')"}, open(req, "w"), indent=1)
    print(f"CODE REQUEST {tag}", flush=True)
    code, end = None, time.time() + CODE_WAIT
    while time.time() < end:
        if os.path.exists(ans):
            c = re.sub(r"[^A-Za-z0-9]", "", open(ans).read())
            if len(c) >= 4: code = c; break
        await asyncio.sleep(3)
    if not code: return False
    boxes = page.locator('input[autocomplete="one-time-code"]:visible, input[name*="pin" i]:visible, input[id*="pin" i]:visible, input[name*="code" i]:visible, input[id*="code" i]:visible')
    if not await boxes.count():
        boxes = page.locator('.apply-flow-dialog__form input:visible:not([name="honey-pot"]):not([type="checkbox"]), main input:visible:not([name="honey-pot"]):not([type="checkbox"]):not([type="email"])')
    n = await boxes.count()
    if not n: job.report["errors"].append("verification code input not found"); return False
    if n >= len(code) and n > 1:
        for i, ch in enumerate(code): await boxes.nth(i).fill(ch)
    else:
        await boxes.first.click(); await boxes.first.fill(""); await boxes.first.type(code, delay=60)
    job.report["code_entered"] = True
    for name in (r"^verify$", r"^(next|continue|submit code|confirm)$"):
        b = page.get_by_role("button", name=re.compile(name, re.I))
        if await b.count():
            await b.first.click(timeout=4000); break
    await page.wait_for_timeout(6000)
    return True

async def drop_unnamed_tiles(page, job):
    """Delete profile tiles the site flags as invalid AND whose title the resume parser left empty ('Unnamed Job Title',
    'Unnamed ...'): they are parser duplicates of entries the resume already holds. Any other invalid tile is left alone
    (reported as unanswered). Returns how many were removed."""
    removed = 0
    for _ in range(4):
        tiles = page.locator('article.apply-flow-profile-item-tile--invalid:visible')
        k = None
        for i in range(await tiles.count()):
            if re.search(r"\bunnamed\b", await tiles.nth(i).inner_text(), re.I): k = i; break
        if k is None: break
        t = tiles.nth(k)
        try:
            btn = t.locator('button[aria-label*="delete" i], button[aria-label*="remove" i], button[title*="delete" i], button[title*="remove" i], .apply-flow-profile-item-tile__remove, button:has-text("Delete"), button:has-text("Remove")')
            if not await btn.count():
                await t.hover(); btn = t.locator('button[aria-label*="delete" i], button[aria-label*="remove" i], button:has-text("Delete"), button:has-text("Remove")')
            if not await btn.count(): break
            await btn.first.click(timeout=4000); await page.wait_for_timeout(1000)
            ok = page.get_by_role("button", name=re.compile(r"^(yes|delete|remove|confirm|ok)$", re.I))
            if await ok.count(): await ok.last.click(timeout=4000); await page.wait_for_timeout(1500)
            removed += 1; job.report.setdefault("removed_tiles", []).append((await t.inner_text())[:120] if await t.count() else "unnamed tile")
        except Exception as e:
            job.report["errors"].append(f"removing an unnamed tile failed: {type(e).__name__}"); break
    return removed

async def save_state(ctx, page, sp, host):
    """The tenant's cookies + localStorage (storage_state) and sessionStorage, private files in out/orc_state."""
    try:
        await ctx.storage_state(path=sp); os.chmod(sp, 0o600)
        ss = json.loads(await page.evaluate("()=>JSON.stringify(Object.assign({}, sessionStorage))"))
        ssp = os.path.join(STATE_DIR, host + ".session.json")   # keyed by the job URL's host; 'h' is the host that serves the form (vanity redirects)
        json.dump({"h": urlparse(page.url).hostname or host, "s": ss}, open(ssp, "w")); os.chmod(ssp, 0o600)
        return sorted(ss.keys())
    except Exception:
        return []

def apply_url(url):
    """The CE email step for a job URL (/job/<id> -> /job/<id>/apply/email)."""
    m = re.match(r"(https?://[^?#]+?/job/\d+)", url)
    return (m.group(1) + "/apply/email") if m else url

async def at_end(page, job, item):
    """Last page: dry run stops here with a screenshot; --submit clicks Submit and waits for the site's confirmation."""
    shot = f"{OUT}/{job.tag}_{ATS}_dry.png"
    await page.screenshot(path=shot, full_page=True); job.report["screenshot"] = shot
    if os.environ.get("ORC_DUMP"):
        try: open(f"{OUT}/{job.tag}_{ATS}_form.html", "w").write((await page.content()).replace(P["email"], "<EMAIL>"))
        except Exception: pass
    is_submit = lambda t: bool(re.fullmatch(r"submit( application)?", t, re.I))
    if any(is_submit(t) for t, _ in await page_buttons(page)) and "Resume" not in job.report["answers"]:
        job.miss({"label": "Resume upload (no resume was attached on any page)", "kind": "file"})   # never submitted without the resume
    if job.report["unanswered"]:
        job.report["result"] = ("DRY RUN: " if not SUBMIT else "NOT SUBMITTED: ") + f"{len(job.report['unanswered'])} required field(s) unanswered"
        return
    if not SUBMIT:
        job.report["result"] = "DRY RUN: ready"; return
    btn = None
    for t, b in await page_buttons(page):
        if is_submit(t): btn = b
    if btn is None:
        job.report["result"] = "NOT SUBMITTED: no Submit button"; return
    CONFIRM = re.compile(r"thank you for (applying|your (job )?application|submitting)|application (was |has been )?(successfully )?(submitted|received)|we('ve| have) received your application|successfully applied|you applied for", re.I)
    job.report["submit_clicked"] = True
    await btn.click(timeout=5000)
    code_done = False
    for _ in range(45):
        await page.wait_for_timeout(1000)
        if await captcha_visible(page):
            job.report["result"] = "NOT SUBMITTED: captcha"; return
        body = await text(page)
        # some tenants (Ford) confirm the candidate's identity with an emailed code only after Submit
        if not code_done and re.search(r"confirm your identity|verification code|enter the code|one-time (code|pin|pass ?code)", body, re.I):
            code_done = True
            if not await verify_code(page, job):
                job.report["result"] = "NOT SUBMITTED: post-submit verification code not received (Submit was clicked: check the site before any retry)"; return
            continue
        # the site's own confirmation, and the form is gone (a form's fine print such as 'once your application has been
        # submitted ...' is not a confirmation while the Submit button is still there)
        if CONFIRM.search(body) and not any(is_submit(t) for t, _ in await page_buttons(page)):
            job.report["submitted"] = True; job.report["result"] = re.sub(r"\s+", " ", body)[:300]
            await page.screenshot(path=f"{OUT}/{job.tag}_{ATS}_submitted.png", full_page=True); return
    errs = await page.evaluate(r"""()=>[...document.querySelectorAll('.input-row--invalid, [class*="error-message"], .cx-notification, [role="alert"]')].filter(e=>e.offsetParent).map(e=>e.innerText.replace(/\s+/g,' ').trim()).filter(x=>x).slice(0,12)""")
    job.report["errors"] += errs
    await page.screenshot(path=f"{OUT}/{job.tag}_{ATS}_after_submit.png", full_page=True)
    job.report["result"] = "NOT SUBMITTED: no confirmation after Submit (Submit was clicked: check the site before any retry)"

async def run_one(br, item):
    job = Job(item); rp = f"{OUT}/{job.tag}_{ATS}_report.json"
    host = urlparse(job.url).hostname or "x"; sp = os.path.join(STATE_DIR, host + ".json")
    G["JOB_CHOICE_RULES"] = [(COMMUTE_Q.pattern, ["Yes", "yes"] if BAY.search(str(item.get("where") or "") + " " + str(item.get("loc") or "")) else ["No", "no"])]
    G["JOB_TEXT_RULES"] = []
    ctx = page = None
    try:
        if NEVER_APPLY.search(job.tag + " " + item.get("company", "") + " " + job.url):
            job.report["result"] = "NOT SUBMITTED: do-not-apply company"; return job.report
        _lb = location_block(item.get("company", ""), job.url, item.get("loc", ""), item.get("where", ""))
        if _lb:
            job.report["result"] = "NOT SUBMITTED: " + _lb; return job.report
        ctx = await br.new_context(ignore_https_errors=True, user_agent=UA, viewport={"width": 1280, "height": 1800}, locale="en-US", timezone_id="America/Los_Angeles",
                                   storage_state=sp if os.path.exists(sp) else None)
        ssp = os.path.join(STATE_DIR, host + ".session.json")
        if os.path.exists(ssp):   # the CE keeps the verified candidate's session in sessionStorage: restore it so a rerun continues the draft
            try:
                ss = json.load(open(ssp))
                if "s" not in ss: ss = {"h": host, "s": ss}
                await ctx.add_init_script("(d=>{try{if(location.hostname===d.h){for(const [k,v] of Object.entries(d.s)){if(sessionStorage.getItem(k)===null) sessionStorage.setItem(k,v);}}}catch(e){}})(" + json.dumps(ss) + ")")
            except Exception: pass
        page = await ctx.new_page()
        challenge = []
        async def onresp(r):
            if "recruitingCEVerificationTokens" in r.url and r.request.method == "POST":
                try: challenge.append(bool((await r.json()).get("ChallengeFlag")))
                except Exception: pass
        page.on("response", lambda r: asyncio.ensure_future(onresp(r)))
        await page.goto(apply_url(job.url), wait_until="domcontentloaded", timeout=60000)
        try: await page.wait_for_selector('input[name="primary-email"], apply-flow-block, .apply-flow-block', timeout=30000)
        except Exception: pass
        await page.wait_for_timeout(2000)
        if "/CandidateExperience/" not in page.url and not await page.locator('input[name="primary-email"], apply-flow-block, .apply-flow-block').count():
            job.report["result"] = f"NOT SUBMITTED: the tenant sends candidates to its own careers site ({urlparse(page.url).hostname}); not an Oracle CE form"
            job.report["redirect"] = page.url; return job.report
        body = await text(page)
        if re.search(r"no longer (available|accepting|open)|job (posting )?(is )?(closed|expired)|position has been filled|page (you are looking for )?(doesn.t|does not) exist|job not found", body, re.I) and not await page.locator('input[name="primary-email"]').count():
            job.report["result"] = "NOT SUBMITTED: job closed"; return job.report
        await dismiss_cookies(page)
        if await captcha_visible(page):
            job.report["result"] = "NOT SUBMITTED: captcha"; return job.report
        if re.search(r"already applied|you have applied|you.ve applied", body, re.I):
            job.report["result"] = "ALREADY APPLIED on this company's Oracle site"; return job.report
        # ---- email step
        if await page.locator('input[name="primary-email"]').count():
            em = page.locator('input[name="primary-email"]').first
            if not await em.is_visible():   # the phone variant is showing: switch back to email
                sw = page.get_by_role("button", name=re.compile(r"email instead", re.I))
                if await sw.count(): await sw.first.click(timeout=3000); await page.wait_for_timeout(800)
            await em.fill(P["email"])
            if await page.locator("#legal-disclaimer-checkbox").count():
                lc = page.locator("#legal-disclaimer-checkbox").first
                if not await lc.is_checked():
                    await page.locator("label[for='legal-disclaimer-checkbox'] .apply-flow-input-checkbox__button, .legal-disclaimer-container .apply-flow-input-checkbox__button").first.click(timeout=3000)
                if not await lc.is_checked(): await lc.evaluate("(e)=>e.click()")
                job.ans("I agree with the terms and conditions", "checked")
            if await captcha_visible(page):
                job.report["result"] = "NOT SUBMITTED: captcha"; return job.report
            await page.get_by_role("button", name=re.compile(r"^next$", re.I)).first.click(timeout=5000)
            for _ in range(30):
                await page.wait_for_timeout(1000)
                b = await text(page)
                if re.search(r"confirm your identity|verification code|enter the code|one-time (code|pin)", b, re.I) or await page.locator("apply-flow-block, .apply-flow-block").count():
                    break
            await page.wait_for_timeout(2000)
            if await captcha_visible(page):
                job.report["result"] = "NOT SUBMITTED: captcha"; return job.report
            b = await text(page)
            if re.search(r"confirm your identity|verification code|enter the code|one-time (code|pin)", b, re.I) and not await page.locator("apply-flow-block, .apply-flow-block").count():
                log(job.tag, "one-time code requested by the site")
                if not await verify_code(page, job):
                    job.report["result"] = "NOT SUBMITTED: email verification code not received"; return job.report
                for _ in range(20):
                    if await page.locator("apply-flow-block, .apply-flow-block").count(): break
                    await page.wait_for_timeout(1000)
                if not await page.locator("apply-flow-block, .apply-flow-block").count():
                    b = await text(page)
                    # an application submitted earlier but never identity-confirmed (Ford): the site offers REMOVE / CONFIRM
                    if re.search(r"do you want to confirm your job application", b, re.I):
                        cb = page.get_by_role("button", name=re.compile(r"^confirm$", re.I))
                        if await cb.count():
                            await cb.first.click(timeout=5000); job.report["submit_clicked"] = True
                            for _ in range(30):
                                await page.wait_for_timeout(1000)
                                b = await text(page)
                                if re.search(r"confirm your identity|verification code|enter the code|one-time (code|pin|pass ?code)", b, re.I) and not job.report.get("confirm_code"):
                                    job.report["confirm_code"] = True
                                    if not await verify_code(page, job):
                                        job.report["result"] = "NOT SUBMITTED: confirmation code not received (CONFIRM was clicked: check the site)"; return job.report
                                    continue
                                if re.search(r"thank you for (applying|your (job )?application)|application (was |has been )?(successfully )?(submitted|received|confirmed)|you applied for|we('ve| have) received your application", b, re.I) and not re.search(r"do you want to confirm", b, re.I):
                                    job.report["submitted"] = True; job.report["result"] = "CONFIRMED earlier application: " + re.sub(r"\s+", " ", b)[:250]
                                    await page.screenshot(path=f"{OUT}/{job.tag}_{ATS}_submitted.png", full_page=True); return job.report
                            await page.screenshot(path=f"{OUT}/{job.tag}_{ATS}_after_confirm.png", full_page=True)
                            job.report["errors"].append(re.sub(r"\s+", " ", b)[:300])
                            job.report["result"] = "NOT SUBMITTED: CONFIRM clicked but no confirmation seen (check the site before any retry)"; return job.report
                    job.report["errors"].append(re.sub(r"\s+", " ", b)[:300])
                    job.report["result"] = "NOT SUBMITTED: the verification code was not accepted"; return job.report
        await save_state(ctx, page, sp, host)
        job.report["challenge"] = any(challenge)
        if re.search(r"already applied|you have applied|you.ve applied", await text(page), re.I):
            job.report["result"] = "ALREADY APPLIED on this company's Oracle site"; return job.report
        if not await page.locator("apply-flow-block, .apply-flow-block").count():
            await page.screenshot(path=f"{OUT}/{job.tag}_{ATS}_error.png", full_page=True)
            job.report["result"] = "NOT SUBMITTED: the application form did not open"; job.report["errors"].append(re.sub(r"\s+", " ", await text(page))[:300]); return job.report
        await page.wait_for_timeout(2500)
        # ---- the form (one page, or pages joined by Next)
        for pg in range(8):
            await dismiss_cookies(page)
            if await captcha_visible(page):
                job.report["result"] = "NOT SUBMITTED: captcha"; return job.report
            if await page.locator('input[type="file"]').count() and "Resume" not in job.report["answers"]:
                await upload_resume(page, job)
                await cover_letter_if_required(page, job)
            missing = await fill_all(page, job)
            for f in missing: job.miss(f)
            await profile_items_review(page, job)
            if os.environ.get("ORC_DUMP"):
                try:
                    await page.screenshot(path=f"{OUT}/{job.tag}_{ATS}_p{pg + 1}.png", full_page=True)
                    open(f"{OUT}/{job.tag}_{ATS}_p{pg + 1}.html", "w").write((await page.content()).replace(P["email"], "<EMAIL>"))
                except Exception: pass
            if await drop_unnamed_tiles(page, job):   # the resume parser's untitled duplicates ('Unnamed Job Title ...') block Next / Submit
                await page.wait_for_timeout(1500)
            for blk in await required_blocks(page):
                for it in blk.get("invalid") or []:   # a tile the site flags ('Fields to fix'), e.g. one its resume parser added: Next / Submit would refuse it
                    job.miss({"label": f"{blk['title'].strip()}: item needs fixing ({it[:100]})", "kind": "section"})
                if not blk["req"] or blk["items"] or blk["comp"] not in ("tile-profile-items", "skill", "work-and-education-timeline", "profile-items"): continue
                kind = "experience" if re.search(r"experience|employment|work history", blk["title"], re.I) else "education" if re.search(r"education", blk["title"], re.I) else None
                try:
                    if kind and await add_profile_entry(page, job, blk["title"], kind): continue
                except Exception as e:
                    job.report["errors"].append(f"{blk['title'][:40]}: adding an entry failed: {type(e).__name__}: {str(e)[:80]}")
                job.report["unanswered"].append({"label": f"{blk['title'].strip()} (required section: add at least one entry)", "type": "section"})
            await page.wait_for_timeout(500)
            btns = await page_buttons(page)
            names = [t for t, _ in btns]
            log(job.tag, f"page {pg + 1}: buttons {names}; unanswered {len(job.report['unanswered'])}")
            if any(re.fullmatch(r"submit( application)?", t, re.I) for t in names) or not btns:
                await at_end(page, job, item); return job.report
            nxt = next((b for t, b in btns if re.fullmatch(r"next|continue|save and continue", t, re.I)), None)
            if nxt is None:
                await at_end(page, job, item); return job.report
            if job.report["unanswered"]:
                await at_end(page, job, item); return job.report
            before = re.sub(r"\s+", " ", await text(page))[:400]
            await nxt.click(timeout=5000); await page.wait_for_timeout(3500)
            if re.sub(r"\s+", " ", await text(page))[:400] == before:
                errs = await page.evaluate(r"""()=>[...document.querySelectorAll('.input-row--invalid')].filter(e=>e.offsetParent).map(e=>e.innerText.replace(/\s+/g,' ').trim().slice(0,160)).slice(0,10)""")
                if errs:
                    job.report["errors"] += errs
                    await at_end(page, job, item); job.report["result"] = "NOT SUBMITTED: the page did not advance (" + "; ".join(errs[:3])[:200] + ")"; return job.report
        job.report["result"] = "NOT SUBMITTED: too many pages"; return job.report
    except asyncio.CancelledError:   # the per-job timeout: the finally below still prints this item's one JSON line
        if not job.report["submitted"]:
            job.report["result"] = (f"NOT SUBMITTED: timed out after {JOB_TIMEOUT}s" + (" after Submit was clicked (check the site before any retry)" if job.report.get("submit_clicked") else ""))
            job.report["errors"].append("job timeout")
        raise
    except Exception as e:
        job.report["result"] = f"ERROR {type(e).__name__}: {str(e)[:200]}"
        try:
            if page: await page.screenshot(path=f"{OUT}/{job.tag}_{ATS}_exception.png", full_page=True)
        except Exception: pass
        return job.report
    finally:
        try:
            if ctx and page and job.report.get("answers"): job.report["state_keys"] = await save_state(ctx, page, sp, host)
        except Exception: pass
        json.dump(job.report, open(rp, "w"), indent=1)
        out = {k: job.report.get(k) for k in ("tag", "ats", "url", "submitted", "result", "unanswered", "errors")}
        out["errors"] = [str(e)[:300] for e in (out["errors"] or [])][:12]   # kept short, never cut mid-JSON
        print(json.dumps(out), flush=True); PRINTED.add(job.tag)
        try:
            if ctx: await ctx.close()
        except Exception: pass

async def main():
    q = json.load(open(sys.argv[1]))
    if isinstance(q, dict): q = q.get("jobs") or q.get("items") or []
    q = [x for x in q if (x.get("ats") or ATS) == ATS]
    async with async_playwright() as p:
        kw = dict(headless=not HEADED, args=["--no-sandbox"])
        if os.path.exists("/opt/pw-browsers/chromium"): kw["executable_path"] = "/opt/pw-browsers/chromium"
        br = await p.chromium.launch(**kw)
        for n, item in enumerate(q):
            if not item.get("tag") or not item.get("url"):   # malformed queue item: reported, the batch goes on
                print(json.dumps({"tag": item.get("tag"), "ats": ATS, "url": item.get("url"), "submitted": False, "result": "ERROR: queue item without tag or url", "unanswered": [], "errors": []}), flush=True); continue
            rp = f"{OUT}/{item['tag']}_{ATS}_report.json"
            if os.path.exists(rp):
                try:
                    if json.load(open(rp)).get("submitted"):
                        print(json.dumps({"tag": item["tag"], "ats": ATS, "url": item.get("url"), "submitted": True, "result": "ALREADY SUBMITTED earlier (skipped)", "unanswered": [], "errors": []}), flush=True); continue
                except Exception: pass
            try: await asyncio.wait_for(run_one(br, item), timeout=JOB_TIMEOUT)
            except asyncio.TimeoutError:   # run_one's finally has normally printed the line already: exactly one line per item
                if item.get("tag") not in PRINTED:
                    print(json.dumps({"tag": item.get("tag"), "ats": ATS, "url": item.get("url"), "submitted": False, "result": f"NOT SUBMITTED: timed out after {JOB_TIMEOUT}s", "unanswered": [], "errors": ["job timeout"]}), flush=True)
            except Exception as e:   # a malformed queue item (no tag / url): reported, the batch goes on
                if item.get("tag") not in PRINTED:
                    print(json.dumps({"tag": item.get("tag"), "ats": ATS, "url": item.get("url"), "submitted": False, "result": f"ERROR {type(e).__name__}: {str(e)[:200]}", "unanswered": [], "errors": [f"{type(e).__name__}"]}), flush=True)
            if n < len(q) - 1:
                g = random.uniform(*PACE); log("pace", f"waiting {int(g)}s before the next application"); await asyncio.sleep(g)
        await br.close()

if __name__ == "__main__":
    asyncio.run(main())
