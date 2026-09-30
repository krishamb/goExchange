"""Workday application filler (company career sites on *.myworkdayjobs.com / *.myworkdaysite.com).

usage: apply_workday.py <queue.json> [--submit] [--headed] [--pace MIN MAX]
  queue items: {"url", "tag", "title", "company"} (other keys are ignored)

Answers come from the same reviewed rule tables as apply.py (TEXT_RULES / CHOICE_RULES / tech_answer), so a fix there
applies here too. Every application stops at Workday's Review step and writes out/<tag>_wd_review.json (every question
and answer shown there) and out/<tag>_wd_review.png. Without --submit that is where it ends (dry run); with --submit it
is submitted only when out/<tag>_wd_approve.txt says OK. The Save and Continue click refuses any button that reads
Submit, so nothing else can submit. A required question with no rule is never guessed: the job is reported as NOT
SUBMITTED and left for the applicant. Captchas and bot checks are never bypassed: if one appears, the job is reported
and skipped.
Accounts: one Workday candidate account per company tenant. One sign-in attempt with the applicant's Workday login
(never retried: failed sign-ins can lock the account), then the account is created with the new-account email.
Passwords come from JOBS_DIR/wf_creds.json and are never printed or saved elsewhere. If a tenant asks to verify the
email, the filler writes out/<tag>_verify_request.json and waits for the link in out/<tag>_verify.txt."""
import asyncio, json, os, re, sys, time, random, secrets, string, datetime
from playwright.async_api import async_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.expanduser(os.environ.get("JOBS_DIR", "/tmp/claude-0/-home-user-goExchange/8d20ffb7-2488-5f8f-a666-35334b9e3ba6/scratchpad/f"))
OUT = os.path.join(JOBS_DIR, "out"); os.makedirs(OUT, exist_ok=True)
P = json.load(open(os.path.join(JOBS_DIR, "profile.json")))
ANS = json.load(open(os.path.join(JOBS_DIR, "answers.json"))) if os.path.exists(os.path.join(JOBS_DIR, "answers.json")) else {}
EXEC_RESUME = os.path.join(JOBS_DIR, "Ambarish_Krishnamurthy_Executive_Resume.pdf")
SUBMIT = "--submit" in sys.argv
HEADED = "--headed" in sys.argv
PACE = (float(sys.argv[sys.argv.index("--pace") + 1]), float(sys.argv[sys.argv.index("--pace") + 2])) if "--pace" in sys.argv else (60, 150)
REVIEW_WAIT = int(os.environ.get("WD_REVIEW_WAIT", "900"))
VERIFY_WAIT = int(os.environ.get("WD_VERIFY_WAIT", "600"))
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

# ---- the shared answer rules and matching helpers, taken from apply.py's source (apply.py runs its CLI at import time)
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
TEXT_RULES, CHOICE_RULES, pick, best_index, _match, mask_hear, NEVER_APPLY, tech_answer = (G[k] for k in ("TEXT_RULES", "CHOICE_RULES", "pick", "best_index", "_match", "mask_hear", "NEVER_APPLY", "tech_answer"))
HEAR_Q, HEAR_BAD, EDU_START, EDU_END = G["HEAR_Q"], G["HEAR_BAD"], G["EDU_START"], G["EDU_END"]
FIRST, LAST = G["first"], G["last"]

def resume_for(title):
    if title and os.path.exists(EXEC_RESUME) and re.search(r"\b(CTO|Chief|VP|SVP|Vice President|Head of|Director|Manager)\b", title, re.I) and not re.search(r"Architect", title, re.I):
        return EXEC_RESUME
    return P["resume"]

# ---- accounts
SECRET = os.path.join(JOBS_DIR, "wd_secret.json")
def secret():
    """The applicant's Workday logins (JOBS_DIR/wf_creds.json {"workday": {"email", "passwords": [...], "new_account_email",
    "new_account_password"}}): sign in with email + passwords[0]; new tenant accounts use new_account_email / password.
    Per-tenant state (which login worked) is kept in JOBS_DIR/wd_secret.json, outside the repository, without passwords."""
    s = json.load(open(SECRET)) if os.path.exists(SECRET) else {"tenants": {}}
    c = json.load(open(os.path.join(JOBS_DIR, "wf_creds.json"))).get("workday") if os.path.exists(os.path.join(JOBS_DIR, "wf_creds.json")) else None
    if c and c.get("email") and c.get("passwords"):
        s["email"], s["passwords"] = c["email"], list(c["passwords"])
        s["new_account_email"], s["new_account_password"] = c.get("new_account_email") or P["email"], c.get("new_account_password") or c["passwords"][0]
    else:
        s.setdefault("email", P["email"])
        s.setdefault("passwords", ["".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(14)) + "!7aZ"])
    s["password"] = s["passwords"][0]
    json.dump({k: v for k, v in s.items() if k not in ("password", "passwords", "new_account_password")}, open(SECRET, "w"), indent=1); os.chmod(SECRET, 0o600)
    return s
def save_secret(s): json.dump({k: v for k, v in s.items() if k not in ("password", "passwords", "new_account_password")}, open(SECRET, "w"), indent=1)
def tenant_of(url):
    m = re.match(r"https?://([^/]+)/(?:recruiting/)?([^/]+)/(?:en-US/)?([^/]+)", url)
    host = m.group(1) if m else url
    return host.split(".")[0] if "myworkdayjobs" in host else (m.group(2) if m else host)

# ---- page helpers
A = lambda i: f'[data-automation-id="{i}"]'
CAPTCHA = 'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="challenges.cloudflare"], [data-automation-id="captcha"], #px-captcha'
APPLIED = re.compile(r"already applied for this job|you.ve already applied", re.I)
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
def log(job, msg): print(f"[{job.tag}] {msg}", flush=True)
async def text(page):
    try: return await page.evaluate("()=>document.body.innerText")
    except Exception: return ""
async def click_button(page, auto_id=None, name=None, timeout=8000):
    """Workday buttons are often covered by a click_filter overlay: click the overlay when the button itself is blocked."""
    loc = page.locator(A(auto_id)) if auto_id else page.get_by_role("button", name=re.compile(name, re.I))
    try:
        await loc.first.wait_for(state="visible", timeout=timeout)
    except Exception:
        return False
    try:
        await loc.first.click(timeout=4000); return True
    except Exception:
        try:
            await loc.first.locator("xpath=..").locator(A("click_filter")).first.click(timeout=3000); return True
        except Exception:
            try: await loc.first.dispatch_event("click"); return True
            except Exception: return False
async def fill(page, loc, val):
    try:
        await loc.scroll_into_view_if_needed(timeout=3000); await loc.click(timeout=3000)
        await loc.fill(""); await loc.type(val, delay=15); await loc.press("Tab"); return True
    except Exception:
        return False
async def step_raw(page):
    """The progress bar's active step, e.g. 'current step 2 of 6 My Information' ('' while a step is loading)."""
    try: return re.sub(r"\s+", " ", await page.locator(A("progressBarActiveStep")).first.inner_text(timeout=2000)).strip()
    except Exception: return ""
async def active_step(page):
    return re.sub(r"^(current )?step \d+ of \d+\s*", "", await step_raw(page), flags=re.I).strip()
LOADING = f'{A("applyFlowLoadingPage")}:visible, {A("loadingIndicator")}:visible'
BUSY_JS = r"""()=>{const m=document.querySelector('[data-automation-id="applyFlowPage"]')||document.body; return /(^|\n)\s*Loading\s*(\n|$)/.test(m.innerText||'')}"""
SNAP_JS = r"""()=>{
  const t=document.body.innerText||'';
  if (/something went wrong|please refresh the page|already applied for this job|you.ve already applied/i.test(t)) return 'page:'+t.length;
  const r=document.querySelector('[data-automation-id="applyFlowReviewPage"]'); if (r) return 'review:'+r.innerText.length;
  const f=[...document.querySelectorAll('[data-automation-id^="formField-"]')].filter(e=>e.offsetParent);
  if (!f.length) return document.querySelector('[data-automation-id="signInContent"], [data-automation-id="jobPostingPage"]')? 'other':'';
  return f.map(e=>e.getAttribute('data-automation-id')+'='+[...e.querySelectorAll('input,textarea,button')].map(i=>i.value||i.innerText||'').join('|')+(e.querySelectorAll('[data-automation-id="selectedItem"]').length)).join(';');}"""
async def settle(page, secs=45):
    """Wait until the current step has rendered AND its saved values have arrived. After a sign-in or a reload Workday
    shows the progress bar first (no fields, no loading sign), then a loading page / 'Loading' placeholders, then the
    fields, and the draft's values a moment later (NVIDIA: Phone Device Type ~1 s after the rest). Filling earlier
    fills a blank form over the draft ('A phone number already exists for this application'). So: no loading sign,
    and the step's fields (or the review) unchanged over two polls."""
    end, last, stable = time.time() + secs, None, 0
    while time.time() < end:
        await page.wait_for_timeout(700)
        try:
            if await page.locator(LOADING).count() or await page.evaluate(BUSY_JS): last, stable = None, 0; continue
            snap = await page.evaluate(SNAP_JS)
            if not snap: last, stable = None, 0; continue
            stable = stable + 1 if snap == last else 0
            last = snap
            if stable >= 2: return True
        except Exception: pass
    return False
async def recover(page):
    """Workday's transient 'Something went wrong. Please refresh the page' error (seen when a draft resumes): reload, twice at most."""
    for _ in range(2):
        if not re.search(r"something went wrong|please refresh the page", await text(page), re.I): return True
        await page.reload(wait_until="domcontentloaded", timeout=60000); await page.wait_for_timeout(3000); await settle(page)
    return not re.search(r"something went wrong|please refresh the page", await text(page), re.I)
ERRORS = f'{A("errorHeading")}, {A("errorMessage")}, {A("inputAlert")}'
async def form_errors(page):
    """Workday's validation errors only: the 'Errors Found' banner (errorHeading) and field alerts (inputAlert /
    errorMessage). Toasts such as '<resume>.pdf successfully uploaded' (ariaLiveMessage, role=alert) are not errors."""
    out, loc = [], page.locator(ERRORS)
    for i in range(min(await loc.count(), 25)):
        try:
            e = loc.nth(i)
            if not await e.is_visible(): continue
            t = re.sub(r"\s+", " ", await e.inner_text()).strip()
        except Exception: continue
        if t and not re.match(r"warning", t, re.I) and t[:300] not in out: out.append(t[:300])
    return out
async def next_button(page):
    for aid in ("pageFooterNextButton", "bottom-navigation-next-button"):
        loc = page.locator(f'{A(aid)}:visible')
        if await loc.count(): return loc.first
    loc = page.get_by_role("button", name=re.compile(r"^(save and continue|next|continue)$", re.I))
    return loc.first if await loc.count() else None
async def click_next(page):
    """Save and Continue. On the Review step the same footer button (pageFooterNextButton) reads 'Submit': a button that
    says Submit (or says nothing) is never clicked here; only the approved --submit path in at_review() may click it.
    Returns 'clicked', 'submit' (the footer button is Submit: this is the review step) or 'none'."""
    b = await next_button(page)
    if b is None: return "none"
    try: label = re.sub(r"\s+", " ", await b.inner_text(timeout=3000)).strip()
    except Exception: label = ""
    if not label or re.search(r"submit", label, re.I): return "submit"
    try: await b.click(timeout=5000)
    except Exception:
        try: await b.locator("xpath=..").locator(A("click_filter")).first.click(timeout=3000)
        except Exception: await b.dispatch_event("click")
    return "clicked"
async def wait_advance(page, before, secs=45):
    """After Save and Continue: 'moved' once the active step changes, 'errors' when Workday reports validation errors,
    'stuck' when neither happens."""
    end = time.time() + secs
    while time.time() < end:
        await page.wait_for_timeout(1000)
        if await form_errors(page): return "errors"
        st = await step_raw(page)
        if st and st != before: return "moved"
    return "stuck"

FIELD_JS = r"""(root)=>{
  root=root||document;
  const clean=s=>(s||'').replace(/\s+/g,' ').trim();
  const labelOf=(el)=>{const l=el.id&&document.querySelector('label[for="'+CSS.escape(el.id)+'"]'); return clean(l?l.innerText:((el.closest('label')||el.parentElement||{}).innerText||''));};
  const out=[];
  for (const f of root.querySelectorAll('[data-automation-id^="formField-"]')) {
    if (!f.offsetParent) continue;
    if (f.parentElement && f.parentElement.closest('[data-automation-id^="formField-"]')) continue;
    const id=f.getAttribute('data-automation-id').replace('formField-','');
    const lab=clean((f.querySelector('legend, label, [data-automation-id="richText"]')||{}).innerText||'');
    const req=/\*/.test(lab) || !!f.querySelector('[aria-required="true"], [required]');
    const g=f.closest('[role="group"][aria-labelledby$="-section"]');
    let kind='other';
    if (f.querySelector('button[aria-haspopup="listbox"]')) kind='listbox';
    else if (f.querySelector('[data-automation-id="multiselectInputContainer"], [data-automation-id="searchBox"]')) kind='prompt';
    else if (f.querySelector('input[type="radio"]')) kind='radio';
    else if (f.querySelector('input[type="checkbox"]')) kind='checkbox';
    else if (f.querySelector('textarea')) kind='textarea';
    else if (f.querySelector('[data-automation-id="dateSectionMonth-input"], [data-automation-id="dateSectionYear-input"], [data-automation-id="dateSectionDay-input"]')) kind='date';
    else if (f.querySelector('input[type="text"], input:not([type]), input[type="tel"], input[type="email"], input[type="number"]')) kind='text';
    let val='';
    const b=f.querySelector('button[aria-haspopup="listbox"]');
    if (b) { val=clean(b.innerText); if (/^select one$/i.test(val)) val=''; }   // the text beside it holds an internal id
    else if (kind==='prompt') val=[...f.querySelectorAll('[data-automation-id="selectedItem"]')].map(s=>clean(s.innerText)).join('; ');
    else if (kind==='radio'||kind==='checkbox') val=[...f.querySelectorAll('input[type="radio"]:checked, input[type="checkbox"]:checked')].map(labelOf).join('; ');
    else if (kind==='date') { const d=[...f.querySelectorAll('[data-automation-id$="-display"]')].map(x=>clean(x.innerText)); val=d.length&&d.every(x=>/^\d+$/.test(x))? d.join('/'):''; }
    else { const i=f.querySelector('textarea, input[type="text"], input:not([type]), input[type="tel"], input[type="number"], input[type="email"]'); if (i && i.value) val=i.value; }
    const opts=(kind==='radio'||kind==='checkbox')? [...f.querySelectorAll('input[type="radio"], input[type="checkbox"]')].map(labelOf).slice(0,12):[];
    out.push({id, fkit: f.getAttribute('data-fkit-id')||'', label:lab.replace(/\s*\*\s*$/,'').trim(), req, kind, val, opts, sec: g? g.getAttribute('aria-labelledby').replace(/-section$/,''):'', nbox: f.querySelectorAll('input[type="checkbox"]').length});
  }
  return out;}"""
REVIEW_JS = r"""(root)=>{
  const clean=s=>(s||'').replace(/\s+/g,' ').trim(); const out=[]; let sec='';
  const qs=(el)=>[...el.querySelectorAll('label, [data-automation-id="richText"]')].some(x=>clean(x.innerText));
  for (const el of root.querySelectorAll('h3, h4, label, [data-automation-id="richText"]')) {
    if (el.tagName==='H3') { sec=clean(el.innerText); continue; }
    const q=clean(el.innerText); if (!q) continue;
    let a='';
    if (el.tagName==='H4') {
      const box=el.parentElement;
      const files=[...box.querySelectorAll('[data-automation-id="file-upload-item-name"]')].map(x=>clean(x.innerText));
      a=files.length? files.join('; ') : clean([...box.children].filter(c=>c!==el && c.tagName!=='LABEL' && !qs(c)).map(c=>c.innerText).join(' '));
      if (!a) continue;
    } else if (el.tagName==='LABEL') {
      a=clean(el.nextElementSibling? el.nextElementSibling.innerText:'');
    } else {
      if (el.closest('label')) continue;
      let p=el; while (p && p!==root && !p.nextElementSibling) p=p.parentElement;
      a=clean(p && p!==root && p.nextElementSibling? p.nextElementSibling.innerText:'');
    }
    out.push({section:sec, question:q, answer:a});
  }
  return out;}"""

# ---- answers
def choice_for(label):
    v = pick(label, CHOICE_RULES)
    if v is None: return None
    return v if isinstance(v, list) else [v]
def text_for(label):
    """Free-text answer from TEXT_RULES. (Education start/end years are filled only inside an Education entry, never
    for any label that merely mentions a month or a year, such as 'How many years of experience ...'.)"""
    v = pick(label, TEXT_RULES)
    return v if isinstance(v, str) and v.strip() else None
VET_Q = re.compile(r"veteran|military (service|status)|served in the (u\.?s\.? )?(military|armed forces)|armed forces|uniformed service", re.I)
VET_BAD = re.compile(r"identify as (a|an|one)\b|\bi am a (protected |disabled |recently separated |active duty )?veteran\b|classifications? of protected|just not a protected|^\s*yes\b", re.I)
VET_PREFS = ["I am not a veteran", "Not a veteran", "No, I am not a veteran", "I am not a protected veteran", "Not a protected veteran", "No military service", "I have not served", "No",
             "I do not wish to self-identify", "I don't wish to self-identify", "I do not wish to answer"]   # applicant: not a veteran; declining is the only other truthful answer
DIS_Q = re.compile(r"disabilit", re.I)
DIS_BAD = re.compile(r"^\s*yes\b|^\s*i have a disability", re.I)
HEAR_NOT = re.compile(r"residen(cy|t)|program\b|academy|scholarship|community|network\b|club\b|challenge|contest|competition|\bdays?\b|\bweek\b|udacity|coursera|bootcamp|student|intern(ship)?\b|alumni|campus|universit|college|school|event|conference|\bfair\b|expo\b|summit|meetup|webinar|hackathon|ignite|associat|society|diversity|women|veteran|military|referr|employee|recruit|agency|headhunter|linkedin|social|facebook|twitter|instagram|youtube|tiktok|weibo|wechat|xing|glassdoor|indeed|monster|\bdice\b|ziprecruiter|handshake|kaggle|newspaper|magazine|radio|television|\btv\b|billboard|\bprint\b|e-?mail|text message|\bsms\b|word of mouth|friend|colleague|family", re.I)
AI_Q = re.compile(r"ai policy|use of ai|ai assistance|ai tools? (in|during)|without (the use of )?ai|ai agent|are you an ai|(did|have) you use(d)? (any )?ai", re.I)
# details of a former job at this company (after "previously worked here? Yes"): his old work email, employee ID or manager
# are not in the profile, and the generic e-mail / name rules must never answer them with his personal details
FORMER_JOB_Q = re.compile(r"\b(work|company|business|corporate|employee|office|former|previous|prior)\b.{0,20}\be-?mail|\be-?mail\b.{0,40}\b(while|when)\b|\bwas your\b.{0,30}\b(e-?mail|employee|id|manager|supervisor)|(former|previous|prior) (employee|worker) (id|number)|employee (id|number)", re.I)
# 'Is your work authorization based on your status as a spouse of an H-1B ...?': the applicant is a US citizen, so a
# generic 'work authorization -> Yes' rule must never claim a visa-based status (Snap); such a Yes is left for him
VISA_STATUS_Q = re.compile(r"\b(based on|because of|by virtue of|derived from|depend\w* on|through|status as)\b.{0,60}\b(spouse|dependent|h-?1b|h-?4|l-?1|l-?2|e-?[1-3]|f-?1|j-?1|opt|cpt|ead|tn|visa|asylum|refugee|daca|tps)\b", re.I)
# 'Do you currently live within commutable distance to the office ...?' names no place, so the rules' 'lives somewhere
# else -> No' answer does not apply (PayPal San Jose, Snap Palo Alto: he lives in Santa Clara): left for the applicant
COMMUTE_Q = re.compile(r"\b(live|living|reside|residing|located|based)\b.{0,30}\b(within|in|near|to)\b.{0,50}\b(commut\w*|the office|office location|the location|this location|job location|advertised|listed)", re.I)
def usable(texts, label):
    """Option texts with the ones the applicant must never pick blanked out: referral / recruiter / event / university /
    LinkedIn sources, 'I identify as a veteran ...' (he is not a veteran), and 'Yes, I have a disability'."""
    out = mask_hear(texts, label)
    if HEAR_Q.search(label or ""): out = ["" if HEAR_NOT.search(t or "") else t for t in out]
    if VET_Q.search(label or ""): out = ["" if VET_BAD.search(t or "") else t for t in out]
    if DIS_Q.search(label or ""): out = ["" if DIS_BAD.search(t or "") else t for t in out]
    return out
def rank(texts, prefs, label, strict=None, exact=False):
    """Index of the first option matching the earliest preference (veteran options: exact or leading matches only, so
    'Not a protected veteran' can never match inside 'I identify as a veteran, just not a protected veteran').
    exact: the option must equal the preference (search prompts, where the rules' 'Engineering' must never pick
    'Aerospace Engineering')."""
    u = usable(texts, label)
    strict = bool(VET_Q.search(label or "")) if strict is None else strict
    for p in prefs or []:
        if exact: k = next((i for i, t in enumerate(u) if t and norm(t) == norm(p)), None)
        elif strict: k = next((i for i, t in enumerate(u) if t and _match(t, p, True)), None)
        else: k = best_index(u, p)
        if k is not None: return k
    return None
def prefs_for(label):
    v = choice_for(label)
    if VET_Q.search(label or "") and v != ["__ASK__"]:
        return VET_PREFS + [p for p in (v or []) if p not in VET_PREFS and not VET_BAD.search(p)]
    return v
def phone_rank(texts):
    """Phone Device Type: the applicant's number is his mobile: Mobile / Cell (also 'Home Cellular'), never a work line."""
    good = [i for i, t in enumerate(texts) if re.search(r"mobile|cell", t or "", re.I) and not re.search(r"work|business|office|fax|pager", t or "", re.I)]
    if good: return min(good, key=lambda i: (0 if re.fullmatch(r"(personal )?(mobile|cell|cellular)( phone)?", texts[i].strip(), re.I) else 1, i))
    return next((best_index(texts, p) for p in ("Home", "Personal") if best_index(texts, p) is not None), None)
STOP_WORDS = {"inc", "inc.", "llc", "ltd", "corp", "corp.", "corporation", "company", "co", "co.", "group", "the", "technologies", "technology", "software", "systems", "holdings", "plc", "international", "&"}
def company_tokens(company, url=""):
    words = [w for w in re.findall(r"[a-z0-9&.]+", re.sub(r"\(.*?\)", "", (company or "").lower())) if w not in STOP_WORDS]
    toks = {norm("".join(words))} | {norm(w) for w in words if len(norm(w)) >= 4}
    t = norm(tenant_of(url)) if url else ""
    if len(t) >= 4: toks.add(t)
    return {x for x in toks if len(x) >= 3}
SITE = re.compile(r"\.com\b|\.co\b|web ?site|\bcareers?\b( (site|page|portal|web ?site|home ?page))?\s*$|\bcareers? (site|page|portal|web ?site)\b|\bjobs? (site|page|portal)\b|\bsite\b|\bportal\b|\bweb\b|\bhome ?page\b", re.I)
def hear_score(t, toks, cat=""):
    """How well a 'How did you hear about us?' item describes the applicant's real source, the company's own careers site:
    100 names the company's website / careers site (NVIDIA.COM), 90 a generic careers site or company website, 60 a plain
    website / internet item, 40 a generic job-board item, 20 'Other'; 0 is never picked (referral, recruiter, event,
    university, LinkedIn, a named job board or social network, a programme, ...)."""
    tl = (t or "").strip().lower()
    if not tl or HEAR_BAD.search(tl) or HEAR_NOT.search(tl): return 0
    webcat = bool(re.search(r"web|site|career|internet|online", cat or "", re.I))
    web = SITE.search(tl) or webcat   # a site, not just 'career': 'Adobe Career Academy' is a programme
    if toks and any(k in norm(tl) for k in toks) and web: return 100 if (not cat or webcat) else 85   # 85: e.g. 'Talent Community > Cohesity Careers'
    if re.search(r"(company|corporate|employer|organi[sz]ation)('?s)? ?(career|careers|jobs?|web ?site|site|page|portal)|careers? ?(web ?site|site|page|portal|section)|^careers?$", tl): return 90
    if re.search(r"\b(jobs?|careers?) (page|section|site|board)\b.{0,30}\b(your|our|the company.?s|company) (web ?site|site)|\b(your|our|the company.?s) (careers? |jobs? )?(web ?site|site|page)\b", tl): return 90   # 'Jobs page on your website'
    if re.search(r"^(the )?(web ?site|internet|online|web|internet search|online search|search engine|google( search)?|web search)$", tl): return 60
    if re.search(r"^(online )?(job board|job boards|job posting|job postings|job post site|job site|job search site)$", tl): return 40
    if re.search(r"^other\b|not listed", tl) and (not cat or re.search(r"other|web|site|internet|online", cat, re.I)): return 20
    return 0
def cat_rank(c, toks=()):
    """Which categories of a source tree may hold the company's careers site: website-like first, then company-named
    ('Company Marketing', 'Cohesity Talent Community'), then 'Other', then job boards (only generic items count there)."""
    if HEAR_BAD.search(c) or HEAR_NOT.search(c): return 9
    if re.search(r"web|site|career|internet|online|search", c, re.I): return 0
    if re.search(r"company|corporate", c, re.I) or any(k in norm(c) for k in toks): return 1
    if re.search(r"other", c, re.I): return 2
    if re.search(r"job|posting|advert", c, re.I): return 3
    return 9

# ---- Workday widgets
LISTBOX_OPT = '[role="listbox"]:not([data-automation-id="selectedItemList"]) [role="option"]:visible:not([aria-disabled="true"])'
async def listbox_choose(page, button, ranker, typeahead=""):
    """Workday single-select (button[aria-haspopup=listbox]): open it, click the option ranker(texts) names, and verify
    the button now shows it. The options are the popup's own list, never the selected-item pills of other prompts."""
    try:
        await button.scroll_into_view_if_needed(timeout=3000); await button.click(timeout=4000)
        opts = page.locator(LISTBOX_OPT)
        for _ in range(10):
            await page.wait_for_timeout(300)
            if await opts.count(): break
        texts = [(await opts.nth(i).inner_text()).strip() for i in range(min(await opts.count(), 400))]
        k = ranker(texts)
        if k is None and typeahead:   # a long list may render only part of its options: jump by typing
            await page.keyboard.type(typeahead[:8], delay=60); await page.wait_for_timeout(700)
            texts = [(await opts.nth(i).inner_text()).strip() for i in range(min(await opts.count(), 400))]
            k = ranker(texts)
        if k is None:
            await page.keyboard.press("Escape"); return None, texts
        await opts.nth(k).scroll_into_view_if_needed(timeout=2000); await opts.nth(k).click(timeout=4000); await page.wait_for_timeout(600)
        now = (await button.inner_text()).strip()
        return (texts[k] if norm(now) == norm(texts[k]) else None), texts
    except Exception:
        try: await page.keyboard.press("Escape")
        except Exception: pass
        return None, []
async def input_label(inp):
    try: return (await inp.evaluate("(el)=>{const l=el.id&&document.querySelector('label[for=\"'+CSS.escape(el.id)+'\"]');return (l?l.innerText:((el.closest('label')||el.parentElement||{}).innerText||'')).replace(/\\s+/g,' ').trim()}"))
    except Exception: return ""
async def set_check(inp, on):
    try:
        if await inp.is_checked() == on: return True
        rid = await inp.get_attribute("id")
        try:
            if rid: await inp.page.locator(f'label[for="{rid}"]').first.click(timeout=3000)
            else: await inp.click(force=True, timeout=3000)
        except Exception:
            await inp.evaluate("(el)=>{const l=el.id&&document.querySelector('label[for=\"'+CSS.escape(el.id)+'\"]');(l||el).click()}")
        await inp.page.wait_for_timeout(300)
        if await inp.is_checked() != on: await inp.set_checked(on, force=True, timeout=3000)
        return await inp.is_checked() == on
    except Exception:
        return False
async def pick_radio(page, box, ranker):
    radios = box.locator('input[type="radio"]'); n = await radios.count()
    texts = [await input_label(radios.nth(i)) for i in range(n)]
    k = ranker(texts)
    if k is None: return None
    return texts[k] if await set_check(radios.nth(k), True) else None
async def checkbox_choose(page, box, ranker):
    """A group of checkboxes answering one question: tick exactly the one the rules name, untick any other."""
    boxes = box.locator('input[type="checkbox"]'); n = await boxes.count()
    texts = [await input_label(boxes.nth(i)) for i in range(n)]
    k = ranker(texts)
    if k is None: return None
    for i in range(n):
        await set_check(boxes.nth(i), i == k)
    return texts[k] if await boxes.nth(k).is_checked() else None
async def menu_items(page):
    """Visible items of an open Workday prompt: (locator, texts, has-sub-list flags)."""
    loc = page.locator('[data-automation-id="menuItem"][role="option"]:visible')
    texts, subs = [], []
    for i in range(min(await loc.count(), 150)):
        try: t, c = await loc.nth(i).evaluate("e=>[e.innerText.trim(), (e.querySelector('[data-uxi-multiselectlistitem-hassidecharm]')||{getAttribute:()=>'false'}).getAttribute('data-uxi-multiselectlistitem-hassidecharm')==='true']")
        except Exception: t, c = "", False
        texts.append(t); subs.append(c)
    return loc, texts, subs
async def menu_scan(page):
    """All items of the open prompt level, scrolling a virtualised list (Workday renders ~14 rows at a time)."""
    seen, subs = [], {}
    for _ in range(25):
        loc, texts, sb = await menu_items(page)
        new = [t for t in texts if t and t not in subs]
        for t, c in zip(texts, sb):
            if t and t not in subs: seen.append(t); subs[t] = c
        if not new or not texts: break
        moved = await loc.nth(len(texts) - 1).evaluate("e=>{let p=e.parentElement; while(p && !(p.scrollHeight>p.clientHeight+4 && /(auto|scroll)/.test(getComputedStyle(p).overflowY))) p=p.parentElement; if(!p) return false; const t=p.scrollTop; p.scrollTop=t+p.clientHeight*0.8; return p.scrollTop!==t;}")
        if not moved: break
        await page.wait_for_timeout(400)
    return seen, [subs[t] for t in seen]
async def menu_wait(page, title_rx=None, before=None, secs=12):
    """Wait until the open prompt shows items: at the level whose title matches title_rx (a category name, 'Search
    Results'), or a list different from `before`. Right after sign-in Workday can take seconds to load a level."""
    end = time.time() + secs
    while time.time() < end:
        _, texts, _ = await menu_items(page)
        tl = page.locator(f'{A("promptTitle")}:visible')
        try: title = (await tl.first.inner_text(timeout=500)).strip() if await tl.count() else ""
        except Exception: title = ""
        if title_rx and re.search(r"no match", title, re.I): return True
        if texts and (not title_rx or re.search(title_rx, title, re.I)) and (before is None or texts != before): return True
        await page.wait_for_timeout(300)
    return False
async def menu_click(page, item):
    """Click the item with this exact text at the open prompt level (scrolling a virtualised list to reach it); for a
    category, wait until its sub-list has loaded."""
    for _ in range(25):
        loc, texts, subs = await menu_items(page)
        if item in texts:
            k = texts.index(item)
            await loc.nth(k).click(timeout=4000)
            if subs[k]: await menu_wait(page, title_rx="^" + re.escape(item) + "$")
            else: await page.wait_for_timeout(1200)
            return True
        if not texts: return False
        moved = await loc.nth(len(texts) - 1).evaluate("e=>{let p=e.parentElement; while(p && !(p.scrollHeight>p.clientHeight+4 && /(auto|scroll)/.test(getComputedStyle(p).overflowY))) p=p.parentElement; if(!p) return false; const t=p.scrollTop; p.scrollTop=t+p.clientHeight*0.8; return p.scrollTop!==t;}")
        if not moved: return False
        await page.wait_for_timeout(400)
    return False
async def prompt_selected(box):
    try: return [t.strip() for t in await box.locator(A("selectedItem")).all_inner_texts()]
    except Exception: return []
async def prompt_clear(page, box):
    for _ in range(6):
        x = box.locator(A("DELETE_charm"))
        if not await x.count(): return
        try: await x.first.click(timeout=3000)
        except Exception: return
        await page.wait_for_timeout(600)
async def prompt_open(page, box, query=""):
    """Open a prompt at its top level (or at the search results for query). Returns the items Workday selected by
    itself: a search with a single result is selected on Enter, and callers must accept or remove that selection."""
    inp = box.locator("input").first
    before = await prompt_selected(box)
    try: await page.keyboard.press("Escape")
    except Exception: pass
    await page.wait_for_timeout(300)
    await inp.scroll_into_view_if_needed(timeout=3000)
    try: await inp.click(timeout=3000)
    except Exception:   # a selected item's pill can cover the input
        try: await box.locator(A("promptIcon")).first.click(timeout=3000)
        except Exception: await inp.focus()
    await inp.fill("")
    if query:
        await inp.type(query[:40], delay=25); await inp.press("Enter")
        end = time.time() + 12
        while time.time() < end:
            now = await prompt_selected(box)
            if now != before: await page.wait_for_timeout(500); return [x for x in await prompt_selected(box) if x not in before]
            if await menu_wait(page, title_rx=r"search results|no match", secs=0.6): return []
        return []
    await menu_wait(page)
    for _ in range(3):
        back = page.locator(f'{A("backButton")}:visible')
        if not await back.count(): break
        _, prev, _ = await menu_items(page)
        await back.first.click(timeout=2000); await menu_wait(page, before=prev)
    return []
async def prompt_choose(page, box, prefs, label, searches=None):
    """A flat Workday prompt (search box + items): search, click the leaf the rules prefer, verify it is selected."""
    for q in (searches or prefs[:3]):
        try:
            auto = await prompt_open(page, box, q)
            if auto:   # Workday selected the lone search result itself: kept only when the rules name it exactly
                if rank(auto, prefs, label, exact=True) is not None: await page.keyboard.press("Escape"); return auto[0]
                await prompt_clear(page, box); continue
            loc, texts, subs = await menu_items(page)
            k = rank([t if not c else "" for t, c in zip(texts, subs)], prefs, label, exact=True)
            if k is None: continue
            want = texts[k]
            await loc.nth(k).click(timeout=4000); await page.wait_for_timeout(1200)
            await page.keyboard.press("Escape"); await page.wait_for_timeout(300)
            sel = [norm(x) for x in await prompt_selected(box)]
            if norm(want) in sel: return want
            if sel: await prompt_clear(page, box)
        except Exception:
            continue
    try: await page.keyboard.press("Escape")
    except Exception: pass
    return None
async def hear_choose(page, box, job):
    """'How Did You Hear About Us?': often a tree (NVIDIA: Associations, Event/Conference, Job Board, Social Media,
    University, Website > AI Residency Program / NVIDIA.COM / Udacity). The applicant found the job on the company's own
    careers site, so: the item naming the company's website or careers site, else a generic careers-site / website item,
    else 'Other' (hear_score). Never the first item of a sub-list, and never a referral, recruiter, event, university,
    LinkedIn or other specific source. Verified by the field's selected item."""
    toks = company_tokens(job.item.get("company"), job.url)
    await prompt_clear(page, box)
    await prompt_open(page, box)
    top, subs = await menu_scan(page)
    cands = [(hear_score(t, toks), [t]) for t, c in zip(top, subs) if not c]
    best = max(cands, default=(0, None), key=lambda x: x[0])
    if best[0] < 90:
        for cat in sorted([t for t, c in zip(top, subs) if c and cat_rank(t, toks) <= 3], key=lambda c: cat_rank(c, toks)):
            await prompt_open(page, box)
            if not await menu_click(page, cat): continue
            items, isub = await menu_scan(page)
            cands += [(hear_score(t, toks, cat), [cat, t]) for t, c in zip(items, isub) if not c]
            best = max(cands, default=(0, None), key=lambda x: x[0])
            if best[0] >= 90: break
    if best[0] < 90:   # a long or oddly grouped tree: search for the company's own site
        for q in sorted(toks, key=len, reverse=True)[:2]:
            auto = await prompt_open(page, box, q)
            if auto: await prompt_clear(page, box)   # a lone result Workday selected by itself: scored like the others
            _, res, rsub = await menu_items(page)
            res, rsub = (auto, [False] * len(auto)) if auto else (res, rsub)
            cands += [(hear_score(t, toks), ["", q, t]) for t, c in zip(res, rsub) if not c and hear_score(t, toks) >= 90]
            best = max(cands, default=(0, None), key=lambda x: x[0])
            if best[0] >= 90: break
    job.report.setdefault("source_options", {})["top"] = top[:40]
    if best[0] <= 0:
        await page.keyboard.press("Escape"); return None
    path = best[1]
    if len(path) == 3:
        auto = await prompt_open(page, box, path[1])
        ok = bool(auto) or await menu_click(page, path[2])
    elif len(path) == 2: await prompt_open(page, box); ok = await menu_click(page, path[0]) and await menu_click(page, path[1])
    else: await prompt_open(page, box); ok = await menu_click(page, path[0])
    try: await page.keyboard.press("Escape")
    except Exception: pass
    await page.wait_for_timeout(300)
    sel = await prompt_selected(box)
    if not (ok and len(sel) == 1 and norm(sel[0]) == norm(path[-1])):
        if sel: await prompt_clear(page, box)   # never leave an item selected that was not the one chosen
        return None
    job.report["source_options"]["picked"] = (f"search '{path[1]}' > " if len(path) == 3 else "") + " > ".join(path if len(path) < 3 else path[2:])
    return path[-1]
async def set_date(page, box, month=None, day=None, year=None):
    """Workday date widget (MM / DD / YYYY spin buttons); fills the sections the widget has and reads them back. The
    spin-button inputs sit hidden under their display text, so each is focused and typed into from the keyboard."""
    for aid, v in (("dateSectionMonth-input", month and f"{month:02d}"), ("dateSectionDay-input", day and f"{day:02d}"), ("dateSectionYear-input", year and str(year))):
        loc = box.locator(A(aid))
        if not (v and await loc.count()): continue
        try:
            try: await box.locator(A(aid.replace("-input", "-display"))).first.click(timeout=2000)
            except Exception: pass
            await loc.first.focus(); await page.keyboard.type(v, delay=80); await page.wait_for_timeout(200)
        except Exception: pass
    await page.wait_for_timeout(300)
    try: shown = [t.strip() for t in await box.locator('[data-automation-id$="-display"]').all_inner_texts()]
    except Exception: shown = []
    return "/".join(shown) if shown and all(t.isdigit() for t in shown) else None
async def date_field(page, box, lab):
    """Today's date on signature / 'today's date' fields (Self Identify form); any other date is left for the applicant."""
    if not re.search(r"today|signature date|date signed|^date$|^signed on|date of signature", (lab or "").strip().lower()): return None
    d = datetime.date.today()
    return await set_date(page, box, d.month, d.day, d.year)

DISC = re.compile(r"non-?compete|non-?solicit|financial interest|conflict of interest|relatives?\b|related to|family member|government official|convicted|felony|i am (currently )?subject to|i (currently )?hold|yes, i (have|had) (a |an )?(disabilit|relative|family|conflict|financial|non-?compete|criminal|conviction)|^\s*i have a disability", re.I)   # 'Yes, I have read the Terms' is an acknowledgement, not a disclosure
ACK = re.compile(r"i (have read|acknowledge|agree|understand|consent|certify|confirm)|terms and conditions|privacy (notice|policy|statement)|^accept\*?$|i accept|by (selecting|checking|clicking) (the|this) (check)?box", re.I)
class Job:
    def __init__(self, item):
        self.item = item; self.tag = item["tag"]; self.url = item["url"]; self.title = item.get("title", "")
        self.report = {"tag": self.tag, "ats": "workday", "url": self.url, "submitted": False, "result": "", "answers": {}, "unanswered": [], "errors": [], "pages": []}
    def ans(self, label, val): self.report["answers"][label[:120]] = val

async def fill_field(page, job, f):
    """Answer one Workday field; returns the answer, or None when it stays empty (the rules have no answer: never guessed).
    An answer already present (a resumed draft, or the tenant's saved profile) is kept only when the rules agree with it."""
    fid, lab, kind, cur = f["id"], f["label"], f["kind"], (f["val"] or "").strip()
    key = lab or fid; low = key.lower()
    box = page.locator(f'[data-fkit-id="{f["fkit"]}"]' if f.get("fkit") else A(f"formField-{fid}")).first   # fkit ids are unique, formField ids can repeat
    btn = box.locator('button[aria-haspopup="listbox"]').first
    def keep(v):
        job.ans(key, v); return v
    def kept_unverified():
        if cur: job.report.setdefault("kept_unverified", {})[key[:120]] = cur; job.ans(key, cur)
        return cur or None
    async def text_to(v):
        if cur and norm(cur) == norm(v): return keep(cur)
        return keep(v) if await fill(page, box.locator("textarea, input").first, v) else None
    async def choose(prefs, strict=None, typeahead="", mlabel=None):
        if cur and rank([x.strip() for x in cur.split(";")][:1], prefs, mlabel or key, strict, exact=(kind == "prompt")) is not None: return keep(cur)
        r = lambda texts: rank(texts, prefs, mlabel or key, strict)
        if kind == "listbox": v, _ = await listbox_choose(page, btn, r, typeahead)
        elif kind == "radio": v = await pick_radio(page, box, r)
        elif kind == "checkbox": v = await checkbox_choose(page, box, r)
        elif kind == "prompt":
            await prompt_clear(page, box)
            v = await prompt_choose(page, box, prefs, key)
        else: v = None
        return keep(v) if v else None
    # ---- the fixed My Information fields
    if re.search(r"firstname$", fid, re.I) or re.search(r"^(given|first) name", low): return await text_to(FIRST)
    if re.search(r"lastname$", fid, re.I) or re.search(r"^(family|last) name|^surname", low): return await text_to(LAST)
    if re.search(r"middlename$|preferredcheck$|addressline[2-9]$|extension$", fid, re.I) or re.search(r"extension|^middle name", low): return cur or None
    if re.search(r"addressline1$", fid, re.I): return keep(cur) if cur else None   # applicant: city only, no street address
    if re.search(r"(^|-|_)city$", fid, re.I): return await text_to("Santa Clara")
    if re.search(r"postalcode$", fid, re.I): return await text_to("95050")
    if re.search(r"phonenumber$", fid, re.I): return await text_to(re.sub(r"\D", "", P["phone"])[-10:])
    if re.search(r"phone(device)?type$", fid, re.I) or re.search(r"phone device type", low):
        if re.search(r"mobile|cell", cur, re.I): return keep(cur)
        v, _ = await listbox_choose(page, btn, phone_rank)
        return keep(v) if v else (keep(cur) if cur else None)
    if re.search(r"countryphonecode$", fid, re.I):
        if re.search(r"united states|\(\+1\)", cur, re.I): return keep(cur)
        await prompt_clear(page, box)
        v = await prompt_choose(page, box, ["United States of America (+1)", "United States (+1)", "USA (+1)", "United States of America", "United States"], key, searches=["United States"])
        return keep(v) if v else None
    if re.search(r"countryregion$", fid, re.I) or (kind == "listbox" and re.search(r"^(state|state/province|province|region|state or province)$", low)):
        return await choose(["California", "CA"], strict=True, typeahead="Calif")
    if fid.lower() in ("country", "countrydropdown") or (kind == "listbox" and low == "country"):
        return await choose(["United States of America", "United States", "USA"], strict=True, typeahead="United S")
    if re.search(r"(^|-)source$|sourceprompt", fid, re.I) or re.search(r"how did you (first )?(hear|learn|find)", low):
        toks = company_tokens(job.item.get("company"), job.url)
        if cur and hear_score(cur.split(";")[0], toks) >= 60: return keep(cur)
        if kind == "prompt":
            v = await hear_choose(page, box, job)
            if not v: await page.wait_for_timeout(2000); v = await hear_choose(page, box, job)   # a slow first load of the tree
        elif kind == "listbox":
            v, _ = await listbox_choose(page, btn, lambda t: max((i for i in range(len(t)) if hear_score(t[i], toks) > 0), key=lambda i: hear_score(t[i], toks), default=None))
        else: v = await choose(prefs_for(key) or [])
        return keep(v) if v else None
    # 'Have you previously worked for <company>?' is answered by the rules like any question: Yes for the applicant's
    # real past employers (Morgan Stanley, JPMorgan Chase, Bloomberg, ...), No for every other company
    if "linkedin" in low and kind in ("text", "textarea"): return await text_to(P["linkedin"])
    if kind in ("checkbox", "radio", "listbox") and (DIS_Q.search(key) or any(DIS_Q.search(o) for o in f.get("opts") or []) or (kind != "listbox" and DIS_Q.search(fid))):   # not the form's 'Language' listbox (id disabilityForm)
        # Self Identify (form CC-305): "Please check one of the boxes below" -> No, I do not have a disability ...
        return await choose(choice_for(key) or choice_for("disability status") or [], mlabel="disability status")
    # ---- everything else from the rules
    if AI_Q.search(key): return kept_unverified()   # AI-use / AI-agent questions are the applicant's to answer
    if FORMER_JOB_Q.search(key) and kind in ("text", "textarea"):
        if cur and norm(cur) in {norm(P["email"]), norm(P["name"]), norm(FIRST), norm(LAST)}:   # an earlier run's generic answer: remove it
            await fill(page, box.locator("textarea, input").first, ""); job.report.setdefault("cleared", []).append(key[:120])
            return None
        return kept_unverified()
    if kind in ("listbox", "radio", "prompt") or (kind == "checkbox" and f["nbox"] > 1):
        prefs = prefs_for(key)
        if prefs == ["__ASK__"]: return None
        if not prefs: return kept_unverified()
        if (VISA_STATUS_Q.search(key) and re.match(r"\s*yes", prefs[0], re.I)) or (COMMUTE_Q.search(key) and re.match(r"\s*no\b", prefs[0], re.I)):
            # a generic rule that would make a false statement here (see VISA_STATUS_Q / COMMUTE_Q): the applicant answers
            job.report.setdefault("rule_conflicts", []).append(f"{key[:150]} -> rule says {prefs[0]!r}; left unanswered")
            if cur: job.report.setdefault("kept_unverified", {})[key[:120]] = cur   # an answer saved by an earlier run stays visible in the report
            return None
        return await choose(prefs)
    if kind == "checkbox":   # one box: an acknowledgement / consent is ticked, a disclosure never is
        cb = box.locator('input[type="checkbox"]').first
        t = await input_label(cb) or lab
        if DISC.search(t) or not (ACK.search(t) or ACK.search(lab)): return cur or None
        return keep(t) if await set_check(cb, True) else None
    if kind in ("text", "textarea"):
        v = text_for(key)
        if v is None and f["req"] and not cur:
            v = tech_answer(key)   # apply.py's fallback for technical questions (None for personal ones)
            if v: job.report.setdefault("tech_fallback", []).append(key[:120])
        if kind == "textarea" and cur: return keep(cur)   # a note already written is kept
        if v: return await text_to(v)
        return kept_unverified()
    if kind == "date":
        if cur: return keep(cur)
        v = await date_field(page, box, key)
        return keep(v) if v else None
    return cur or None

async def fill_page(page, job):
    """Fill every visible field of the current step (Work Experience / Education entries are experience_page()'s).
    Answers can reveal follow-up questions, so fields are re-read until no new one appears.
    Returns the required fields left empty."""
    step = await active_step(page)
    if step and step not in job.report["pages"]: job.report["pages"].append(step)
    missing, seen = [], set()
    for _ in range(4):
        fields = [f for f in await page.evaluate(FIELD_JS) if (f["id"], f["label"]) not in seen]
        if not fields: break
        for f in fields:
            seen.add((f["id"], f["label"]))
            if f["sec"] in ("Work-Experience", "Education", "Websites", "Certifications", "Languages") or not f["id"]: continue
            try: v = await fill_field(page, job, f)
            except Exception as e:
                v = None; job.report["errors"].append(f"{(f['label'] or f['id'])[:60]}: {type(e).__name__}")
            if not v and f["req"]: missing.append(f["label"] or f["id"])
    return missing

# ---- My Experience
WORK_ENTRY = {"jobTitle": "CTO & Technical Co-Founder", "companyName": P["org"], "location": "Santa Clara, CA", "start": (1, 2023)}   # resume: HYPERION AI 2023-, Santa Clara, CA (rules: start month January)
FIELD_OF_STUDY = ["Computer Science and Engineering", "Computer Science & Engineering", "Computer Science & Engin.", "Computer Science & Engin", "Computer Science and Engin"]
async def upload_resume(page, job):
    path = resume_for(job.title); base = os.path.basename(path)
    names = lambda: page.locator(A("file-upload-item-name")).all_inner_texts()
    if base in [x.strip() for x in await names()]:   # a resumed draft already has it: never attach it twice
        job.ans("Resume", base); return True
    up = page.locator(f'input[type="file"]{A("file-upload-input-ref")}, {A("file-upload-input-ref")}, input[type="file"]')
    if not await up.count():
        job.report["errors"].append("resume upload: no file input"); return False
    try: await up.first.set_input_files(path)
    except Exception as e:
        job.report["errors"].append(f"resume upload: {str(e)[:80]}"); return False
    for _ in range(30):
        await page.wait_for_timeout(1000)
        if base in [x.strip() for x in await names()] and await page.locator(A("file-upload-successful")).count():
            job.ans("Resume", base); return True
    job.report["errors"].append("resume upload: not confirmed"); return False
async def fill_entry(page, job, kind, panel):
    """One Work Experience / Education entry: the applicant's current role (CTO & Technical Co-Founder, Hyperion AI,
    2023-present) or his degree (B.E. Computer Science and Engineering, University of Madras, 1991-1995). Empty fields
    only; an entry naming another employer or school is left as it is."""
    fields = await panel.evaluate(FIELD_JS)
    by = {re.sub(r".*--", "", f["id"]): f for f in fields}
    val = lambda k: ((by.get(k) or {}).get("val") or "").strip()
    fb = lambda k: panel.locator(A(f"formField-{k}")).first
    done = {}
    if kind == "work":
        if val("companyName") and norm(val("companyName")) != norm(WORK_ENTRY["companyName"]): return None
        for k in ("jobTitle", "companyName"):   # this is the applicant's entry: any other value is corrected
            if k in by and norm(val(k)) != norm(WORK_ENTRY[k]) and await fill(page, fb(k).locator("input").first, WORK_ENTRY[k]): done[k] = WORK_ENTRY[k]
        if "location" in by and not val("location") and by["location"]["kind"] == "text" and await fill(page, fb("location").locator("input").first, WORK_ENTRY["location"]): done["location"] = WORK_ENTRY["location"]
        if "currentlyWorkHere" in by and await set_check(fb("currentlyWorkHere").locator('input[type="checkbox"]').first, True): done["current"] = "yes"
        rd = by.get("roleDescription")
        if rd and rd["req"] and not val("roleDescription"):   # required (Relativity): the rules' reviewed Hyperion AI summary
            v = text_for("Tell us about your most recent project")
            if v and await fill(page, fb("roleDescription").locator("textarea, input").first, v): done["description"] = v[:70] + "..."
        want = f"{WORK_ENTRY['start'][0]:02d}/{WORK_ENTRY['start'][1]}"
        if "startDate" in by and val("startDate") != want: done["from"] = await set_date(page, fb("startDate"), month=WORK_ENTRY["start"][0], year=WORK_ENTRY["start"][1])
        label = f"{WORK_ENTRY['jobTitle']}, {WORK_ENTRY['companyName']}, {want}-present"
    else:
        sk = next((k for k in by if re.search(r"school", k, re.I)), None)   # schoolName (text) or school (prompt)
        if sk and val(sk) and "madras" not in val(sk).lower(): return None
        if sk and not val(sk):
            if by[sk]["kind"] == "prompt": done["school"] = await prompt_choose(page, fb(sk), choice_for("School or University") or ["University of Madras"], "School or University", searches=["University of Madras", "Madras", "Other"])
            elif await fill(page, fb(sk).locator("input").first, "University of Madras"): done["school"] = "University of Madras"
        dp = choice_for("Degree") or []
        if "degree" in by and (not val("degree") or rank([val("degree")], dp, "Degree") is None):
            v, _ = await listbox_choose(page, fb("degree").locator('button[aria-haspopup="listbox"]').first, lambda t: rank(t, dp, "Degree"))
            done["degree"] = v
        fp = FIELD_OF_STUDY + (choice_for("Field of Study") or [])
        if "fieldOfStudy" in by and (not val("fieldOfStudy") or rank([val("fieldOfStudy")], fp, "Field of Study", exact=True) is None):
            await prompt_clear(page, fb("fieldOfStudy"))   # e.g. 'Aerospace Engineering' from an earlier loose match
            done["field"] = await prompt_choose(page, fb("fieldOfStudy"), fp, "Field of Study", searches=["Computer Science and Engineering", "Computer Science", "Computer Engineering"])
        mon = lambda m: datetime.datetime.strptime(m, "%B").month
        for k, (y, m) in (("firstYearAttended", EDU_START), ("lastYearAttended", EDU_END)):
            if k in by and not re.search(str(y) + "$", val(k)): done[k] = await set_date(page, fb(k), month=mon(m), year=y)
        label = "B.E. Computer Science and Engineering, University of Madras, 1991-1995"
    job.ans(f"{'Work Experience' if kind == 'work' else 'Education'}: {label}", done)
    return done
def level_rank(texts, prefs):
    """Language level: CEFR-aware ('Fluent (C1)' picks 'C1 (Advanced)'), otherwise exact or leading matches only."""
    for p in prefs or []:
        m = re.search(r"\b([abc][12])\b", p, re.I)
        k = next((i for i, t in enumerate(texts) if m and re.search(r"\b" + m.group(1) + r"\b", t or "", re.I)), None) if m else None
        if k is None: k = next((i for i, t in enumerate(texts) if t and _match(t, p, True)), None)
        if k is not None: return k
    return None
async def fill_language(page, job, panel):
    """One Languages entry (Relativity: Language, 'I am fluent in this language.', Level): English, at the level the
    rules give for English (TEXT_RULES: English, full professional proficiency; CHOICE_RULES: Fluent (C1) first)."""
    fields = await panel.evaluate(FIELD_JS)
    lang = next((f for f in fields if re.search(r"^language$", f["label"], re.I)), None)
    if lang and lang["val"] and norm(lang["val"]) != "english": return None   # another language the profile has: left as it is
    done = {}
    if lang and not lang["val"]:
        v, _ = await listbox_choose(page, panel.locator(f'[data-fkit-id="{lang["fkit"]}"] button[aria-haspopup="listbox"]').first, lambda t: rank(t, ["English"], "Language", exact=True), "English")
        done["language"] = v
    prefs = choice_for("English language proficiency") or []
    for f in fields:
        loc = panel.locator(f'[data-fkit-id="{f["fkit"]}"]').first
        if f["kind"] == "checkbox" and re.search(r"fluent|native", f["label"], re.I):
            done["fluent"] = await set_check(loc.locator('input[type="checkbox"]').first, True)
        elif f["kind"] == "listbox" and f is not lang and re.search(r"level|proficien|reading|writing|speaking|overall|comprehension", f["label"], re.I) and not f["val"]:
            v, _ = await listbox_choose(page, loc.locator('button[aria-haspopup="listbox"]').first, lambda t: level_rank(t, prefs))
            done[f["label"]] = v
    job.ans("Language: English", done)
    return done
async def experience_page(page, job, need=()):
    """My Experience: attach the resume once. Work Experience / Education / Languages entries are added only when Workday
    requires them (the section heading is starred, or its errors name the section): uploading the resume is enough otherwise."""
    await upload_resume(page, job)
    g = page.locator('[role="group"][aria-labelledby="Languages-section"]')
    if await g.count():
        panels = g.locator('[role="group"][aria-labelledby$="-panel"]')
        try: head = (await page.locator('[id="Languages-section"]').first.inner_text(timeout=2000)).strip()
        except Exception: head = ""
        if not await panels.count() and ("*" in head or "lang" in need):
            await g.locator(A("add-button")).first.click(timeout=4000); await page.wait_for_timeout(1500)
        for i in range(await panels.count()):
            await fill_language(page, job, panels.nth(i))
    for sec, kind in (("Work-Experience", "work"), ("Education", "edu")):
        g = page.locator(f'[role="group"][aria-labelledby="{sec}-section"]')
        if not await g.count(): continue
        try: head = (await page.locator(f'[id="{sec}-section"]').first.inner_text(timeout=2000)).strip()
        except Exception: head = ""
        panels = g.locator('[role="group"][aria-labelledby$="-panel"]')
        if not await panels.count():
            if "*" not in head and kind not in need: continue
            await g.locator(A("add-button")).first.click(timeout=4000); await page.wait_for_timeout(1500)
        for i in range(await panels.count()):
            await fill_entry(page, job, kind, panels.nth(i))

# ---- sign-in
SIGNIN_UI = f'{A("signInContent")}:visible, {A("SignInWithEmailButton")}:visible, {A("signInSubmitButton")}:visible, {A("createAccountLink")}:visible, {A("createAccountSubmitButton")}:visible, {A("signInLink")}:visible, input{A("password")}:visible'
APPLY_FORM = f'{A("applyFlowMyInfoPage")}, {A("applyFlowMyExpPage")}, {A("applyFlowPage")} [data-automation-id^="formField-"]'
async def form_open(page):
    """The application form itself is showing without a sign-in step: signed in, a resumed draft, or a tenant that lets
    candidates apply without an account (Adobe: My Information with its own Email field, 'Sign In' still in the header)."""
    try:
        st = await step_raw(page)
        if not st or re.search(r"sign in|create account", st, re.I) or await page.locator(SIGNIN_UI).count(): return False
        return await page.locator(APPLY_FORM).count() > 0
    except Exception:
        return False
async def signed_in_now(page):
    """Signed in to this tenant: the header's Sign In button gave way to the account menu / Candidate Home, or the apply
    flow is already past its sign-in step (a resumed draft goes straight to My Information)."""
    try:
        if await page.locator(f'input{A("password")}:visible').count() or await page.locator(f'{A("utilityButtonSignIn")}:visible').count(): return False
        if await page.locator(f'{A("utilityButtonAccountTasksMenu")}, {A("navigationItem-Candidate Home")}').count(): return True
        st = await step_raw(page)
        return bool(st) and not re.search(r"sign in|create account", st, re.I) and not await page.locator(SIGNIN_UI).count()
    except Exception:
        return False
async def auth_state(page, secs=30):
    """Where the apply flow landed: 'in' (signed in, or 'already applied'), 'form' (sign-in / create-account), 'captcha' or 'unknown'."""
    end = time.time() + secs
    while time.time() < end:
        try:
            if await page.locator(CAPTCHA).count(): return "captcha"
            if APPLIED.search(await text(page)) or await signed_in_now(page) or await form_open(page): return "in"
            if await page.locator(SIGNIN_UI).count():
                await page.wait_for_timeout(1000); return "form"
        except Exception: pass
        await page.wait_for_timeout(800)
    return "unknown"
async def auth(page, job, s):
    """Sign in or create the tenant account (applicant's plan): one sign-in attempt with his Workday login
    (wf_creds workday.email + first password); if that fails, create the account with workday.new_account_email /
    new_account_password (Gmail, so a verification link can be read); an existing Gmail account is signed in instead.
    An already signed-in session (an earlier job on the tenant, a resumed draft) needs no sign-in at all.
    Returns 'ok', 'verify', 'blocked' or 'fail'. Never more than one attempt per credential (no lockouts)."""
    ten = tenant_of(job.url)
    st = await auth_state(page)
    if st == "captcha": return "blocked"
    if st == "in": return "ok"
    known = s["tenants"].get(ten) or {}
    async def sign_in(email, pw):
        """One attempt: True / False, None when a captcha appears (never solved), or 'noform' when there was no sign-in
        form to fill (nothing was submitted, so it is not an attempt)."""
        if await page.locator(f'{A("signInLink")}:visible').count() and not await page.locator(f'{A("signInSubmitButton")}:visible').count():
            await click_button(page, "signInLink"); await page.wait_for_timeout(1500)
        if not await page.locator(f'input{A("password")}:visible').count():   # social chooser first: pick "Sign in with email"
            await click_button(page, "SignInWithEmailButton", timeout=3000) or await click_button(page, name=r"sign in with email", timeout=3000)
            await page.wait_for_timeout(1500)
        if not await page.locator(f'input{A("email")}:visible').count() or not await page.locator(f'input{A("password")}:visible').count():
            return "noform"   # no sign-in form: nothing was submitted
        await fill(page, page.locator(f'input{A("email")}:visible').first, email)
        await fill(page, page.locator(f'input{A("password")}:visible').first, pw)
        if await page.locator(CAPTCHA).count(): return None
        await click_button(page, "signInSubmitButton") or await click_button(page, name=r"^sign in$")
        end = time.time() + 30   # wait for the outcome (a slow tenant used to be read as a failure after 5 s)
        while time.time() < end:
            await page.wait_for_timeout(1000)
            if await page.locator(CAPTCHA).count(): return None
            if APPLIED.search(await text(page)) or await signed_in_now(page): return True
            form = page.locator(A("signInContent"))
            ft = (await form.first.inner_text()) if await form.count() else ""
            if re.search(r"wrong|invalid|incorrect|not recogni[sz]ed|locked|could not|unable to sign|verify your|not (been )?verified|doesn.t match", ft, re.I): return False
        return False
    def remember(email, pw_key):
        s["tenants"][ten] = {"email": email, "pw_key": pw_key, "ts": int(time.time())}; save_secret(s)
    creds = {"login": (s["email"], s["passwords"][0]), "new": (s.get("new_account_email") or P["email"], s.get("new_account_password") or s["passwords"][0])}
    if known.get("pw_key") in creds:
        if known.get("failed"):   # the remembered login failed on an earlier run: never retried (lockouts); fix wf_creds, then remove "failed"
            job.report["errors"].append(f"sign-in with the remembered {known['pw_key']} login failed on an earlier run; not retried"); return "fail"
        e, pw = creds[known["pw_key"]]
        r = await sign_in(e, pw)
        if r == "noform": return "ok" if await auth_state(page, 10) == "in" else "fail"
        if r is False: known["failed"] = int(time.time()); s["tenants"][ten] = known; save_secret(s)
        return "ok" if r else ("blocked" if r is None else "fail")
    # 1) one attempt with the applicant's Workday login (never again on this tenant once it has failed)
    r = "noform" if known.get("login_failed") else await sign_in(*creds["login"])
    if r is None: return "blocked"
    if r is True: remember(creds["login"][0], "login"); return "ok"
    if r is False: s["tenants"][ten] = {"login_failed": int(time.time())}; save_secret(s)
    # 2) create the account with the new-account email (Gmail)
    await page.goto(page.url, wait_until="domcontentloaded", timeout=60000)
    st = await auth_state(page)
    if st == "captcha": return "blocked"
    if st == "in":   # the one sign-in went through after all (slow tenant), or the form needs no account
        if r is not True and r != "noform": remember(creds["login"][0], "login")
        return "ok"
    if not await page.locator(f'{A("createAccountLink")}:visible, input{A("verifyPassword")}:visible').count():   # social chooser first (PTC)
        await click_button(page, "SignInWithEmailButton", timeout=3000) or await click_button(page, name=r"sign in with email", timeout=3000)
        await page.wait_for_timeout(1500)
    if await page.locator(A("createAccountLink")).count(): await click_button(page, "createAccountLink"); await page.wait_for_timeout(1500)
    if not await page.locator(f'input{A("verifyPassword")}').count():
        return "fail"
    e, pw = creds["new"]
    await fill(page, page.locator(f'input{A("email")}').first, e)
    await fill(page, page.locator(f'input{A("password")}').first, pw)
    await fill(page, page.locator(f'input{A("verifyPassword")}').first, pw)
    cb = page.locator(f'input{A("createAccountCheckbox")}')
    if await cb.count():
        try: await cb.first.check(timeout=3000)
        except Exception: await cb.first.evaluate("(el)=>el.click()")
    if await page.locator(CAPTCHA).count(): return "blocked"
    await click_button(page, "createAccountSubmitButton") or await click_button(page, name=r"^create account$")
    end = time.time() + 40
    while time.time() < end:
        await page.wait_for_timeout(1500)
        if await page.locator(CAPTCHA).count(): return "blocked"
        body = await text(page)
        if re.search(r"already (exists|in use|registered)|account with this email", body, re.I):
            if (s["tenants"].get(ten) or {}).get("new_failed"): return "fail"   # tried once already: never again (lockouts)
            r = await sign_in(e, pw)
            if r is True: remember(e, "new"); return "ok"
            if r is False: s["tenants"].setdefault(ten, {})["new_failed"] = int(time.time()); save_secret(s)
            return "blocked" if r is None else "fail"
        if re.search(r"email has been sent|verify (your )?(email|account)|verification (email|link)|check your email|resend account verification", body, re.I):
            remember(e, "new"); return "verify"
        if APPLIED.search(body) or await signed_in_now(page): remember(e, "new"); return "ok"
        errs = await form_errors(page)
        if errs:   # e.g. Visa: 'Password must include: A minimum of 12 characters' (wf_creds new_account_password)
            job.report["errors"] += [f"create account: {x}" for x in errs[:3]]; return "fail"
    return "fail"

async def wait_file(path, secs):
    end = time.time() + secs
    while time.time() < end:
        if os.path.exists(path):
            v = open(path).read().strip()
            if v: return v
        await asyncio.sleep(3)
    return None

async def at_review(page, job, item):
    """The Review step: save every question and answer it shows (out/<tag>_wd_review.json) and a screenshot. A dry run
    stops here; with --submit, Submit is clicked only after the applicant's OK in out/<tag>_wd_approve.txt."""
    await settle(page)
    rv = page.locator(A("applyFlowReviewPage"))
    qa = await rv.first.evaluate(REVIEW_JS) if await rv.count() else []
    body = await text(page)
    review = {"tag": job.tag, "url": job.url, "title": job.title, "company": item.get("company"), "ts": time.time(), "step": await active_step(page), "answers": job.report["answers"], "review": qa, "review_text": body[:15000]}
    json.dump(review, open(f"{OUT}/{job.tag}_wd_review.json", "w"), indent=1)
    await page.screenshot(path=f"{OUT}/{job.tag}_wd_review.png", full_page=True)
    job.report["review"] = qa
    if not SUBMIT:
        job.report["result"] = "DRY RUN: stopped at Review"; return job.report
    ap = f"{OUT}/{job.tag}_wd_approve.txt"
    if os.path.exists(ap): os.remove(ap)
    print(f"WD REVIEW {job.tag}", flush=True)
    v = await wait_file(ap, REVIEW_WAIT)
    if not v or not v.upper().startswith("OK"):
        job.report["result"] = f"NOT SUBMITTED: review {'rejected: ' + v if v else 'not approved in time'}"; return job.report
    b = await next_button(page)
    if b is None or not re.search(r"^submit$", (await b.inner_text()).strip(), re.I):
        job.report["result"] = "NOT SUBMITTED: no Submit button on the review step"; return job.report
    await b.click(timeout=5000)
    for _ in range(30):
        await page.wait_for_timeout(1000)
        body = await text(page)
        if re.search(r"application (was )?submitted|thank you for (applying|your application)|successfully submitted|congratulations", body, re.I):
            job.report["submitted"] = True; job.report["result"] = body[:300]; return job.report
    job.report["errors"] = await form_errors(page)
    job.report["result"] = "NOT SUBMITTED: no confirmation after Submit"; return job.report

async def open_apply(page):
    """From the job page: 'Apply' (then 'Apply Manually'), or 'Continue Application' when a signed-in draft exists."""
    try: await page.locator(f'{A("adventureButton")}:visible, {A("continueButton")}:visible').first.wait_for(state="visible", timeout=15000)
    except Exception: pass
    if not (await click_button(page, "adventureButton", timeout=1000) or await click_button(page, "continueButton", timeout=1000) or await click_button(page, name=r"^(apply|continue application)$", timeout=3000)):
        return False
    await page.wait_for_timeout(2500)
    if await page.locator(A("applyManually")).count(): await click_button(page, "applyManually"); await page.wait_for_timeout(2500)
    return True

async def run_one(ctx, item, s):
    job = Job(item); page = await ctx.new_page(); rp = f"{OUT}/{job.tag}_wd_report.json"
    try:
        if NEVER_APPLY.search(job.tag + " " + item.get("company", "") + " " + job.url):
            job.report["result"] = "NOT SUBMITTED: do-not-apply company"; return job.report
        await page.goto(job.url, wait_until="domcontentloaded", timeout=60000); await page.wait_for_timeout(4000)
        body = await text(page)
        if re.search(r"no longer (available|accepting)|job (posting )?(is )?closed|page you are looking for doesn.t exist", body, re.I):
            job.report["result"] = "NOT SUBMITTED: job closed"; return job.report
        if await page.locator(CAPTCHA).count():
            job.report["result"] = "NOT SUBMITTED: captcha/bot check on the job page (not bypassed)"; return job.report
        if await page.locator(f'{A("legalNoticeDeclineButton")}:visible').count():   # cookie banner: strictly necessary cookies only
            await click_button(page, "legalNoticeDeclineButton", timeout=3000); await page.wait_for_timeout(800)
        if APPLIED.search(body):
            job.report["result"] = "ALREADY APPLIED on this company's Workday site"; return job.report
        if not await open_apply(page):
            job.report["result"] = "NOT SUBMITTED: no Apply button"; return job.report
        a = await auth(page, job, s)
        log(job, f"auth: {a}")
        if a == "blocked": job.report["result"] = "NOT SUBMITTED: captcha/bot check at sign-in (not bypassed)"; return job.report
        if a == "verify":
            req = f"{OUT}/{job.tag}_verify_request.json"; ans = f"{OUT}/{job.tag}_verify.txt"
            em = (s["tenants"].get(tenant_of(job.url)) or {}).get("email") or s.get("new_account_email") or s["email"]
            json.dump({"tag": job.tag, "email": em, "url": job.url, "tenant": tenant_of(job.url), "ts": time.time()}, open(req, "w"), indent=1)
            print(f"VERIFY REQUEST {job.tag}", flush=True)
            link = await wait_file(ans, VERIFY_WAIT)
            if not link: job.report["result"] = "NOT SUBMITTED: email verification link not received"; return job.report
            await page.goto(link, wait_until="domcontentloaded", timeout=60000); await page.wait_for_timeout(4000)
            await page.goto(job.url, wait_until="domcontentloaded", timeout=60000); await page.wait_for_timeout(3000)
            await open_apply(page)
            if await auth(page, job, s) != "ok": job.report["result"] = "NOT SUBMITTED: sign-in failed after verification"; return job.report   # auth() signs in with the remembered new-account login
        elif a == "fail":
            await page.screenshot(path=f"{OUT}/{job.tag}_wd_auth.png", full_page=True)
            pw = any(re.search(r"password", x, re.I) for x in job.report["errors"])
            job.report["result"] = "NOT SUBMITTED: " + ("the tenant rejected the new-account password (see errors)" if pw else "could not create an account or sign in"); return job.report
        await settle(page)
        if APPLIED.search(await text(page)):
            job.report["result"] = "ALREADY APPLIED on this company's Workday site"; return job.report
        # ---- the wizard
        repaired, stuck = set(), 0
        for _ in range(16):
            await settle(page)
            if not await recover(page):
                await page.screenshot(path=f"{OUT}/{job.tag}_wd_error.png", full_page=True)
                job.report["result"] = "NOT SUBMITTED: Workday error page ('Something went wrong') after two reloads"; return job.report
            if await page.locator(CAPTCHA).count():
                job.report["result"] = "NOT SUBMITTED: captcha/bot check in the form (not bypassed)"; return job.report
            body = await text(page)
            if APPLIED.search(body):
                job.report["result"] = "ALREADY APPLIED on this company's Workday site"; return job.report
            raw, step = await step_raw(page), await active_step(page)
            if re.search(r"review", step, re.I) or await page.locator(A("applyFlowReviewPage")).count():
                log(job, "at Review"); return await at_review(page, job, item)
            log(job, f"step: {step or '?'}")
            if re.search(r"experience", step, re.I): await experience_page(page, job)
            missing = await fill_page(page, job)
            if missing:
                job.report["unanswered"] = missing
                await page.screenshot(path=f"{OUT}/{job.tag}_wd_missing.png", full_page=True)
                job.report["result"] = "NOT SUBMITTED: unanswered required questions"; return job.report
            r = await click_next(page)
            if r == "submit":   # the footer button reads Submit (or nothing): never clicked here
                if await page.locator(A("applyFlowReviewPage")).count(): log(job, "footer button reads Submit: at Review"); return await at_review(page, job, item)
                await page.screenshot(path=f"{OUT}/{job.tag}_wd_error.png", full_page=True)
                job.report["result"] = f"NOT SUBMITTED: the Next button on step '{step}' reads Submit or is blank; stopped without clicking"; return job.report
            if r == "none":
                job.report["result"] = f"NOT SUBMITTED: no Next button on step '{step}'"; return job.report
            adv = await wait_advance(page, raw)
            if adv == "errors":
                errs = await form_errors(page)
                if any(re.search(r"already exists for this application", e, re.I) for e in errs) and ("stale", raw) not in repaired:
                    # the form was filled before the draft had loaded into it: reload the step and fill it again (once)
                    repaired.add(("stale", raw)); log(job, f"stale form on '{step}' ({errs[0][:80]}): reloading the step")
                    await page.reload(wait_until="domcontentloaded", timeout=60000); await page.wait_for_timeout(3000)
                    continue
                if raw in repaired:
                    job.report["errors"] = errs; await page.screenshot(path=f"{OUT}/{job.tag}_wd_error.png", full_page=True)
                    job.report["result"] = "NOT SUBMITTED: form errors"; return job.report
                repaired.add(raw)
                log(job, f"Workday errors on '{step}': {errs[:4]}; filling the step once more")
                need = {k for k, rx in (("work", r"work experience"), ("edu", r"education"), ("lang", r"\blanguage\b")) if any(re.search(rx, e, re.I) for e in errs)}
                if need: await experience_page(page, job, need)
                continue
            if adv == "stuck":
                stuck += 1
                if stuck >= 2:
                    await page.screenshot(path=f"{OUT}/{job.tag}_wd_error.png", full_page=True)
                    job.report["result"] = f"NOT SUBMITTED: step '{step}' did not advance"; return job.report
        job.report["result"] = "NOT SUBMITTED: too many steps"
        return job.report
    except Exception as e:
        job.report["result"] = f"ERROR {type(e).__name__}: {str(e)[:200]}"
        try: await page.screenshot(path=f"{OUT}/{job.tag}_wd_exception.png", full_page=True)
        except Exception: pass
        return job.report
    finally:
        json.dump(job.report, open(rp, "w"), indent=1)
        print(json.dumps({k: job.report[k] for k in ("tag", "ats", "url", "submitted", "result", "unanswered", "errors")})[:1500], flush=True)
        try: await page.close()
        except Exception: pass

async def main():
    q = json.load(open(sys.argv[1])); s = secret()
    async with async_playwright() as p:
        br = await p.chromium.launch(headless=not HEADED)
        ctx = await br.new_context(ignore_https_errors=True, user_agent=UA, viewport={"width": 1280, "height": 1800}, locale="en-US", timezone_id="America/Los_Angeles")
        for n, item in enumerate(q):
            rp = f"{OUT}/{item['tag']}_wd_report.json"
            if os.path.exists(rp):
                try:
                    rr = json.load(open(rp))
                    if rr.get("submitted") or "ALREADY APPLIED" in (rr.get("result") or ""): continue
                except Exception: pass
            await run_one(ctx, item, s)
            if n < len(q) - 1:
                g = random.uniform(*PACE); print(f"PACE waiting {int(g)}s before the next application", flush=True); await asyncio.sleep(g)
        await br.close()

if __name__ == "__main__":
    asyncio.run(main())
