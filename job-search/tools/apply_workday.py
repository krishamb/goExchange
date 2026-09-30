"""Workday application filler (company career sites on *.myworkdayjobs.com / *.myworkdaysite.com).

usage: apply_workday.py <queue.json> [--submit] [--headed] [--pace MIN MAX]
  queue items: {"url", "tag", "title", "company"} (other keys are ignored)

Answers come from the same reviewed rule tables as apply.py (TEXT_RULES / CHOICE_RULES), so a fix there applies here too.
Every application stops at Workday's Review page and writes out/<tag>_wd_review.json (every question and answer);
it is submitted only when out/<tag>_wd_approve.txt says OK. A required question with no rule is never guessed:
the job is reported as NOT SUBMITTED and left for the applicant. Captchas and bot checks are never bypassed: if one
appears, the job is reported and skipped.
Accounts: one Workday candidate account per company tenant, created with the applicant's email; the password lives
only in JOBS_DIR/wd_secret.json (never in the repository). If a tenant asks to verify the email, the filler writes
out/<tag>_verify_request.json and waits for the link in out/<tag>_verify.txt."""
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
exec(_seg("TEXT_RULES=[", "\ndef pick("), G)
exec(_seg("def pick(", "\nLABEL_JS"), G)
exec(_seg("EDU_START=", "\nasync def is_edu_date"), G)
exec(_seg("def _match(", "\nasync def open_menu"), G)
exec(_seg("HEAR_Q=", "\nasync def choose_react_select"), G)
exec(_seg("NEVER_APPLY=", "\n"), G)
TEXT_RULES, CHOICE_RULES, pick, best_index, mask_hear, edu_value, NEVER_APPLY = (G[k] for k in ("TEXT_RULES", "CHOICE_RULES", "pick", "best_index", "mask_hear", "edu_value", "NEVER_APPLY"))
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
async def listbox_choose(page, button, prefs, label):
    """Workday single-select: a button with aria-haspopup=listbox; options are [role=option] in a popup."""
    try:
        await button.scroll_into_view_if_needed(timeout=3000); await button.click(timeout=4000)
        await page.wait_for_timeout(700)
        opts = page.locator('[role="listbox"] [role="option"]:visible, ul[role="listbox"] li:visible')
        n = await opts.count(); texts = []
        for i in range(min(n, 200)):
            try: texts.append((await opts.nth(i).inner_text()).strip())
            except Exception: texts.append("")
        usable = mask_hear(texts, label)
        for pref in prefs:
            k = best_index(usable, pref)
            if k is not None:
                await opts.nth(k).click(timeout=4000); await page.wait_for_timeout(400); return texts[k], texts
        await page.keyboard.press("Escape")
        return None, texts
    except Exception:
        return None, []
async def prompt_choose(page, box, typed, prefs, label):
    """Workday multiselect prompt (e.g. How Did You Hear About Us?): open it, click the matching menu item (drilling
    into a category when it opens a sub-list), and verify the field now shows '1 item selected'."""
    field = box.locator("xpath=ancestor-or-self::*[starts-with(@data-automation-id,'formField-')][1]")
    async def items():
        loc = page.locator('[data-automation-id="menuItem"][role="option"]:visible')
        n = await loc.count(); t = []
        for i in range(min(n, 120)):
            try: t.append((await loc.nth(i).inner_text()).strip())
            except Exception: t.append("")
        return loc, t
    async def selected():
        try: return re.search(r"[1-9]\d* items? selected", await field.inner_text(timeout=2000)) is not None and not re.search(r"^\s*0 items selected", await field.inner_text(timeout=2000))
        except Exception: return False
    try:
        await box.scroll_into_view_if_needed(timeout=3000); await box.click(timeout=3000); await page.wait_for_timeout(1500)
        picked = None
        for depth in range(3):
            loc, texts = await items()
            usable = mask_hear(texts, label)
            k = next((best_index(usable, p) for p in prefs if best_index(usable, p) is not None), None)
            if k is None and depth > 0:   # inside a category: take its first real option
                k = next((i for i, t in enumerate(usable) if t), None)
            if k is None: break
            picked = texts[k]
            await loc.nth(k).click(timeout=4000); await page.wait_for_timeout(1500)
            if await selected(): break
        await page.keyboard.press("Escape"); await page.wait_for_timeout(300)
        return (picked if await selected() else None), []
    except Exception:
        return None, []

HEAR_PREFS = ["Company Website", "Company Career Site", "Career Site", "Careers Website", "Corporate Website", "Company Careers Page", "Website", "Careers Page", "Job Board", "Internet", "Online", "Other"]
STATE_PREFS = ["California", "CA"]

def choice_for(label):
    v = pick(label, CHOICE_RULES)
    if v is None: return None
    return v if isinstance(v, list) else [v]
def text_for(label):
    ev = edu_value(label)
    if ev is not None: return str(ev)
    v = pick(label, TEXT_RULES)
    return v if isinstance(v, str) else None

FIELD_JS = r"""()=>{
  const out=[];
  for (const f of document.querySelectorAll('[data-automation-id^="formField-"]')) {
    if (!f.offsetParent) continue;
    const id=f.getAttribute('data-automation-id').replace('formField-','');
    const lab=(f.querySelector('legend, label, [data-automation-id="richText"]')||{}).innerText||'';
    const req=/\*/.test(lab) || !!f.querySelector('[aria-required="true"], [required]');
    let kind='other';
    if (f.querySelector('button[aria-haspopup="listbox"]')) kind='listbox';
    else if (f.querySelector('[data-automation-id="multiselectInputContainer"], [data-automation-id="searchBox"]')) kind='prompt';
    else if (f.querySelector('input[type="radio"]')) kind='radio';
    else if (f.querySelector('input[type="checkbox"]')) kind='checkbox';
    else if (f.querySelector('textarea')) kind='textarea';
    else if (f.querySelector('[data-automation-id="dateSectionMonth-input"], [data-automation-id="dateSectionYear-input"]')) kind='date';
    else if (f.querySelector('input[type="text"], input:not([type]), input[type="tel"], input[type="email"], input[type="number"]')) kind='text';
    let val='';
    const b=f.querySelector('button[aria-haspopup="listbox"]'); if (b) val=(b.innerText||'').trim();
    const i=f.querySelector('input[type="text"], input:not([type]), textarea, input[type="tel"], input[type="number"]'); if (i && i.value) val=i.value;
    const sel=f.querySelectorAll('[data-automation-id="selectedItem"]'); if (sel.length) val=[...sel].map(s=>s.innerText.trim()).join('; ');
    const checked=[...f.querySelectorAll('input[type="radio"]:checked, input[type="checkbox"]:checked')]; if (checked.length) val=val||'checked';
    out.push({id, label:lab.replace(/\s+/g,' ').replace(/\*$/,'').trim(), req, kind, val});
  }
  return out;}"""

class Job:
    def __init__(self, item):
        self.item = item; self.tag = item["tag"]; self.url = item["url"]; self.title = item.get("title", "")
        self.report = {"tag": self.tag, "ats": "workday", "url": self.url, "submitted": False, "result": "", "answers": {}, "unanswered": [], "errors": [], "pages": []}
    def ans(self, label, val): self.report["answers"][label[:120]] = val

async def fill_page(page, job):
    """Fill every visible Workday form field on the current step. Returns the list of required fields left empty."""
    step = ""
    try: step = (await page.locator(A("progressBarActiveStep")).first.inner_text(timeout=2000)).strip()
    except Exception: pass
    job.report["pages"].append(step)
    fields = await page.evaluate(FIELD_JS)
    missing = []
    for f in fields:
        fid, lab, kind, cur = f["id"], f["label"], f["kind"], f["val"]
        box = page.locator(A(f"formField-{fid}")).first
        low = (lab or fid).lower()
        # already answered (Workday keeps answers from earlier applications to the same tenant)
        if cur and cur.lower() not in ("select one", "") and kind in ("listbox", "text", "textarea", "prompt"):
            job.ans(lab or fid, cur); continue
        done = None
        # ---- known Workday fields first
        if fid in ("legalNameSection_firstName", "firstName") or re.search(r"^given name|^first name", low): done = await fill(page, box.locator("input").first, FIRST) and FIRST
        elif fid in ("legalNameSection_lastName", "lastName") or re.search(r"^family name|^last name", low): done = await fill(page, box.locator("input").first, LAST) and LAST
        elif fid in ("addressSection_city", "city"): done = await fill(page, box.locator("input").first, "Santa Clara") and "Santa Clara"
        elif fid in ("addressSection_postalCode", "postalCode"): done = await fill(page, box.locator("input").first, "95050") and "95050"
        elif fid in ("addressSection_addressLine1", "addressLine1"):
            if f["req"]: missing.append(lab or fid)   # applicant: city only, no street address
            continue
        elif fid in ("phone-extension", "phoneExtension") or re.search(r"extension", low):
            continue
        elif fid in ("phone-number", "phoneNumber"): done = await fill(page, box.locator("input").first, re.sub(r"\D", "", P["phone"])[-10:]) and P["phone"]
        elif fid in ("phone-device-type", "phoneType"):
            done, _ = await listbox_choose(page, box.locator('button[aria-haspopup="listbox"]').first, ["Mobile", "Cell", "Personal Cell", "Home"], lab)
        elif fid in ("addressSection_countryRegion", "countryRegion"):
            done, _ = await listbox_choose(page, box.locator('button[aria-haspopup="listbox"]').first, STATE_PREFS, lab)
        elif fid in ("country", "countryDropdown"):
            done, _ = await listbox_choose(page, box.locator('button[aria-haspopup="listbox"]').first, ["United States of America", "United States"], lab)
        elif fid in ("source", "sourcePrompt") or re.search(r"how did you hear", low):
            b = box.locator('input').first
            done, _ = await prompt_choose(page, b, "", HEAR_PREFS, lab)
        elif fid in ("previousWorker", "candidateIsPreviousWorker") or re.search(r"previously (been )?(employed|worked)|former employee|worked for .{0,40} before", low):
            done = await pick_radio(page, box, ["No"], lab)
        elif fid in ("linkedinQuestion",) or "linkedin" in low: done = await fill(page, box.locator("input").first, P["linkedin"]) and P["linkedin"]
        elif kind == "listbox":
            prefs = choice_for(lab)
            if prefs: done, opts = await listbox_choose(page, box.locator('button[aria-haspopup="listbox"]').first, prefs, lab)
        elif kind == "radio":
            prefs = choice_for(lab)
            if prefs: done = await pick_radio(page, box, prefs, lab)
        elif kind == "prompt":
            prefs = choice_for(lab)
            if prefs:
                b = box.locator(f'{A("searchBox")}, input').first
                done, _ = await prompt_choose(page, b, prefs[0], prefs, lab)
        elif kind == "checkbox":
            done = await checkbox_field(page, box, lab)
        elif kind in ("text", "textarea"):
            v = text_for(lab)
            if v: done = await fill(page, box.locator("textarea, input").first, v) and v
        elif kind == "date":
            done = await date_field(page, box, lab)
        if done: job.ans(lab or fid, done)
        elif f["req"]: missing.append(lab or fid)
    return missing

async def pick_radio(page, box, prefs, lab):
    radios = box.locator('input[type="radio"]'); n = await radios.count(); texts = []
    for i in range(n):
        r = radios.nth(i)
        t = await r.evaluate("(el)=>{const l=el.id&&document.querySelector('label[for=\"'+CSS.escape(el.id)+'\"]');return (l?l.innerText:(el.closest('label')||el.parentElement).innerText||'').trim()}")
        texts.append(t)
    for pref in prefs:
        k = best_index(mask_hear(texts, lab), pref)
        if k is not None:
            rid = await radios.nth(k).get_attribute("id")
            try:
                if rid: await page.locator(f'label[for="{rid}"]').first.click(timeout=3000)
                else: await radios.nth(k).click(force=True, timeout=3000)
            except Exception:
                await radios.nth(k).evaluate("(el)=>{const l=el.id&&document.querySelector('label[for=\"'+CSS.escape(el.id)+'\"]');(l||el).click()}")
            await page.wait_for_timeout(300)
            if not await radios.nth(k).is_checked(): return None
            return texts[k]
    return None

DISC = re.compile(r"non-?compete|non-?solicit|financial interest|conflict of interest|relatives?\b|related to|family member|government official|convicted|felony|i am (currently )?subject to|i (currently )?hold|disabilit(y|ies) and have|i have a disability|yes, i have", re.I)
ACK = re.compile(r"i (have read|acknowledge|agree|understand|consent|certify)|terms and conditions|privacy (notice|policy)|^accept\*?$|i accept|no, i do not have a disability|i do not want to answer", re.I)
async def checkbox_field(page, box, lab):
    boxes = box.locator('input[type="checkbox"]'); n = await boxes.count(); picked = []
    for i in range(n):
        c = boxes.nth(i)
        t = await c.evaluate("(el)=>{const l=el.id&&document.querySelector('label[for=\"'+CSS.escape(el.id)+'\"]');return (l?l.innerText:(el.closest('label')||el.parentElement).innerText||'').trim()}")
        if DISC.search(t): continue
        if ACK.search(t) or (n == 1 and ACK.search(lab or "")):
            try: await c.check(timeout=3000)
            except Exception: await c.evaluate("(el)=>{const l=el.id&&document.querySelector('label[for=\"'+CSS.escape(el.id)+'\"]');(l||el).click()}")
            picked.append(t or lab)
    return "; ".join(picked) if picked else None

async def date_field(page, box, lab):
    today = datetime.date.today()
    if re.search(r"today|signature date|date signed|^date$", (lab or "").lower()):
        m, d, y = str(today.month), str(today.day), str(today.year)
    else:
        return None
    for aid, v in (("dateSectionMonth-input", m), ("dateSectionDay-input", d), ("dateSectionYear-input", y)):
        loc = box.locator(A(aid))
        if await loc.count():
            try: await loc.first.click(timeout=2000); await loc.first.type(v, delay=40)
            except Exception: pass
    return f"{m}/{d}/{y}"

async def experience_page(page, job):
    """My Experience: upload the resume (Workday may parse it) and add LinkedIn. Work history / education entries are
    filled only where the section is required and empty."""
    up = page.locator(f'input[type="file"]{A("file-upload-input-ref")}, {A("file-upload-input-ref")}, input[type="file"]')
    if await up.count():
        try:
            await up.first.set_input_files(resume_for(job.title)); await page.wait_for_timeout(4000)
            job.ans("Resume", os.path.basename(resume_for(job.title)))
        except Exception as e: job.report["errors"].append(f"resume upload: {str(e)[:80]}")

async def auth(page, job, s):
    """Sign in or create the tenant account (applicant's plan): one sign-in attempt with his Workday login
    (wf_creds workday.email + first password); if that fails, create the account with workday.new_account_email /
    new_account_password (Gmail, so a verification link can be read); an existing Gmail account is signed in instead.
    Returns 'ok', 'verify', 'blocked' or 'fail'. Never more than one attempt per credential (no lockouts)."""
    ten = tenant_of(job.url)
    try: await page.locator(A("signInContent")).first.wait_for(state="visible", timeout=25000)
    except Exception: pass
    await page.wait_for_timeout(1000)
    if await page.locator(CAPTCHA).count(): return "blocked"
    known = s["tenants"].get(ten) or {}
    async def signed_in():
        await page.wait_for_timeout(5000)
        body = await text(page)
        if re.search(r"already applied for this job|you.ve already applied", body, re.I): return True
        if re.search(r"invalid|incorrect|wrong (email|password)|try again|could not sign|account (is )?locked", body, re.I): return False
        if await page.locator(f'input{A("password")}:visible').count(): return False
        try:
            st = (await page.locator(A("progressBarActiveStep")).first.inner_text(timeout=4000)).lower()
            return "sign in" not in st and "create account" not in st
        except Exception: return False
    async def sign_in(email, pw):
        if await page.locator(A("signInLink")).count() and not await page.locator(A("signInSubmitButton")).count():
            await click_button(page, "signInLink"); await page.wait_for_timeout(1500)
        if not await page.locator(f'input{A("password")}').count():   # social chooser first: pick "Sign in with email"
            await click_button(page, "SignInWithEmailButton", timeout=3000) or await click_button(page, name=r"sign in with email", timeout=3000)
            await page.wait_for_timeout(1500)
        await fill(page, page.locator(f'input{A("email")}').first, email)
        await fill(page, page.locator(f'input{A("password")}').first, pw)
        if await page.locator(CAPTCHA).count(): return None
        await click_button(page, "signInSubmitButton") or await click_button(page, name=r"^sign in$")
        return await signed_in()
    def remember(email, pw_key):
        s["tenants"][ten] = {"email": email, "pw_key": pw_key, "ts": int(time.time())}; save_secret(s)
    creds = {"login": (s["email"], s["passwords"][0]), "new": (s.get("new_account_email") or P["email"], s.get("new_account_password") or s["passwords"][0])}
    if known.get("pw_key") in creds:
        e, pw = creds[known["pw_key"]]
        r = await sign_in(e, pw)
        return "ok" if r else ("blocked" if r is None else "fail")
    # 1) one attempt with the applicant's Workday login
    r = await sign_in(*creds["login"])
    if r is None: return "blocked"
    if r: remember(creds["login"][0], "login"); return "ok"
    # 2) create the account with the new-account email (Gmail)
    await page.goto(page.url, wait_until="domcontentloaded", timeout=60000)
    try: await page.locator(A("signInContent")).first.wait_for(state="visible", timeout=25000)
    except Exception: pass
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
    await page.wait_for_timeout(6000)
    body = await text(page)
    if re.search(r"already (exists|in use|registered)|account with this email", body, re.I):
        r = await sign_in(e, pw)
        if r: remember(e, "new"); return "ok"
        return "fail"
    if re.search(r"email has been sent|verify (your )?(email|account)|verification (email|link)|check your email|resend account verification", body, re.I):
        remember(e, "new"); return "verify"
    try:
        st = (await page.locator(A("progressBarActiveStep")).first.inner_text(timeout=4000)).lower()
        if "sign in" not in st and "create account" not in st: remember(e, "new"); return "ok"
    except Exception: pass
    return "fail"

async def wait_file(path, secs):
    end = time.time() + secs
    while time.time() < end:
        if os.path.exists(path):
            v = open(path).read().strip()
            if v: return v
        await asyncio.sleep(3)
    return None

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
        if not await click_button(page, "adventureButton", timeout=15000) and not await click_button(page, name=r"^apply$"):
            job.report["result"] = "NOT SUBMITTED: no Apply button"; return job.report
        await page.wait_for_timeout(2500)
        if await page.locator(A("applyManually")).count(): await click_button(page, "applyManually"); await page.wait_for_timeout(2500)
        a = await auth(page, job, s)
        if a == "blocked": job.report["result"] = "NOT SUBMITTED: captcha/bot check at sign-in (not bypassed)"; return job.report
        if a == "verify":
            req = f"{OUT}/{job.tag}_verify_request.json"; ans = f"{OUT}/{job.tag}_verify.txt"
            json.dump({"tag": job.tag, "email": s["email"], "url": job.url, "tenant": tenant_of(job.url), "ts": time.time()}, open(req, "w"), indent=1)
            print(f"VERIFY REQUEST {job.tag}", flush=True)
            link = await wait_file(ans, VERIFY_WAIT)
            if not link: job.report["result"] = "NOT SUBMITTED: email verification link not received"; return job.report
            await page.goto(link, wait_until="domcontentloaded", timeout=60000); await page.wait_for_timeout(4000)
            await page.goto(job.url, wait_until="domcontentloaded", timeout=60000); await page.wait_for_timeout(3000)
            await click_button(page, "adventureButton"); await page.wait_for_timeout(2000)
            if await page.locator(A("applyManually")).count(): await click_button(page, "applyManually"); await page.wait_for_timeout(2000)
            if await auth(page, job, s) != "ok": job.report["result"] = "NOT SUBMITTED: sign-in failed after verification"; return job.report   # auth() signs in with the remembered new-account login
        elif a == "fail":
            await page.screenshot(path=f"{OUT}/{job.tag}_wd_auth.png", full_page=True)
            job.report["result"] = "NOT SUBMITTED: could not create an account or sign in"; return job.report
        if re.search(r"already applied for this job|you.ve already applied", await text(page), re.I):
            job.report["result"] = "ALREADY APPLIED on this company's Workday site"; return job.report
        # ---- the wizard
        for _ in range(12):
            await page.wait_for_timeout(2500)
            if await page.locator(CAPTCHA).count():
                job.report["result"] = "NOT SUBMITTED: captcha/bot check in the form (not bypassed)"; return job.report
            body = await text(page)
            if re.search(r"application (was )?submitted|thank you for (applying|your application)|successfully submitted|congratulations", body, re.I):
                job.report["submitted"] = True; job.report["result"] = body[:300]; return job.report
            step = ""
            try: step = (await page.locator(A("progressBarActiveStep")).first.inner_text(timeout=3000)).strip()
            except Exception: pass
            if re.search(r"experience", step, re.I): await experience_page(page, job)
            if re.search(r"review", step, re.I):
                review = {"tag": job.tag, "url": job.url, "title": job.title, "company": item.get("company"), "ts": time.time(), "answers": job.report["answers"], "review_text": body[:12000]}
                json.dump(review, open(f"{OUT}/{job.tag}_wd_review.json", "w"), indent=1)
                await page.screenshot(path=f"{OUT}/{job.tag}_wd_review.png", full_page=True)
                if not SUBMIT: job.report["result"] = "DRY RUN: stopped at Review"; return job.report
                ap = f"{OUT}/{job.tag}_wd_approve.txt"
                if os.path.exists(ap): os.remove(ap)
                print(f"WD REVIEW {job.tag}", flush=True)
                v = await wait_file(ap, REVIEW_WAIT)
                if not v or not v.upper().startswith("OK"):
                    job.report["result"] = f"NOT SUBMITTED: review {'rejected: ' + v if v else 'not approved in time'}"; return job.report
                await click_button(page, "pageFooterNextButton") or await click_button(page, "bottom-navigation-next-button") or await click_button(page, name=r"^submit$")
                await page.wait_for_timeout(6000)
                continue
            missing = await fill_page(page, job)
            if missing:
                job.report["unanswered"] = missing
                await page.screenshot(path=f"{OUT}/{job.tag}_wd_missing.png", full_page=True)
                job.report["result"] = "NOT SUBMITTED: unanswered required questions"; return job.report
            if not (await click_button(page, "pageFooterNextButton", timeout=6000) or await click_button(page, "bottom-navigation-next-button", timeout=3000) or await click_button(page, name=r"save and continue|^next$|^continue$")):
                job.report["result"] = f"NOT SUBMITTED: no Next button on step '{step}'"; return job.report
            await page.wait_for_timeout(3000)
            errs = page.locator(f'{A("errorMessage")}:visible, [role="alert"]:visible')
            if await errs.count():
                e = [(await errs.nth(i).inner_text()).strip() for i in range(min(await errs.count(), 8))]
                e = [x for x in e if x]
                if e:
                    job.report["errors"] = e; await page.screenshot(path=f"{OUT}/{job.tag}_wd_error.png", full_page=True)
                    job.report["result"] = "NOT SUBMITTED: form errors"; return job.report
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
