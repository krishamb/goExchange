#!/usr/bin/env python3
"""Click-run page: the live, never-applied Ashby queue, with a ONE-CLICK hands-free launcher.

Runs on the applicant's Mac. Reads the current queue (batches/ashby_all.json), drops anything
already submitted locally or present in the Gmail applied ledger, and writes
~/jobs-private/click_run.html, newest first.

With the Tampermonkey filler installed, the big START button hands the whole queue to the
userscript via the page-URL #akf= hash (auto:true). The script then opens each job in that
one tab, fills it, submits the ones every required question is answered for, waits for Ashby
to confirm, and moves to the next by itself - no further clicks. It pauses on a captcha and
stops after two spam-blocks in a row, leaving the rest as individual links. Nothing is
spoofed or disguised: this is the applicant's own browser and session doing what they would
do by hand, faster.
"""
import json, re, os, glob, time, base64, html as H

HERE = os.path.dirname(os.path.abspath(__file__))
PRIV = os.path.expanduser(os.environ.get("JOBS_DIR", "~/jobs-private"))
OUT = os.path.join(PRIV, os.environ.get("CLICK_RUN_OUT", "click_run.html"))

def norm(s): return re.sub(r"[^a-z0-9]", "", str(s or "").lower())

queue = json.load(open(os.environ.get("ASHBY_QUEUE") or os.path.join(HERE, "batches", "ashby_all.json")))

done_tags, done_cos = set(), set()
for f in glob.glob(os.path.join(PRIV, "out", "*_report.json")):
    try: r = json.load(open(f))
    except Exception: continue
    if r.get("submitted"):
        done_tags.add(r.get("tag") or os.path.basename(f)[:-12]); done_cos.add(norm(r.get("company")))
ledger = set()
try: ledger = {norm(k) for k in json.load(open(os.path.join(HERE, "applied_gmail.json")))["companies"]}
except Exception: pass

rows = []
# exec/leadership roles (priority=1: Director / VP / CTO / Head of) first, then newest first
_key = (lambda x: -(x.get("posted_ts") or 0)) if os.environ.get("ASHBY_SORT") == "recency" else (lambda x: (-(x.get("priority") or 0), -(x.get("posted_ts") or 0)))
_ordered = queue if os.environ.get("ASHBY_SORT") == "none" else sorted(queue, key=_key)   # none: the queue file's own order (groups)
PACE = [int(x) for x in os.environ.get("AKF_PACE", "2000,45000").split(",")]
for j in _ordered:
    if j.get("tag") in done_tags or norm(j.get("company")) in done_cos | ledger: continue
    rows.append(j)

def appurl(u):
    if "jobs.lever.co" in (u or ""): return re.sub(r"/apply/?$", "", u.rstrip("/")) + "/apply"   # Lever: the apply form
    return re.sub(r"/application/?$", "", (u or "").rstrip("/")) + "/application"

# applicant contact for autofill — read from the private jobs folder (me.json: {"email": ..., "phone": ...}) and
# carried only in the LOCALLY generated page (its #akf hash); never written into this public repository. Without
# me.json the filler uses the email/phone saved once in its own Setup panel.
try: _me = json.load(open(os.path.join(PRIV, "me.json")))
except Exception: _me = {}
AUTOFILL_EMAIL = os.environ.get("AKF_EMAIL") or _me.get("email", "")
AUTOFILL_PHONE = os.environ.get("AKF_PHONE") or _me.get("phone", "")
ME = {k: v for k, v in (("email", AUTOFILL_EMAIL), ("phone", AUTOFILL_PHONE)) if v}

def akf_hash(items, auto):
    """URL-safe base64 of the queue, matching the userscript's decoder (no '=' padding, which
    its hash regex would truncate). Pad the JSON so the byte length is a multiple of 3."""
    payload = {"name": "Ashby queue", "auto": auto, "pad": "", "pace": PACE, "me": ME,
               "items": [dict({"u": appurl(j["url"]), "t": (j.get("title") or "")[:70], "c": (j.get("company") or "")[:40]}, **({"a": j["a"]} if j.get("a") else {})) for j in items]}   # a: per-job answers (filler v.12+)
    js = json.dumps(payload, ensure_ascii=False)
    extra = (3 - (len(js.encode("utf-8")) % 3)) % 3
    if extra:
        payload["pad"] = " " * extra
        js = json.dumps(payload, ensure_ascii=False)
    b = base64.b64encode(js.encode("utf-8")).decode("ascii").replace("+", "-").replace("/", "_")
    assert "=" not in b, "padding would be truncated by the userscript hash regex"
    return b

start_href = (appurl(rows[0]["url"]) + "#akf=" + akf_hash(rows, True)) if rows else "#"

def one_href(j):
    """A single-job auto link: opening it fills AND submits that one job, no chain to break."""
    return appurl(j["url"]) + "#akf=" + akf_hash([j], True)

def age(j):
    ts = j.get("posted_ts")
    if not ts: return ""
    h = (time.time() - ts) / 3600
    return f"{int(h)}h" if h < 48 else f"{int(h/24)}d"

# Done-state is keyed by the job's tag (unique per posting), NOT the row index, and the storage
# key carries the generation date — so a fresh list never inherits stale strike-throughs from a
# previous list's first rows.
GEN = time.strftime("%Y%m%d")
def _hdr(j, prev):
    g = "Maybe already applied (old fresh page, second window, no record): ticked = skipped; untick to include" if j.get("maybe") else (j.get("group") or "")[2:]
    pg = None if prev is None else ("M" if prev.get("maybe") else prev.get("group"))
    cur = "M" if j.get("maybe") else j.get("group")
    if not g or cur == pg: return ""
    n = sum(1 for x in rows if (("M" if x.get("maybe") else x.get("group")) == cur))
    return f'<tr class="grp"><td colspan="6">{H.escape(g)} — {n}</td></tr>'
tr = "\n".join(_hdr(j, rows[i-1] if i else None) +
    f'<tr><td><input type="checkbox" data-k="{H.escape(j.get("tag") or j["url"])}"></td><td class="a">{age(j)}</td>'
    f'<td class="c">{H.escape(j["company"])}</td><td>{H.escape(j["title"])}</td>'
    f'<td class="l">{H.escape((j.get("loc") or "")[:40])}</td>'
    f'<td><a class="go1" href="{H.escape(one_href(j))}" target="_blank" rel="noopener" data-k="{H.escape(j.get("tag") or j["url"])}">Apply ▸</a></td></tr>'
    for i, j in enumerate(rows))

us_path = os.path.join(HERE, "ashby_fill", "ashby_fill.user.js")
ITEMS_JS = json.dumps([dict({"k": (j.get("tag") or j["url"]), "u": appurl(j["url"]), "t": (j.get("title") or "")[:70], "c": (j.get("company") or "")[:40]}, **({"a": j["a"]} if j.get("a") else {})) for j in rows], ensure_ascii=False).replace("</", "<\\/")   # a: per-job answers (filler v.12+)
page = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Job Click Run</title><style>
:root{{--bg:#fff;--fg:#111;--mut:#667;--line:#e5e7eb;--acc:#0a66c2;--card:#f6f8fa;--ok:#15803d;--go:#1a7f37}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#0f1115;--fg:#e8eaf0;--mut:#9aa3b2;--line:#2a2f3a;--acc:#6ab0f3;--card:#171b22;--ok:#4ade80;--go:#2ea043}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;max-width:1060px;margin:24px auto;padding:0 16px}}
h1{{font-size:21px;margin:0}} table{{border-collapse:collapse;width:100%;margin-top:10px}}
td,th{{padding:5px 8px;border-bottom:1px solid var(--line);text-align:left}} .a{{color:var(--mut);font-size:13px;white-space:nowrap}}
.c{{font-weight:600;white-space:nowrap}} .l{{color:var(--mut);font-size:13px}} a{{color:var(--acc)}}
tr.done{{opacity:.42}} tr.done .c{{text-decoration:line-through}} tr.grp td{{background:var(--card);font-weight:700;padding-top:12px}}
.box{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin:12px 0;font-size:14px}}
code{{background:var(--line);padding:1px 6px;border-radius:5px;font-size:13px}}
#prog{{font-size:16px;font-weight:600;color:var(--ok);margin:8px 0}}
.start{{display:inline-block;background:var(--go);color:#fff;font-size:17px;font-weight:700;padding:14px 26px;border-radius:12px;text-decoration:none;margin:6px 0}}
.start:hover{{filter:brightness(1.07)}}
</style></head><body>
<h1>Click Run (Ashby + Lever) — {len(rows)} live, never-applied roles</h1>
<div id="prog"></div>
<div class="box"><b>One-time setup (2 minutes):</b> install the <a href="https://www.tampermonkey.net/" target="_blank">Tampermonkey</a> Chrome extension → Tampermonkey menu → <i>Utilities</i> → <i>Import from file</i> → pick <code>{H.escape(us_path)}</code> → Install. Done forever (it auto-updates from the repo). Or on your Mac: <code>bash ~/ashby.sh setup</code> then <code>bash ~/ashby.sh fill</code>.</div>
<div class="box"><b>Apply to all — one click, hands-free and paced:</b><br>
<a class="start" id="start" href="{H.escape(start_href)}" target="_blank" rel="noopener">▶ Start — apply to all {len(rows)}</a><br>
It opens <b>one tab</b>, confirms once, then fills and submits each role on its own, <b>waiting a random {PACE[0]//1000} to {PACE[1]//1000} seconds before each submission</b> so Ashby does not rate-limit you ("application submission unavailable"). It keeps running with the tab in the background (keep it the front tab of its own window). <b>Run it in ONE window only</b>: a second window now waits for the first (they share one lock), and a job this browser already submitted is skipped automatically. Rows you tick as done below are left out of the queue when you press Start. A captcha (mostly Lever) pops up a desktop notification: tick it and click Submit; after 10 minutes the run moves on without it. It stops after three Ashby blocks in a row (wait an hour, then press Start again).</div>
<div class="box"><b>Run log:</b> every job is logged by the filler: <i>SUBMITTED (confirmation seen)</i>, <i>CLICKED SUBMIT - NO CONFIRMATION</i>, <i>NOT SUBMITTED - needs an answer</i>, <i>BLOCKED</i>, <i>STUCK</i>, <i>CLOSED</i>. On any Ashby page, the filler panel (bottom right) has <b>Run log</b> and <b>Download log</b> (CSV). After clicking Submit it waits up to 90 s for Ashby's own thank-you screen before moving on.</div>
<div class="box"><b>Prefer to pick a few by hand?</b> Click any row's <b>Apply ▸</b> below — it opens one tab that fills and submits that single role. (Do them a minute or two apart, not all at once.)</div>
<table><thead><tr><th></th><th>Age</th><th>Company</th><th>Role</th><th>Location</th><th></th></tr></thead><tbody>{tr}</tbody></table>
<script>
const K='akf_clickrun_{GEN}_{H.escape(os.path.basename(OUT))}';let st=null;try{{st=JSON.parse(localStorage.getItem(K)||'null')}}catch(e){{}}
const DEF={json.dumps([(j.get("tag") or j["url"]) for j in rows if j.get("maybe")])};if(!st){{st={{}};DEF.forEach(k=>st[k]=1);}}
const boxes=document.querySelectorAll('input[type=checkbox][data-k]');
const links=[...document.querySelectorAll('a.go1[data-k]')];
function paint(){{let d=0;boxes.forEach(b=>{{const on=!!st[b.dataset.k];b.checked=on;b.closest('tr').classList.toggle('done',on);if(on)d++}});
document.getElementById('prog').textContent=d+' of {len(rows)} marked done';}}
function save(){{try{{localStorage.setItem(K,JSON.stringify(st))}}catch(e){{}}}}
function mark(k){{st[k]=1;save();paint();}}
boxes.forEach(b=>b.addEventListener('change',()=>{{st[b.dataset.k]=b.checked?1:0;save();paint()}}));
links.forEach(a=>a.addEventListener('click',()=>{{setTimeout(()=>mark(a.dataset.k),800)}}));
const ITEMS={ITEMS_JS};
const ME={json.dumps(ME)};const PACE={json.dumps(PACE)};
function akfHash(items){{let pad='';for(;;){{const js=JSON.stringify({{name:'Ashby queue',auto:true,pad:pad,pace:PACE,me:ME,items:items.map(x=>(x.a?{{u:x.u,t:x.t,c:x.c,a:x.a}}:{{u:x.u,t:x.t,c:x.c}}))}});const b=btoa(unescape(encodeURIComponent(js)));if(!b.includes('='))return b.replace(/\+/g,'-').replace(/\//g,'_');pad+=' ';}}}}
document.getElementById('start').addEventListener('click',function(){{const left=ITEMS.filter(x=>!st[x.k]);if(!left.length){{alert('Every row is ticked as done.');return;}}this.href=left[0].u+'#akf='+akfHash(left);this.textContent='▶ Start — apply to '+left.length+' not yet done';}});
paint();
</script></body></html>"""
os.makedirs(PRIV, exist_ok=True)
open(OUT, "w").write(page)
print(f"{OUT}: {len(rows)} roles, one-click launcher built (skipped {len(queue)-len(rows)} already submitted/ledgered)")
