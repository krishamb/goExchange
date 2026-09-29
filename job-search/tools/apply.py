#!/usr/bin/env python3
"""Generic job-application filler/submitter for Lever, Greenhouse, Ashby and Wellfound.
Usage: python3 job-search/tools/apply.py <lever|greenhouse|ashby|wellfound> <url> <tag> [--submit] [--answers file.json]
Profile/credentials are read from JOBS_DIR (default: session scratchpad), never from this repo.
"""
import asyncio, sys, json, os, re, time
from playwright.async_api import async_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cover
JOBS_DIR=os.environ.get("JOBS_DIR","/tmp/claude-0/-home-user-goExchange/8d20ffb7-2488-5f8f-a666-35334b9e3ba6/scratchpad/f")
OUT=os.path.join(JOBS_DIR,"out"); os.makedirs(OUT,exist_ok=True)
JOBS_DIR=os.path.expanduser(JOBS_DIR)
P=json.load(open(os.path.join(JOBS_DIR,"profile.json")))
for _k in ("resume","cover_letter"):
    if P.get(_k): P[_k]=os.path.expanduser(P[_k])
ANS=json.load(open(os.path.join(JOBS_DIR,"answers.json"))) if os.path.exists(os.path.join(JOBS_DIR,"answers.json")) else {}
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
HEADED="--headed" in sys.argv
import shutil, platform
if HEADED and platform.system()=="Linux" and not os.environ.get("DISPLAY") and shutil.which("xvfb-run"):
    os.execvp("xvfb-run",["xvfb-run","-a","-s","-screen 0 1280x2000x24",sys.executable]+sys.argv)
submit="--submit" in sys.argv
BATCH = sys.argv[1]=="batch"
if BATCH:
    JOBS=json.load(open(sys.argv[2])); ats=url=tag=None; extra={}
elif sys.argv[1]=="outlook-test":
    ats=url=tag=None; extra={}
else:
    ats,url,tag=sys.argv[1],sys.argv[2],sys.argv[3]
    extra=json.load(open(sys.argv[sys.argv.index("--answers")+1])) if "--answers" in sys.argv else {}
first,last=P["name"].split(" ",1)
# label regex -> value ; order matters
TEXT_RULES=[
 (r"first and last name|legal name|full legal name|^(full )?name\b|^your name|_systemfield_name", P["name"]),
 (r"first ?name", first),(r"last ?name|surname|family name", last),
 (r"address", P["location"]),
 (r"preferred name", first),(r"e-?mail", P["email"]),(r"phone|mobile", P["phone"]),
 (r"linkedin", P["linkedin"]),(r"github", P["github"]),(r"portfolio|website|personal site", P["github"]),
 (r"current (company|employer)|most recent (company|employer)|^company$|^employer$", P["org"]),
 (r"current (title|role)|job title|^title$", "CTO & Technical Co-Founder / Principal Architect"),
 (r"location|city|where (are you|do you) (based|live|located)", P["location"]),
 (r"salary|compensation|pay expectation|desired (base|comp)|expected (base|salary|comp)", "$300,000 - $350,000 base"),
 (r"start date|available to start|availability|notice period", "Immediately"),
 (r"years? of (relevant |professional |total )?experience|how many years", "25"),
 (r"how did you hear|referral source|source", "Company careers page"),
 (r"^why\b|why (do you want|are you interested|.*join|.*this role|.*us)|interest(ed)? in (this|the) (role|position|company)|tell us (a little )?about yourself|cover letter|anything else|additional information|why .*good fit|what excites you", ANS.get("why_us","")),
 (r"greatest (impact|achievement)|proudest|accomplishment", ANS.get("impact","")),
 (r"work environment|thrive|attributes", ANS.get("environment","")),
 (r"pronoun", "He/him"),
 (r"university|school|college|alma mater", "University of Madras"),
 (r"degree|field of study|major", "Bachelor of Engineering, Computer Science and Engineering"),
]
CHOICE_RULES=[
 (r"location \(city\)|^location$|current location|^city$", ["Santa Clara, California","Santa Clara, CA","Santa Clara"]),
 (r"sponsor", ["No","no"]),
 (r"interviewed .*before|applied .*before|previously (applied|interviewed)", ["No","no"]),
 (r"in[- ]person|open to working in|come into the office|days? (a|per) week", ["Yes","yes"]),
 (r"ai policy|use of ai|ai assistance|ai tools? (in|during)|without (the use of )?ai|generative ai", ["__ASK__"]),
 (r"authori[sz]ed to work|legally (able|eligible|authorized)|work authorization|eligible to work|right to work", ["Yes","yes"]),
 (r"citizen", ["Yes","U.S. Citizen","US Citizen"]),
 (r"relocat", ["Yes","yes"]),
 (r"remote|hybrid|on-?site|in[- ]office|work from|commut", ["Yes","yes","Hybrid","Remote"]),
 (r"gender|sex\b|\bmale\b|female|\bman\b|woman", ["Male","Man"]),
 (r"hispanic|latino", ["No","I am not Hispanic or Latino","Not Hispanic or Latino"]),
 (r"\brace\b|racial|ethnic|hispanic|asian|caucasian|african", ["I don't wish to answer","Decline To Self Identify","Decline to self identify","Decline to self-identify","Decline","Prefer not to say","Prefer not to answer","I do not wish to answer","I don't wish"]),
 (r"veteran", ["I am not a protected veteran","Not a protected veteran","I am not a veteran","No","Decline To Self Identify"]),
 (r"disabilit", ["No, I do not have a disability","No, I don't have a disability","No","I do not have a disability","I don't wish to answer"]),
 (r"18\+|18 (years|or older)|age of 18|over 18|at least 18", ["Yes","yes"]),
 (r"background check|drug|non-?compete|agreement|acknowledge|certify|consent|privacy|terms|policy|subscribe|agree", ["Yes","I agree","I acknowledge","I consent","yes"]),
 (r"how did you hear|source", ["Company Website","Company website","Careers page","Career Page","Other","Job Board","Other/Not Listed"]),
 (r"school|university|college", ["University of Madras","Other","University"]),
 (r"discipline|major|field of study", ["Computer Science","Computer Engineering","Engineering","Other"]),
 (r"degree|education|highest level", ["Bachelor's Degree","Undergraduate/Bachelor's degree","Bachelor's","Bachelors","Bachelor"]),
 (r"previously (applied|worked|employed)|currently employed by|worked for .* before|former employee|current employee", ["No","no"]),
 (r"security clearance|clearance", ["No","None","no"]),
 (r"visa", ["No","no"]),
 (r"country", ["United States","United States of America","USA"]),
 (r"state|province", ["California","CA"]),
 (r"experience with|familiar|proficien|years", ["10+ years","10+","Expert","Yes"]),
]
def pick(label,rules):
    l=label.lower()
    for pat,val in rules:
        if re.search(pat,l): return val
    return None
LABEL_JS=r"""
(el)=>{let t='';
 const byId=(id)=>{const l=document.querySelector('label[for="'+CSS.escape(id)+'"]'); return l? l.innerText:'';};
 const byLabelledBy=(e)=>{const a=e.getAttribute('aria-labelledby'); if(!a) return ''; return a.split(/\s+/).map(i=>{const x=document.getElementById(i); return x? x.innerText:'';}).join(' ');};
 if(el.id) t=byId(el.id);
 if(!t){const l=el.closest('label'); if(l) t=l.innerText;}
 if(!t && el.getAttribute('aria-label')) t=el.getAttribute('aria-label');
 if(!t) t=byLabelledBy(el);
 if(!t){const inp=el.querySelector('input[aria-labelledby], input[id], select[id]'); if(inp){ t=byLabelledBy(inp) || (inp.id? byId(inp.id):''); }}
 if(!t){const fs=el.closest('fieldset'); if(fs){const lg=fs.querySelector('legend'); if(lg) t=lg.innerText;}}
 if(!t){let p=el.parentElement; for(let i=0;i<6&&p;i++){
    let lab=null; for(const c of p.querySelectorAll('label, legend')){ if(!c.contains(el) && !el.contains(c) && c.innerText.trim()){lab=c; break;} }
    if(!lab){ for(const c of p.querySelectorAll('.application-label, [class*="label"], [class*="Label"], h3, h4, .field-label, .question')){ if(c!==el && !c.contains(el) && !el.contains(c) && c.innerText.trim() && !/^select\.\.\.$/i.test(c.innerText.trim())){lab=c; break;} } }
    if(lab){t=lab.innerText; break;} p=p.parentElement;}}
 return (t||'').trim().replace(/\s+/g,' ').replace(/[✱*]/g,'').trim();}
"""
async def label_of(h): return await h.evaluate(LABEL_JS)
async def is_required(h):
    return await h.evaluate("(el)=>el.required||el.getAttribute('aria-required')==='true'||/\\*|✱|required/i.test((el.closest('label,fieldset,div')||{}).innerText||'')")
async def fill_text(page,h,val):
    try:
        await h.scroll_into_view_if_needed(timeout=3000)
        await h.click(timeout=3000); await h.fill(val)
        await h.dispatch_event("input"); await h.dispatch_event("change"); await h.press("Tab"); return True
    except Exception:
        try: await h.click(timeout=3000); await h.type(val,delay=10); await h.press("Tab"); return True
        except Exception: return False
async def autocomplete_fill(page,h,text,prefer):
    """Type into an autocomplete box and pick the first matching suggestion."""
    try:
        await h.scroll_into_view_if_needed(timeout=3000); await h.click(timeout=3000); await h.fill("")
        await h.type(text,delay=40); await page.wait_for_timeout(1800)
        opts=page.locator('[role="option"]:visible:not(.iti__country), [role="listbox"] li:visible, [class*="dropdown"] li:visible, [class*="option"]:visible, [class*="Option"]:visible, [class*="suggestion"]:visible')
        n=await opts.count()
        for i in range(min(n,30)):
            o=opts.nth(i)
            try:
                if await o.is_visible() and re.search(prefer,await o.inner_text(),re.I): await o.click(timeout=3000); await page.wait_for_timeout(500); return "picked"
            except Exception: pass
        for i in range(min(n,30)):
            o=opts.nth(i)
            try:
                if await o.is_visible(): await o.click(timeout=3000); await page.wait_for_timeout(500); return "picked-first"
            except Exception: pass
        await h.press("ArrowDown"); await h.press("Enter"); await page.wait_for_timeout(500); return "enter"
    except Exception: return None
async def choose_select(page,h,options_pref):
    opts=await h.evaluate("(s)=>[...s.options].map(o=>o.text.trim())")
    for pref in options_pref:
        for o in opts:
            if o and (o.lower()==pref.lower() or pref.lower() in o.lower()):
                try:
                    if await h.is_visible(): await h.select_option(label=o)
                    else: raise RuntimeError("hidden")
                    return o
                except Exception:
                    try:
                        await h.evaluate("(s,label)=>{for(const op of s.options){if(op.text.trim()===label){s.value=op.value; op.selected=true;}} s.dispatchEvent(new Event('input',{bubbles:true})); s.dispatchEvent(new Event('change',{bubbles:true})); if(window.jQuery){try{window.jQuery(s).trigger('change');}catch(e){}}}",o)
                        return o
                    except Exception: pass
    return None
OPT_SEL='[role="option"]:visible:not(.iti__country), [class*="select__option"]:visible, [class*="Select__option"]:visible'
async def visible_options(page):
    o=page.locator(OPT_SEL); n=await o.count(); t=[]
    for i in range(min(n,60)):
        try: t.append((await o.nth(i).inner_text()).strip())
        except Exception: t.append("")
    return o,t
def _match(t,pref):
    tl,pl=t.lower(),pref.lower()
    return tl==pl or tl.startswith(pl) or (pl in tl and len(pl)>=4)
async def choose_react_select(page,control,options_pref,label):
    """react-select: type the preferred answer into the inner input, pick the visible matching option (or Enter), verify."""
    if options_pref==["__ASK__"]: return None
    inp=control.locator('input[role="combobox"], input.select__input, input').first
    if not await inp.count(): return None
    async def current():
        try: return (await control.inner_text()).strip()
        except Exception: return ""
    try:
        for pref in options_pref[:4]:
            await inp.scroll_into_view_if_needed(timeout=3000); await inp.click(timeout=3000)
            await inp.press("Control+A"); await inp.press("Backspace"); await page.wait_for_timeout(200)
            await inp.type(pref[:30],delay=25); await page.wait_for_timeout(900)
            opts,texts=await visible_options(page)
            hit=None
            for i,t in enumerate(texts):
                if t and _match(t,pref): hit=i; break
            if hit is None and texts:
                # no textual match: maybe options are unfiltered (async search); pick none
                pass
            if hit is not None: await opts.nth(hit).click(timeout=3000)
            else: await inp.press("Enter")
            await page.wait_for_timeout(500)
            cur=await current()
            if cur and cur.lower()!="select..." and (pref.lower()[:6] in cur.lower() or (hit is not None)): return cur[:80]
            # not selected: clear and try next preference
            await inp.press("Control+A"); await inp.press("Backspace"); await page.keyboard.press("Escape")
        await page.keyboard.press("Escape")
    except Exception:
        try: await page.keyboard.press("Escape")
        except Exception: pass
    return None
def fetch_email_code(max_wait=150):
    """Return the latest 8-character verification code from the inbox configured in wf_creds.json {"imap":{"host","user","password"}}
    (Gmail: imap.gmail.com + an app password). Falls back to a terminal prompt when running interactively."""
    creds_path=os.path.join(JOBS_DIR,"wf_creds.json")
    cfg=(json.load(open(creds_path)).get("imap") if os.path.exists(creds_path) else None)
    if cfg:
        import imaplib, email, datetime
        deadline=time.time()+max_wait
        while time.time()<deadline:
            try:
                M=imaplib.IMAP4_SSL(cfg.get("host","imap.gmail.com")); M.login(cfg["user"],cfg["password"]); M.select("INBOX")
                since=(datetime.datetime.utcnow()-datetime.timedelta(days=1)).strftime("%d-%b-%Y")
                typ,data=M.search(None,f'(SINCE {since})'); ids=data[0].split()[-15:]
                best=None
                for i in reversed(ids):
                    typ,msg=M.fetch(i,"(RFC822)"); m=email.message_from_bytes(msg[0][1])
                    subj=str(m.get("Subject","")); body=""
                    for part in (m.walk() if m.is_multipart() else [m]):
                        if part.get_content_type() in ("text/plain","text/html"):
                            try: body+=part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8","ignore")
                            except Exception: pass
                    txt=re.sub(r"<[^>]+>"," ",subj+" "+body)
                    if re.search(r"verification code|security code|confirm you.re a human|application code",txt,re.I):
                        d=email.utils.parsedate_to_datetime(m.get("Date")) if m.get("Date") else None
                        if d and (datetime.datetime.now(d.tzinfo)-d).total_seconds()>900: continue   # older than 15 min
                        c=re.search(r"\b([A-Z0-9]{8})\b",txt)
                        if c: best=c.group(1); break
                M.logout()
                if best: return best
            except Exception as e: print("imap:",str(e)[:120])
            time.sleep(10)
        return None
    if sys.stdin.isatty():
        try: return input("Enter the 8-character verification code emailed to you (blank to skip): ").strip() or None
        except Exception: return None
    return None
BROWSER=None; OUTLOOK={"page":None}
def outlook_cfg():
    p=os.path.join(JOBS_DIR,"wf_creds.json")
    if not os.path.exists(p): return None
    c=json.load(open(p)).get("outlook")
    return c if c and c.get("email") and c.get("password") else None
CODE_RE=re.compile(r"\b([A-Z0-9]{8})\b")
def _codes_in(text):
    out=[]
    for m in re.finditer(r"code[^A-Za-z0-9]{0,120}([A-Za-z0-9]{8})\b",text,re.I|re.S): out.append(m.group(1))
    for m in CODE_RE.finditer(text): out.append(m.group(1))
    return [c for c in out if re.search(r"\d",c)] or out
async def outlook_page():
    """Open (once) a logged-in Outlook.com tab in its own browser context; reuse it for every code lookup."""
    if OUTLOOK["page"] and not OUTLOOK["page"].is_closed(): return OUTLOOK["page"]
    cfg=outlook_cfg()
    if not cfg or BROWSER is None: return None
    state=os.path.join(JOBS_DIR,"outlook_state.json")
    ctx=await BROWSER.new_context(ignore_https_errors=True,user_agent=UA,viewport={"width":1280,"height":900},storage_state=state if os.path.exists(state) else None)
    ctx.set_default_timeout(8000); page=await ctx.new_page()
    await page.goto("https://outlook.live.com/mail/0/",wait_until="domcontentloaded",timeout=60000); await page.wait_for_timeout(5000)
    for _ in range(6):
        if "outlook.live.com/mail" in page.url and await page.locator('[role="main"], #app, [aria-label="Search"]').count(): break
        try:
            e=page.locator('input[name="loginfmt"], input[type="email"]').first
            if await e.count() and await e.is_visible(): await e.fill(cfg["email"]); await page.locator('#idSIButton9, button[type="submit"]').first.click(timeout=4000); await page.wait_for_timeout(3000)
            for sel in ['button:has-text("Use your password")','a:has-text("Use your password")','a:has-text("Other ways to sign in")']:
                el=page.locator(sel).first
                if await el.count() and await el.is_visible(): await el.click(timeout=3000); await page.wait_for_timeout(2000)
            pw=page.locator('input[name="passwd"], input[type="password"]').first
            if await pw.count() and await pw.is_visible(): await pw.fill(cfg["password"]); await page.locator('#idSIButton9, button[type="submit"]').first.click(timeout=4000); await page.wait_for_timeout(5000)
            for sel in ['#idSIButton9','button:has-text("Yes")','button:has-text("Skip for now")','a:has-text("Skip for now")','button:has-text("Not now")','#iCancel','button:has-text("Cancel")','#iNext','button:has-text("Maybe later")']:
                el=page.locator(sel).first
                if await el.count() and await el.is_visible(): await el.click(timeout=3000); await page.wait_for_timeout(3000)
        except Exception: pass
        await page.wait_for_timeout(2000)
    if "outlook.live.com/mail" not in page.url:
        print("outlook: login did not complete (2-step verification or a sign-in challenge?); falling back to manual code entry")
        await page.screenshot(path=f"{OUT}/outlook_login_problem.png"); return None
    try: await ctx.storage_state(path=state)
    except Exception: pass
    OUTLOOK["page"]=page; return page
async def outlook_codes(page,query="verification code"):
    """Codes found in the newest few messages matching the search, newest first."""
    found=[]
    try:
        sb=page.locator('input[aria-label="Search"], #topSearchInput, input[placeholder*="Search"]').first
        await sb.click(timeout=5000); await sb.fill(""); await sb.type(query,delay=20); await sb.press("Enter"); await page.wait_for_timeout(4500)
        items=page.locator('[role="listbox"] [role="option"], div[data-convid]'); n=await items.count()
        for i in range(min(n,4)):
            try:
                await items.nth(i).click(timeout=4000); await page.wait_for_timeout(2500)
                body=await page.evaluate("()=>{const r=document.querySelector('[aria-label=\"Message body\"], #UniqueMessageBody, [role=\"document\"], .allowTextSelection'); return (r? r.innerText : document.body.innerText).slice(0,6000)}")
                found+=_codes_in(body)
            except Exception: pass
    except Exception as e: print("outlook search:",str(e)[:100])
    return found
async def enter_email_code(page,report,baseline=()):
    boxes=page.locator('input[autocomplete="one-time-code"], input[name*="security_code"], input[id*="security_code"], input[name*="verification"], [class*="security-code"] input, [class*="securityCode"] input, [class*="otp"] input')
    n=await boxes.count()
    if not n: return False
    code=None
    op=await outlook_page()
    if op:
        deadline=time.time()+180
        while time.time()<deadline and not code:
            for c in await outlook_codes(op):
                if c not in baseline: code=c; break
            if not code: await asyncio.sleep(12)
        report["code_source"]="outlook"
    if not code: code=await asyncio.get_event_loop().run_in_executor(None,fetch_email_code)
    if not code: report.setdefault("errors",[]).append("email verification code required (configure imap in wf_creds.json or run interactively)"); return False
    try:
        if n>=8:
            for i,ch in enumerate(code[:n]): await boxes.nth(i).fill(ch)
        else: await boxes.first.fill(code)
        report["code_entered"]=True; return True
    except Exception as e: report.setdefault("errors",[]).append(f"code entry failed: {e}"); return False
async def run():
    async with async_playwright() as p:
        launch_kw=dict(headless=not HEADED,args=["--no-sandbox","--ignore-certificate-errors"])
        if os.path.exists("/opt/pw-browsers/chromium"): launch_kw["executable_path"]="/opt/pw-browsers/chromium"   # cloud container
        b=await p.chromium.launch(**launch_kw)
        global BROWSER; BROWSER=b
        if sys.argv[1]=="outlook-test":
            op=await outlook_page()
            print("outlook login:", "ok" if op else "FAILED")
            if op:
                codes=await outlook_codes(op); print("codes found (newest first):",codes[:6])
                await op.screenshot(path=f"{OUT}/outlook_test.png")
            await b.close(); return
        jobs = JOBS if BATCH else [{"ats":ats,"url":url,"tag":tag,"answers":extra}]
        summary=[]
        for job in jobs:
            ctx=await b.new_context(ignore_https_errors=True,user_agent=UA,viewport={"width":1280,"height":2000},locale="en-US",timezone_id="America/Los_Angeles")
            ctx.set_default_timeout(8000)
            r=await run_one(ctx,job["ats"],job["url"],job["tag"],job.get("answers",{}),job.get("company"),job.get("title"))
            summary.append({k:r.get(k) for k in ("tag","ats","url","submitted","result","unanswered","captcha_present","errors")})
            print(json.dumps(summary[-1])); sys.stdout.flush()
            await ctx.close()
        json.dump(summary,open(f"{OUT}/batch_summary_{int(time.time())}.json","w"),indent=1)
        await b.close()
async def run_one(ctx,ats,url,tag,extra,company=None,jtitle=None):
    if True:
        page=await ctx.new_page(); report={"ats":ats,"url":url,"tag":tag,"filled":{},"chosen":{},"unanswered":[],"submitted":False,"result":""}
        cl_text=""; cl_pdf=None
        try:
            if ats=="wellfound":
                C=json.load(open(os.path.join(JOBS_DIR,"wf_creds.json")))
                await page.goto("https://wellfound.com/login",wait_until="domcontentloaded",timeout=60000); await page.wait_for_timeout(2500)
                await page.fill('input[type="email"]',C["email"]); await page.fill('input[type="password"]',C["password"])
                await page.locator('button[type="submit"], input[type="submit"]').first.click(timeout=10000); await page.wait_for_timeout(5000)
                await page.goto(url,wait_until="domcontentloaded",timeout=60000); await page.wait_for_timeout(4000)
                await page.locator('button:has-text("Apply Now"), button:has-text("Apply now"), button:has-text("Apply")').first.click(timeout=10000); await page.wait_for_timeout(3500)
                ta=page.locator('textarea').first
                if await ta.count(): await ta.fill(extra.get("note") or ANS.get("why_us","")); report["filled"]["note"]="ok"
                await page.screenshot(path=f"{OUT}/{tag}_filled.png",full_page=True)
                if submit:
                    await page.locator('button:has-text("Send application")').first.click(timeout=10000); await page.wait_for_timeout(6000)
                    report["submitted"]=True; report["result"]=(await page.evaluate("()=>document.body.innerText.slice(0,500)")).replace("\n"," | ")
                    await page.screenshot(path=f"{OUT}/{tag}_after.png",full_page=True)
                json.dump(report,open(f"{OUT}/{tag}_report.json","w"),indent=1); await page.close(); return report
            if ats=="greenhouse":
                m=re.search(r"greenhouse\.io/([^/]+)/jobs/(\d+)",url)
                if m: url=f"https://job-boards.greenhouse.io/embed/job_app?for={m.group(1)}&token={m.group(2)}"
            await page.goto(url,wait_until="domcontentloaded",timeout=60000); await page.wait_for_timeout(3500)
            for sel in ['button:has-text("Accept All")','button:has-text("Accept all")','button:has-text("Accept")','button:has-text("I agree")','button:has-text("Got it")','button:has-text("Decline All")']:
                try:
                    el=page.locator(sel).first
                    if await el.count() and await el.is_visible(): await el.click(timeout=2000); await page.wait_for_timeout(500); break
                except Exception: pass
            if ats=="ashby" and "/application" not in page.url:
                for sel in ['a:has-text("Apply for this Job")','a:has-text("Apply")','button:has-text("Apply")']:
                    try:
                        el=page.locator(sel).first
                        if await el.count(): await el.click(timeout=4000); await page.wait_for_timeout(3000); break
                    except Exception: pass
            if ats=="greenhouse":
                for sel in ['a:has-text("Apply")','button:has-text("Apply")','#apply_button']:
                    try:
                        el=page.locator(sel).first
                        if await el.count() and not await page.locator('input[type="file"]').count(): await el.click(timeout=4000); await page.wait_for_timeout(2500); break
                    except Exception: pass
            # per-posting cover letter
            try:
                ptitle=jtitle or re.sub(r"\s*[|@\-–].*$","",await page.title())
                pdesc=await page.evaluate("()=>document.body.innerText.slice(0,6000)")
                comp=company or re.sub(r"[-_]"," ",url.split("/")[3]).title()
                cl_text=cover.text(comp,ptitle,pdesc,P); cl_pdf=cover.pdf(f"{OUT}/{tag}_cover.pdf",cl_text); report["cover_category"]=cover.category(ptitle,pdesc)
            except Exception as e: report["cover_err"]=str(e)[:100]; cl_pdf=P.get("cover_letter")
            # resume upload first (autofill may follow)
            files=page.locator('input[type="file"]'); nf=await files.count()
            for i in range(nf):
                f=files.nth(i)
                try: lab=(await label_of(f)).lower()
                except Exception: lab="cover" if i==1 else ("resume" if i==0 else "")
                if not lab: lab="cover" if i==1 else ("resume" if i==0 else "")
                try:
                    if re.search(r"cover",lab): await f.set_input_files(cl_pdf or P.get("cover_letter",P["resume"])); report["filled"]["cover_letter"]="uploaded"
                    elif i==0 or re.search(r"resume|cv",lab): await f.set_input_files(P["resume"]); report["filled"]["resume"]="uploaded"
                except Exception as e: report["filled"][f"file{i}"]=f"ERR {e.__class__.__name__}"
            await page.wait_for_timeout(5000)
            for _ in range(25):
                if not await page.locator('text=/Analyzing resume|Uploading|Parsing/i').count(): break
                await page.wait_for_timeout(1000)
            # text inputs / textareas
            ctrls=page.locator('input[type="text"], input[type="email"], input[type="tel"], input[type="url"], input[type="number"], input:not([type]), textarea')
            n=await ctrls.count()
            for i in range(n):
                h=ctrls.nth(i)
                try:
                    if not await h.is_visible(): continue
                    name=await h.get_attribute("name") or ""; lab=await label_of(h)
                    if re.search(r"captcha|search",name+lab,re.I): continue
                    ph=(await h.get_attribute("placeholder") or "")
                    if lab.strip().lower() in ("select...","select") or re.search(r"select2",(await h.get_attribute("class")) or ""): continue
                    if re.search(r"^location$|current location|^city$|where are you (based|located)",lab,re.I) or (ats=="lever" and name=="location") or (re.search(r"start typing",ph,re.I) and re.search(r"location|city",lab,re.I)):
                        if not (await h.input_value()).strip():
                            got=await autocomplete_fill(page,h,"Santa Clara, California",r"santa clara")
                            report["filled"][lab[:60] or name]=f"autocomplete:{got}"
                        continue
                    if await h.evaluate("(el)=>el.getAttribute('aria-autocomplete')==='list'||el.getAttribute('role')==='combobox'||/select__input|react-select/.test(el.className+' '+el.id)||!!el.closest('[class*=select__control],[class*=Select__control]')"): continue
                    if re.search(r"ai policy|use of ai|ai assistance|ai tools? (in|during)|without (the use of )?ai",lab,re.I): report["unanswered"].append({"type":"text","label":lab[:160],"name":name,"note":"AI-use question left for user"}); continue
                    key=lab or name
                    val=None
                    for k,v in extra.items():
                        if k.lower() in (name+" "+lab).lower(): val=v; break
                    if val is None: val=pick(key,TEXT_RULES)
                    if re.search(r"cover letter",lab,re.I) and cl_text: val=cl_text
                    if ats=="lever" and re.search(r"^location$",name): val=P["location"]
                    if val is None and (await h.get_attribute("placeholder") or ""): val=pick(await h.get_attribute("placeholder"),TEXT_RULES)
                    cur=await h.input_value()
                    if val: 
                        if cur.strip()!=val: await fill_text(page,h,val)
                        report["filled"][key[:60]]=val[:40]
                    elif not cur.strip() and await is_required(h): report["unanswered"].append({"type":"text","label":key[:160],"name":name})
                except Exception as e: pass
            # native selects
            sels=page.locator('select'); n=await sels.count()
            for i in range(n):
                h=sels.nth(i)
                try:
                    vis=await h.is_visible()
                    if not vis and not await h.evaluate("(s)=>!!(s.id||s.name)"): continue
                    lab=await label_of(h); name=await h.get_attribute("name") or ""
                    if not lab and not vis: continue
                    pref=None
                    for k,v in extra.items():
                        if k.lower() in (name+" "+lab).lower(): pref=[v]; break
                    pref=pref or pick(lab,CHOICE_RULES)
                    if pref==["__ASK__"]: pref=None
                    if pref:
                        got=await choose_select(page,h,pref); report["chosen"][lab[:60]]=got
                        if not got and await is_required(h): report["unanswered"].append({"type":"select","label":lab[:160],"options":(await h.evaluate("(s)=>[...s.options].map(o=>o.text.trim())"))[:12]})
                    elif await is_required(h): report["unanswered"].append({"type":"select","label":lab[:160],"options":(await h.evaluate("(s)=>[...s.options].map(o=>o.text.trim())"))[:12]})
                except Exception: pass
            # react-select style comboboxes (Greenhouse/Ashby)
            combos=page.locator('[class*="select__control"], [role="combobox"]:not(input), div[class*="Select"] [class*="control"], button[aria-haspopup="listbox"]')
            n=await combos.count()
            for i in range(n):
                h=combos.nth(i)
                try:
                    if not await h.is_visible(): continue
                    lab=await label_of(h)
                    if not lab: continue
                    cur=(await h.inner_text()).strip()
                    if cur and not re.search(r"select|choose|--",cur,re.I): continue
                    pref=None
                    for k,v in extra.items():
                        if k.lower() in lab.lower(): pref=[v]; break
                    pref=pref or pick(lab,CHOICE_RULES)
                    if pref:
                        got=await choose_react_select(page,h,pref,lab); report["chosen"][lab[:60]]=got
                        if not got: report["unanswered"].append({"type":"combo","label":lab[:160]})
                    else: report["unanswered"].append({"type":"combo","label":lab[:160]})
                except Exception: pass
            # radios & checkboxes grouped by name
            radios=page.locator('input[type="radio"]'); n=await radios.count(); groups={}
            for i in range(n):
                h=radios.nth(i)
                try:
                    name=await h.get_attribute("name") or f"r{i}"; groups.setdefault(name,[]).append(h)
                except Exception: pass
            for name,hs in groups.items():
                try:
                    if any([await x.is_checked() for x in hs]): continue
                    qlab=await hs[0].evaluate("(el)=>{const fs=el.closest('fieldset'); if(fs){const lg=fs.querySelector('legend'); if(lg) return lg.innerText;} let p=el.parentElement; for(let i=0;i<7&&p;i++){const q=p.querySelector('.application-label, legend, [class*=question], [class*=label], h3, h4'); if(q&&q.innerText.trim().length>3) return q.innerText; p=p.parentElement;} return '';}")
                    qlab=re.sub(r"\s+"," ",qlab).replace("✱","").strip()
                    opts=[]
                    for x in hs: opts.append(((await x.get_attribute("value")) or "", await label_of(x)))
                    if not qlab or qlab.lower() in [o[1].lower() for o in opts]:
                        # label picked an option text; walk up further for the question text
                        qlab2=await hs[0].evaluate("(el)=>{let p=el.parentElement; for(let i=0;i<9&&p;i++){const prev=p.previousElementSibling; if(prev&&prev.innerText&&prev.innerText.trim().length>3&&prev.innerText.trim().length<200) return prev.innerText; p=p.parentElement;} return '';}")
                        qlab2=re.sub(r"\s+"," ",qlab2).replace("✱","").strip()
                        if qlab2 and qlab2.lower() not in [o[1].lower() for o in opts]: qlab=qlab2
                    cands=[]
                    for k,v in extra.items():
                        if k.lower() in qlab.lower(): cands.append([v]); break
                    p1=pick(qlab,CHOICE_RULES); p2=pick(" ".join(o[1] for o in opts),CHOICE_RULES)
                    if p1 and p1!=["__ASK__"]: cands.append(p1)
                    if p2 and p2!=["__ASK__"] and p2 not in cands: cands.append(p2)
                    done=None
                    if p1==["__ASK__"]: cands=[]
                    for pref in cands:
                        for pv in pref:
                            for x,(v,l) in zip(hs,opts):
                                if l.lower()==pv.lower() or v.lower()==pv.lower() or pv.lower() in l.lower():
                                    await x.check(timeout=3000); done=l or v; break
                            if done: break
                        if done: break
                    report["chosen"][qlab[:60] or name]=done
                    if not done: report["unanswered"].append({"type":"radio","label":qlab[:160],"options":[o[1] or o[0] for o in opts][:10]})
                except Exception: pass
            # segmented Yes/No button groups and ARIA radios (Ashby)
            try:
                groups=await page.evaluate(r"""()=>{
                  const out=[]; const seen=new Set();
                  const els=[...document.querySelectorAll('button, [role="radio"]:not(input), [role="option"]')].filter(e=>e.offsetParent!==null);
                  for(const e of els){
                    const t=(e.innerText||'').trim(); if(!/^(yes|no|male|female|true|false|i am not a protected veteran|i don't wish to answer|decline)/i.test(t)) continue;
                    const par=e.parentElement; if(!par||seen.has(par)) continue; seen.add(par);
                    const btns=[...par.children].filter(c=>c.tagName==='BUTTON'||c.getAttribute('role')==='radio').map(c=>(c.innerText||'').trim());
                    if(btns.length<2) continue;
                    let q=''; let p=par;
                    for(let i=0;i<6&&p;i++){ const prev=p.previousElementSibling; if(prev&&prev.innerText&&prev.innerText.trim().length>5){q=prev.innerText.trim(); break;} const lab=p.querySelector('label,legend'); if(lab&&lab.innerText.trim().length>5){q=lab.innerText.trim(); break;} p=p.parentElement; }
                    const pressed=[...par.children].some(c=>c.getAttribute('aria-pressed')==='true'||c.getAttribute('aria-checked')==='true'||/selected|active|checked/.test(c.className));
                    par.setAttribute('data-applyq', String(out.length));
                    out.push({q:q.replace(/\s+/g,' ').replace(/[✱*]/g,'').trim(), opts:btns, pressed});
                  }
                  return out; }""")
                for gi,g in enumerate(groups):
                    if g["pressed"]: continue
                    pref=None
                    for k,v in extra.items():
                        if k.lower() in g["q"].lower(): pref=[v]; break
                    pref=pref or pick(g["q"],CHOICE_RULES)
                    if pref==["__ASK__"] or not pref:
                        if g["q"]: report["unanswered"].append({"type":"buttons","label":g["q"][:160],"options":g["opts"][:8]})
                        continue
                    done=None
                    for pv in pref:
                        for o in g["opts"]:
                            if o.lower()==pv.lower() or pv.lower() in o.lower():
                                await page.locator(f'[data-applyq="{gi}"] > *:has-text("{o}")').first.click(timeout=3000); done=o; break
                        if done: break
                    report["chosen"][g["q"][:60]]=done
                    if not done: report["unanswered"].append({"type":"buttons","label":g["q"][:160],"options":g["opts"][:8]})
            except Exception as e: report["chosen"]["_buttons_err"]=str(e)[:120]
            cbs=page.locator('input[type="checkbox"]'); n=await cbs.count()
            for i in range(n):
                h=cbs.nth(i)
                try:
                    if not await h.is_visible() or await h.is_checked(): continue
                    lab=await label_of(h)
                    if re.search(r"pronoun|newsletter|marketing|updates|subscribe|text message|sms",lab,re.I): continue
                    if re.search(r"agree|acknowledge|consent|certify|confirm|privacy|terms|policy|accurate|true",lab,re.I) or await is_required(h): await h.check(timeout=3000); report["chosen"][lab[:60]]="checked"
                except Exception: pass
            answered={k.lower()[:40] for k,v in report["chosen"].items() if v} | {k.lower()[:40] for k in report["filled"].keys()}
            seen=set(); uu=[]
            for u in report["unanswered"]:
                if u["label"] in seen or u["label"].lower()[:40] in answered: continue
                seen.add(u["label"]); uu.append(u)
            report["unanswered"]=uu
            await page.wait_for_timeout(800)
            await page.screenshot(path=f"{OUT}/{tag}_filled.png",full_page=True)
            cap=await page.evaluate("()=>!!document.querySelector('iframe[src*=hcaptcha], iframe[src*=recaptcha], [data-sitekey]')")
            report["captcha_present"]=cap
            if submit and not report["unanswered"]:
                cands=page.locator('button#btn-submit, button[type="submit"], input[type="submit"], button:has-text("Submit application"), button:has-text("Submit Application"), button:has-text("Submit")')
                btn=None
                for i in range(await cands.count()):
                    c=cands.nth(i)
                    try:
                        if await c.is_visible() and re.search(r"submit|apply|send",(await c.inner_text()) or (await c.get_attribute("value")) or "submit",re.I): btn=c; break
                    except Exception: pass
                if btn is None: raise RuntimeError("no visible submit button")
                baseline=()
                if ats=="greenhouse" and outlook_cfg():
                    op=await outlook_page()
                    if op: baseline=tuple(await outlook_codes(op))   # codes already in the inbox before this submission
                await btn.scroll_into_view_if_needed(); await btn.click(timeout=10000); await page.wait_for_timeout(9000)
                body=await page.evaluate("()=>document.body.innerText.slice(0,2500)")
                if re.search(r"verification code|security code|confirm you.re a human",body,re.I):
                    if await enter_email_code(page,report,baseline):
                        await page.wait_for_timeout(800)
                        try: await btn.click(timeout=10000)
                        except Exception:
                            b2=page.locator('button[type="submit"]:visible, button:has-text("Submit application"):visible').first; await b2.click(timeout=10000)
                        await page.wait_for_timeout(9000)
                        body=await page.evaluate("()=>document.body.innerText.slice(0,2500)")
                ok=bool(re.search(r"thank you|thanks for applying|application (has been |was )?(submitted|received|sent)|we('ve| have) received|successfully|you're all set|applied",body,re.I)) and not re.search(r"needs corrections|missing entry|is required|please (fill|complete)",body,re.I)
                errs=await page.evaluate("()=>[...document.querySelectorAll('[class*=error], [role=alert], .invalid-feedback, [aria-invalid=true], [class*=correction]')].map(e=>e.innerText.trim()).filter(Boolean).slice(0,8)")
                m=re.findall(r"Missing entry for required field:\s*([^\n]+)",body)
                if m: errs=errs+[f"missing: {x.strip()}" for x in m]
                report["submitted"]=ok; report["result"]=body[:400].replace("\n"," | "); report["errors"]=errs; report["final_url"]=page.url
                await page.screenshot(path=f"{OUT}/{tag}_after.png",full_page=True)
            elif submit: report["result"]="NOT SUBMITTED: unanswered required questions"
        except Exception as e:
            report["result"]=f"ERROR {type(e).__name__}: {str(e)[:300]}"
            try: await page.screenshot(path=f"{OUT}/{tag}_error.png",full_page=True)
            except Exception: pass
        json.dump(report,open(f"{OUT}/{tag}_report.json","w"),indent=1)
        await page.close()
        return report
asyncio.run(run())
