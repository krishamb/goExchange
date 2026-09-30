"""Dice.com Easy Apply, signed in as the applicant.

usage: apply_dice.py <dice_queue.json> [--submit] [--pace MIN MAX] [--max N]
  queue items: {"guid", "url", "title", "company", "tag"}  (from dice_find.py)

Dice's Easy Apply sends the resume on the applicant's Dice profile plus the work authorization and location stored
there (US Citizen; Santa Clara, California). The filler adds the applicant's cover letter, answers any screening
questions from apply.py's reviewed rule tables, and checks the Review page before submitting: it submits only when
the review shows "US Citizen" and Santa Clara and every screening question has an answer from a rule. Anything else is
reported and left. Captchas and bot checks are never bypassed.
The login (JOBS_DIR/wf_creds.json {"dice": {"email", "password"}}) and the saved session (JOBS_DIR/dice_state.json)
stay outside the repository; a failed sign-in is never retried, so the account cannot lock."""
import asyncio, json, os, re, sys, time, random
from playwright.async_api import async_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.expanduser(os.environ.get("JOBS_DIR", "/tmp/claude-0/-home-user-goExchange/8d20ffb7-2488-5f8f-a666-35334b9e3ba6/scratchpad/f"))
OUT = os.path.join(JOBS_DIR, "out"); os.makedirs(OUT, exist_ok=True)
STATE = os.path.join(JOBS_DIR, "dice_state.json")
P = json.load(open(os.path.join(JOBS_DIR, "profile.json")))
SUBMIT = "--submit" in sys.argv
PACE = (float(sys.argv[sys.argv.index("--pace") + 1]), float(sys.argv[sys.argv.index("--pace") + 2])) if "--pace" in sys.argv else (45, 110)
MAX = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 10**6
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
CAPTCHA = 'iframe[src*="recaptcha"][src*="anchor"], iframe[src*="hcaptcha"], iframe[src*="challenges.cloudflare"], #px-captcha, iframe[title*="challenge" i]'

# shared, reviewed answer rules (apply.py runs its CLI at import time, so take the rule section from its source)
_src = open(os.path.join(HERE, "apply.py")).read()
def _seg(a, b):
    i = _src.index(a); return _src[i:_src.index(b, i)]
import datetime
G = {"re": re, "json": json, "os": os, "time": time, "datetime": datetime, "date": datetime.date, "P": P,
     "ANS": json.load(open(os.path.join(JOBS_DIR, "answers.json"))) if os.path.exists(os.path.join(JOBS_DIR, "answers.json")) else {}}
exec(_src[_src.index("first,last="):_src.index("\n", _src.index("first,last="))], G)
exec(_seg("TEXT_RULES=[", "\ndef pick("), G); exec(_seg("def pick(", "\nLABEL_JS"), G)
exec(_seg("def _match(", "\nasync def open_menu"), G); exec(_seg("HEAR_Q=", "\nasync def choose_react_select"), G)
exec(_seg("NEVER_APPLY=", "\n"), G)
TEXT_RULES, CHOICE_RULES, pick, best_index, mask_hear, NEVER_APPLY = (G[k] for k in ("TEXT_RULES", "CHOICE_RULES", "pick", "best_index", "mask_hear", "NEVER_APPLY"))

async def refetch(route):
    """This container's proxy drops some of Chromium's own requests to dice.com (ERR_TOO_MANY_RETRIES); fetching them
    through Playwright instead loads the page normally."""
    for _ in range(3):
        try:
            r = await route.fetch(timeout=30000); await route.fulfill(response=r); return
        except Exception: pass
    await route.abort()
async def text(page):
    try: return await page.evaluate("()=>document.body.innerText")
    except Exception: return ""

async def ensure_login(ctx):
    pg = await ctx.new_page()
    await pg.goto("https://www.dice.com/home-feed", wait_until="domcontentloaded", timeout=60000); await pg.wait_for_timeout(6000)
    if "/dashboard/login" not in pg.url and re.search(r"Your Profile|Jobs Recommended|is Online", await text(pg)):
        await pg.close(); return True
    c = json.load(open(os.path.join(JOBS_DIR, "wf_creds.json")))["dice"]
    await pg.goto("https://www.dice.com/dashboard/login", wait_until="domcontentloaded", timeout=60000)
    em = pg.locator('input[type="email"], input[name="email"]')
    await em.first.wait_for(state="visible", timeout=40000)
    if await pg.locator(CAPTCHA).count(): print("DICE LOGIN: captcha shown, not bypassed", flush=True); return False
    await em.first.fill(c["email"])
    await pg.get_by_role("button", name=re.compile("continue", re.I)).first.click()
    await pg.locator('input[type="password"]').first.wait_for(state="visible", timeout=45000)
    if await pg.locator(CAPTCHA).count(): print("DICE LOGIN: captcha shown, not bypassed", flush=True); return False
    await pg.locator('input[type="password"]').first.fill(c["password"])
    await pg.get_by_role("button", name=re.compile("sign in|log in|continue", re.I)).first.click()
    await pg.wait_for_timeout(9000)
    ok = "/dashboard/login" not in pg.url
    if ok: await ctx.storage_state(path=STATE); os.chmod(STATE, 0o600)
    print("DICE LOGIN", "ok" if ok else "FAILED (not retried)", flush=True)
    await pg.close(); return ok

QFIELDS_JS = r"""()=>{
  const out=[];
  for (const el of document.querySelectorAll('main input, main select, main textarea, form input, form select, form textarea')) {
    if (!el.offsetParent || el.type==='file' || el.type==='hidden') continue;
    let lab=(el.labels&&el.labels[0]?el.labels[0].innerText:'')||el.getAttribute('aria-label')||'';
    const fs=el.closest('fieldset'); if (fs && (el.type==='radio'||el.type==='checkbox')) lab=(fs.querySelector('legend')||{}).innerText||lab;
    out.push({tag:el.tagName,type:el.type||'',name:el.name||'',id:el.id||'',label:lab.replace(/\s+/g,' ').trim(),value:el.value||'',checked:!!el.checked,required:el.required||el.getAttribute('aria-required')==='true'});
  }
  return out;}"""

async def answer_questions(page, report):
    """Screening questions on a Dice step: answer from the rules or report them as unanswered."""
    fields = await page.evaluate(QFIELDS_JS); missing = []
    groups = {}
    for f in fields:
        if f["type"] in ("radio", "checkbox"): groups.setdefault((f["name"] or f["label"]), []).append(f)
    for f in fields:
        lab = f["label"]
        if f["type"] in ("radio", "checkbox") or not lab: continue
        if f["tag"] == "SELECT":
            prefs = pick(lab, CHOICE_RULES); prefs = prefs if isinstance(prefs, list) else ([prefs] if prefs else [])
            loc = page.locator(f'select[name="{f["name"]}"]' if f["name"] else f'#{f["id"]}').first
            opts = await loc.evaluate("(s)=>[...s.options].map(o=>o.text.trim())")
            k = next((best_index(mask_hear(opts, lab), p) for p in prefs if best_index(mask_hear(opts, lab), p) is not None), None)
            if k is not None: await loc.select_option(label=opts[k]); report["answers"][lab] = opts[k]
            elif f["required"]: missing.append(lab)
        else:
            if f["value"]: report["answers"][lab] = f["value"]; continue
            v = pick(lab, TEXT_RULES)
            if isinstance(v, str):
                loc = page.locator(f'[name="{f["name"]}"]' if f["name"] else f'#{f["id"]}').first
                await loc.fill(v); report["answers"][lab] = v
            elif f["required"]: missing.append(lab)
    for key, g in groups.items():
        lab = g[0]["label"] or key
        if any(x["checked"] for x in g): continue
        prefs = pick(lab, CHOICE_RULES); prefs = prefs if isinstance(prefs, list) else ([prefs] if prefs else [])
        texts = []
        for x in g:
            t = await page.evaluate("(id)=>{const e=document.getElementById(id);const l=e&&e.labels&&e.labels[0];return l?l.innerText.trim():(e&&e.value)||''}", x["id"]) if x["id"] else x["value"]
            texts.append(t)
        k = next((best_index(mask_hear(texts, lab), p) for p in prefs if best_index(mask_hear(texts, lab), p) is not None), None)
        if k is not None:
            sel = f'#{g[k]["id"]}' if g[k]["id"] else f'input[name="{g[k]["name"]}"][value="{g[k]["value"]}"]'
            try: await page.locator(sel).first.check(timeout=3000)
            except Exception: await page.locator(sel).first.evaluate("(e)=>{const l=e.labels&&e.labels[0];(l||e).click()}")
            report["answers"][lab] = texts[k]
        elif any(x["required"] for x in g): missing.append(lab)
    return missing

async def apply_one(ctx, item):
    tag = item["tag"]; rp = f"{OUT}/{tag}_report.json"
    report = {"tag": tag, "ats": "dice", "url": item["url"], "submitted": False, "result": "", "answers": {}, "unanswered": [], "errors": [],
              "resume_file": "Dice profile resume"}
    page = await ctx.new_page()
    try:
        if NEVER_APPLY.search(f'{item.get("company","")} {item.get("title","")}'):
            report["result"] = "NOT SUBMITTED: do-not-apply company"; return report
        await page.goto(item["url"], wait_until="domcontentloaded", timeout=60000); await page.wait_for_timeout(6000)
        body = await text(page)
        if await page.locator(CAPTCHA).count(): report["result"] = "NOT SUBMITTED: captcha/bot check (not bypassed)"; return report
        if re.search(r"no longer (available|accepting)|job (has been|is) (closed|filled|removed)|page not found", body, re.I):
            report["result"] = "NOT SUBMITTED: job closed"; return report
        if re.search(r"\bApplied\b\s*(on|\d)|You('ve| have) applied|Application submitted", body):
            report["result"] = "ALREADY APPLIED on Dice"; return report
        link = page.locator('a[href*="/job-applications/"][href$="/wizard"]')
        if not await link.count():
            report["result"] = "NOT SUBMITTED: no Easy Apply on this job"; return report
        await link.first.click(); await page.wait_for_timeout(6000)
        for _ in range(6):
            body = await text(page)
            if await page.locator(CAPTCHA).count(): report["result"] = "NOT SUBMITTED: captcha/bot check (not bypassed)"; return report
            if re.search(r"application (has been )?(submitted|sent)|you('ve| have) (successfully )?applied|thanks for applying|application complete", body, re.I) and "Review your application" not in body:
                report["submitted"] = True; report["result"] = re.sub(r"\s+", " ", body[:300]); return report
            if "Review your application" in body:
                ok_auth = re.search(r"Work Authorization\s*\*?\s*\n?\s*US Citizen", body) is not None
                ok_loc = re.search(r"Current Location\s*\*?\s*\n?\s*Santa Clara", body) is not None
                report["answers"].update({"Work Authorization": "US Citizen" if ok_auth else "?", "Current Location": "Santa Clara" if ok_loc else "?"})
                await page.screenshot(path=f"{OUT}/{tag}_review.png", full_page=True)
                if not (ok_auth and ok_loc):
                    report["result"] = "NOT SUBMITTED: review page did not show US Citizen / Santa Clara"; return report
                if not SUBMIT: report["result"] = "DRY RUN: stopped at Review"; return report
                await page.get_by_role("button", name=re.compile(r"^submit$", re.I)).first.click()
                await page.wait_for_timeout(8000)
                body = await text(page)
                if re.search(r"application (has been )?(submitted|sent)|you('ve| have) (successfully )?applied|thanks for applying|application complete|\bApplied\b", body, re.I) or "/wizard" not in page.url:
                    report["submitted"] = True; report["result"] = re.sub(r"\s+", " ", body[:300]); report["final_url"] = page.url
                else:
                    report["result"] = "UNCERTAIN: no confirmation after Submit"; report["final_url"] = page.url
                    await page.screenshot(path=f"{OUT}/{tag}_after.png", full_page=True)
                return report
            if re.search(r"Resume & Cover Letter", body):
                cl = P.get("cover_letter")
                up = page.locator('input[type="file"]')
                if cl and os.path.exists(cl) and await up.count() and "No cover letter" not in body and not re.search(r"\.pdf\s*\n\s*Uploaded.*\n.*Cover", body):
                    try: await up.last.set_input_files(cl); await page.wait_for_timeout(3000); report["cover_letter"] = os.path.basename(cl)
                    except Exception as e: report["errors"].append(f"cover letter: {str(e)[:80]}")
            else:
                missing = await answer_questions(page, report)
                if missing:
                    report["unanswered"] = missing; await page.screenshot(path=f"{OUT}/{tag}_missing.png", full_page=True)
                    report["result"] = "NOT SUBMITTED: unanswered required questions"; return report
            nxt = page.get_by_role("button", name=re.compile(r"^(next|continue)$", re.I))
            if not await nxt.count(): report["result"] = "NOT SUBMITTED: no Next button"; return report
            await nxt.first.click(); await page.wait_for_timeout(5000)
            errs = page.locator('[role="alert"]:visible:not(#__next-route-announcer__):not(next-route-announcer), [class*="error"]:visible')
            if await errs.count():
                e = [t for t in [(await errs.nth(i).inner_text()).strip() for i in range(min(await errs.count(), 5))] if t and not t.endswith("| Dice.com")]
                if e: report["errors"] = e; report["result"] = "NOT SUBMITTED: form errors"; return report
        report["result"] = "NOT SUBMITTED: too many steps"; return report
    except Exception as e:
        report["result"] = f"ERROR {type(e).__name__}: {str(e)[:200]}"; return report
    finally:
        report["title"], report["company"] = item.get("title"), item.get("company")
        json.dump(report, open(rp, "w"), indent=1)
        print(("OK  " if report["submitted"] else "FAIL") + f' dice {tag} | {report["result"][:90]} | unanswered={"; ".join(x[:28] for x in report["unanswered"])} | err={"; ".join(report["errors"])[:80]}', flush=True)
        try: await page.close()
        except Exception: pass

def _norm_title(t):
    t = re.sub(r"\(.*?\)", "", (t or "").lower()); t = re.sub(r"^(coe|remote|urgent|hiring|immediate)\s*[-:|]\s*", "", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()
def _ckey(c): return re.sub(r"[^a-z0-9]", "", (c or "").lower())
def same_position_done(item):
    """The applicant never wants the same position submitted twice (reposts included); 3 different roles per company at most."""
    import glob as _g
    n = 0
    for f in _g.glob(f"{OUT}/dice_*_report.json"):
        try: r = json.load(open(f))
        except Exception: continue
        if not r.get("submitted") or r.get("tag") == item["tag"] or _ckey(r.get("company")) != _ckey(item.get("company")): continue
        if _norm_title(r.get("title")) == _norm_title(item.get("title")): return "same position already applied"
        n += 1
    return "3 roles at this company already" if n >= 3 else None

async def main():
    q = json.load(open(sys.argv[1]))
    async with async_playwright() as p:
        br = await p.chromium.launch(headless=False, args=["--disable-http2", "--disable-quic"])
        ctx = await br.new_context(ignore_https_errors=True, user_agent=UA, viewport={"width": 1280, "height": 1500}, locale="en-US",
                                   timezone_id="America/Los_Angeles", storage_state=STATE if os.path.exists(STATE) else None)
        await ctx.route(re.compile(r"https://([a-z0-9-]+\.)*dice\.com/.*"), refetch)
        if not await ensure_login(ctx): print("stopping: not signed in to Dice", flush=True); return
        n = 0
        for item in q:
            rp = f"{OUT}/{item['tag']}_report.json"
            if os.path.exists(rp):
                try:
                    if json.load(open(rp)).get("submitted"): continue
                except Exception: pass
            if n >= MAX: break
            why = same_position_done(item)
            if why: print(f"SKIP dice {item['tag']} | {why}", flush=True); continue
            r = await apply_one(ctx, item); n += 1
            if r["submitted"] or not r["result"].startswith(("NOT SUBMITTED: job closed", "ALREADY", "NOT SUBMITTED: no Easy")):
                g = random.uniform(*PACE); print(f"PACE waiting {int(g)}s before the next application", flush=True); await asyncio.sleep(g)
        await ctx.storage_state(path=STATE)
        await br.close()

if __name__ == "__main__":
    asyncio.run(main())
