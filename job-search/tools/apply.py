#!/usr/bin/env python3
"""Generic job-application filler/submitter for Lever, Greenhouse, Ashby and Wellfound.
Usage: python3 job-search/tools/apply.py <lever|greenhouse|ashby|wellfound> <url> <tag> [--submit] [--answers file.json]
Profile/credentials are read from JOBS_DIR (default: session scratchpad), never from this repo.
"""
import asyncio, sys, json, os, re, time
from playwright.async_api import async_playwright
JOBS_DIR=os.environ.get("JOBS_DIR","/tmp/claude-0/-home-user-goExchange/8d20ffb7-2488-5f8f-a666-35334b9e3ba6/scratchpad/f")
OUT=os.path.join(JOBS_DIR,"out"); os.makedirs(OUT,exist_ok=True)
P=json.load(open(os.path.join(JOBS_DIR,"profile.json")))
ANS=json.load(open(os.path.join(JOBS_DIR,"answers.json"))) if os.path.exists(os.path.join(JOBS_DIR,"answers.json")) else {}
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
HEADED="--headed" in sys.argv
if HEADED and not os.environ.get("DISPLAY"):
    os.execvp("xvfb-run",["xvfb-run","-a","-s","-screen 0 1280x2000x24",sys.executable]+sys.argv)
submit="--submit" in sys.argv
BATCH = sys.argv[1]=="batch"
if BATCH:
    JOBS=json.load(open(sys.argv[2])); ats=url=tag=None; extra={}
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
 (r"pronoun", ""),
]
CHOICE_RULES=[
 (r"sponsor", ["No","no"]),
 (r"interviewed .*before|applied .*before|previously (applied|interviewed)", ["No","no"]),
 (r"in[- ]person|open to working in|come into the office|days? (a|per) week", ["Yes","yes"]),
 (r"ai policy|use of ai|ai assistance|ai tools? (in|during)|without (the use of )?ai|generative ai", ["__ASK__"]),
 (r"authori[sz]ed to work|legally (able|eligible|authorized)|work authorization|eligible to work|right to work", ["Yes","yes"]),
 (r"citizen", ["Yes","U.S. Citizen","US Citizen"]),
 (r"relocat", ["Yes","yes"]),
 (r"remote|hybrid|on-?site|in[- ]office|work from|commut", ["Yes","yes","Hybrid","Remote"]),
 (r"gender|sex\b", ["Male","Man"]),
 (r"hispanic|latino", ["No","I am not Hispanic or Latino","Not Hispanic or Latino"]),
 (r"race|ethnicit", ["I don't wish to answer","Decline To Self Identify","Decline to self identify","Prefer not to say","Prefer not to answer","I do not wish to answer"]),
 (r"veteran", ["I am not a protected veteran","Not a protected veteran","I am not a veteran","No","Decline To Self Identify"]),
 (r"disabilit", ["No, I do not have a disability","No, I don't have a disability","No","I do not have a disability","I don't wish to answer"]),
 (r"18 (years|or older)|age of 18|over 18", ["Yes","yes"]),
 (r"background check|drug|non-?compete|agreement|acknowledge|certify|consent|privacy|terms|policy|subscribe|agree", ["Yes","I agree","I acknowledge","I consent","yes"]),
 (r"how did you hear|source", ["Company Website","Company website","Careers page","Career Page","Other","Job Board","Other/Not Listed"]),
 (r"degree|education|highest level", ["Bachelor's Degree","Undergraduate/Bachelor's degree","Bachelor's","Bachelors"]),
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
 if(el.id){const l=document.querySelector('label[for="'+CSS.escape(el.id)+'"]'); if(l) t=l.innerText;}
 if(!t){const l=el.closest('label'); if(l) t=l.innerText;}
 if(!t && el.getAttribute('aria-label')) t=el.getAttribute('aria-label');
 if(!t && el.getAttribute('aria-labelledby')){const l=document.getElementById(el.getAttribute('aria-labelledby')); if(l) t=l.innerText;}
 if(!t){const fs=el.closest('fieldset'); if(fs){const lg=fs.querySelector('legend'); if(lg) t=lg.innerText;}}
 if(!t){let p=el.parentElement; for(let i=0;i<6&&p;i++){const lab=p.querySelector('label, legend, .application-label, [class*="label"], [class*="Label"], h3, h4, .field-label, .question'); if(lab && lab.innerText.trim()){t=lab.innerText; break;} p=p.parentElement;}}
 return (t||'').trim().replace(/\s+/g,' ').replace(/[✱*]/g,'').trim();}
"""
async def label_of(h): return await h.evaluate(LABEL_JS)
async def is_required(h):
    return await h.evaluate("(el)=>el.required||el.getAttribute('aria-required')==='true'||/\\*|✱|required/i.test((el.closest('label,fieldset,div')||{}).innerText||'')")
async def fill_text(page,h,val):
    try:
        await h.scroll_into_view_if_needed(timeout=3000)
        await h.fill(val); return True
    except Exception:
        try: await h.click(timeout=3000); await h.type(val,delay=10); return True
        except Exception: return False
async def choose_select(page,h,options_pref):
    opts=await h.evaluate("(s)=>[...s.options].map(o=>o.text.trim())")
    for pref in options_pref:
        for o in opts:
            if o.lower()==pref.lower() or pref.lower() in o.lower():
                try: await h.select_option(label=o); return o
                except Exception: pass
    return None
async def choose_react_select(page,control,options_pref,label):
    # click control, read listbox options, click best
    try:
        await control.scroll_into_view_if_needed(timeout=3000); await control.click(timeout=4000); await page.wait_for_timeout(600)
        if options_pref==["__ASK__"]:
            await page.keyboard.press("Escape"); return None
        async def visible_opts():
            o=page.locator('[class*="select__option"], [role="option"], [class*="Select__option"], li[id*="option"], div[id*="-option-"]')
            n=await o.count(); t=[]
            for i in range(min(n,80)):
                try: t.append((await o.nth(i).inner_text()).strip())
                except Exception: t.append("")
            return o,t
        opts,texts=await visible_opts()
        if not texts:
            inp=control.locator('input').first
            if await inp.count(): await inp.click(timeout=2000); await page.wait_for_timeout(500); opts,texts=await visible_opts()
        for pref in options_pref:
            for i,t in enumerate(texts):
                if t and (t.lower()==pref.lower() or pref.lower() in t.lower()):
                    await opts.nth(i).click(timeout=3000); await page.wait_for_timeout(300); return t
        inp=control.locator('input').first
        if await inp.count():
            for pref in options_pref[:3]:
                await inp.fill(""); await inp.type(pref[:25],delay=15); await page.wait_for_timeout(700); opts,texts=await visible_opts()
                for i,t in enumerate(texts):
                    if t and (t.lower()==pref.lower() or pref.lower() in t.lower()):
                        await opts.nth(i).click(timeout=3000); await page.wait_for_timeout(300); return t
            await page.keyboard.press("Escape")
        await page.keyboard.press("Escape")
    except Exception as e:
        try: await page.keyboard.press("Escape")
        except Exception: pass
    return None
async def run():
    async with async_playwright() as p:
        b=await p.chromium.launch(executable_path="/opt/pw-browsers/chromium",headless=not HEADED,args=["--no-sandbox","--ignore-certificate-errors"])
        jobs = JOBS if BATCH else [{"ats":ats,"url":url,"tag":tag,"answers":extra}]
        summary=[]
        for job in jobs:
            ctx=await b.new_context(ignore_https_errors=True,user_agent=UA,viewport={"width":1280,"height":2000},locale="en-US",timezone_id="America/Los_Angeles")
            r=await run_one(ctx,job["ats"],job["url"],job["tag"],job.get("answers",{}))
            summary.append({k:r.get(k) for k in ("tag","ats","url","submitted","result","unanswered","captcha_present","errors")})
            print(json.dumps(summary[-1])[:600]); sys.stdout.flush()
            await ctx.close()
        json.dump(summary,open(f"{OUT}/batch_summary_{int(time.time())}.json","w"),indent=1)
        await b.close()
async def run_one(ctx,ats,url,tag,extra):
    if True:
        page=await ctx.new_page(); report={"ats":ats,"url":url,"tag":tag,"filled":{},"chosen":{},"unanswered":[],"submitted":False,"result":""}
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
            await page.goto(url,wait_until="domcontentloaded",timeout=60000); await page.wait_for_timeout(3500)
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
            # resume upload first (autofill may follow)
            files=page.locator('input[type="file"]'); nf=await files.count()
            for i in range(nf):
                f=files.nth(i); lab=(await label_of(f)).lower()
                try:
                    if re.search(r"cover",lab): await f.set_input_files(P.get("cover_letter",P["resume"])); report["filled"]["cover_letter"]="uploaded"
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
                    if await h.evaluate("(el)=>el.getAttribute('aria-autocomplete')==='list'||el.getAttribute('role')==='combobox'||/select__input|react-select/.test(el.className+' '+el.id)||!!el.closest('[class*=select__control],[class*=Select__control]')"): continue
                    if re.search(r"ai policy|use of ai|ai assistance|ai tools? (in|during)|without (the use of )?ai",lab,re.I): report["unanswered"].append({"type":"text","label":lab[:160],"name":name,"note":"AI-use question left for user"}); continue
                    key=lab or name
                    val=None
                    for k,v in extra.items():
                        if k.lower() in (name+" "+lab).lower(): val=v; break
                    if val is None: val=pick(key,TEXT_RULES)
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
                    if not await h.is_visible(): continue
                    lab=await label_of(h); name=await h.get_attribute("name") or ""
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
                    pref=None
                    for k,v in extra.items():
                        if k.lower() in qlab.lower(): pref=[v]; break
                    pref=pref or pick(qlab,CHOICE_RULES) or pick(" ".join(o[1] for o in opts),CHOICE_RULES)
                    done=None
                    if pref==["__ASK__"]: pref=None
                    if pref:
                        for pv in pref:
                            for x,(v,l) in zip(hs,opts):
                                if l.lower()==pv.lower() or v.lower()==pv.lower() or pv.lower() in l.lower():
                                    await x.check(timeout=3000); done=l or v; break
                            if done: break
                    report["chosen"][qlab[:60] or name]=done
                    if not done: report["unanswered"].append({"type":"radio","label":qlab[:160],"options":[o[1] or o[0] for o in opts][:10]})
                except Exception: pass
            cbs=page.locator('input[type="checkbox"]'); n=await cbs.count()
            for i in range(n):
                h=cbs.nth(i)
                try:
                    if not await h.is_visible() or await h.is_checked(): continue
                    lab=await label_of(h)
                    if re.search(r"pronoun|newsletter|marketing|updates|subscribe|text message|sms",lab,re.I): continue
                    if re.search(r"agree|acknowledge|consent|certify|confirm|privacy|terms|policy|accurate|true",lab,re.I) or await is_required(h): await h.check(timeout=3000); report["chosen"][lab[:60]]="checked"
                except Exception: pass
            seen=set(); uu=[]
            for u in report["unanswered"]:
                if u["label"] in seen: continue
                seen.add(u["label"]); uu.append(u)
            report["unanswered"]=uu
            await page.wait_for_timeout(800)
            await page.screenshot(path=f"{OUT}/{tag}_filled.png",full_page=True)
            cap=await page.evaluate("()=>!!document.querySelector('iframe[src*=hcaptcha], iframe[src*=recaptcha], [data-sitekey]')")
            report["captcha_present"]=cap
            if submit and not report["unanswered"]:
                btn=page.locator('button#btn-submit, button[type="submit"]:has-text("Submit"), input[type="submit"], button:has-text("Submit application"), button:has-text("Submit Application"), button:has-text("Submit")').first
                await btn.scroll_into_view_if_needed(); await btn.click(timeout=10000); await page.wait_for_timeout(9000)
                body=await page.evaluate("()=>document.body.innerText.slice(0,1500)")
                ok=bool(re.search(r"thank you|application (has been )?(submitted|received)|we('ve| have) received|successfully|you're all set|application sent|applied",body,re.I))
                errs=await page.evaluate("()=>[...document.querySelectorAll('[class*=error], [role=alert], .invalid-feedback, [aria-invalid=true]')].map(e=>e.innerText.trim()).filter(Boolean).slice(0,8)")
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
