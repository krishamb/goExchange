#!/usr/bin/env python3
"""Click-run page: ONLY the still-open, never-applied Ashby queue (not the historic piles).

Runs on the applicant's Mac. Reads the current queue (batches/ashby_all.json), drops anything
with a submitted report in ~/jobs-private/out/ and any company in the Gmail applied ledger
shipped with the repo, and writes ~/jobs-private/click_run.html, newest first.
With the Tampermonkey filler installed, each link auto-fills on open; the applicant clicks
Submit. Done-state lives in the page (localStorage) so progress survives reopening.
"""
import json, re, os, glob, time, html as H

HERE = os.path.dirname(os.path.abspath(__file__))
PRIV = os.path.expanduser(os.environ.get("JOBS_DIR", "~/jobs-private"))
OUT = os.path.join(PRIV, "click_run.html")

def norm(s): return re.sub(r"[^a-z0-9]", "", str(s or "").lower())

queue = json.load(open(os.path.join(HERE, "batches", "ashby_all.json")))

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
for j in sorted(queue, key=lambda x: -(x.get("posted_ts") or 0)):
    if j.get("tag") in done_tags or norm(j.get("company")) in done_cos | ledger: continue
    rows.append(j)

def age(j):
    ts = j.get("posted_ts")
    if not ts: return ""
    h = (time.time() - ts) / 3600
    return f"{int(h)}h" if h < 48 else f"{int(h/24)}d"

tr = "\n".join(
    f'<tr id="r{i}"><td><input type="checkbox" data-i="{i}"></td><td class="a">{age(j)}</td>'
    f'<td class="c">{H.escape(j["company"])}</td><td>{H.escape(j["title"])}</td>'
    f'<td class="l">{H.escape((j.get("loc") or "")[:40])}</td>'
    f'<td><a href="{H.escape(j["url"])}" target="_blank" rel="noopener" data-i="{i}">Open &amp; fill</a></td></tr>'
    for i, j in enumerate(rows))

us_path = os.path.join(HERE, "ashby_fill", "ashby_fill.user.js")
page = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ashby Click Run</title><style>
:root{{--bg:#fff;--fg:#111;--mut:#667;--line:#e5e7eb;--acc:#0a66c2;--card:#f6f8fa;--ok:#15803d}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#0f1115;--fg:#e8eaf0;--mut:#9aa3b2;--line:#2a2f3a;--acc:#6ab0f3;--card:#171b22;--ok:#4ade80}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;max-width:1060px;margin:24px auto;padding:0 16px}}
h1{{font-size:21px;margin:0}} table{{border-collapse:collapse;width:100%;margin-top:10px}}
td,th{{padding:5px 8px;border-bottom:1px solid var(--line);text-align:left}} .a{{color:var(--mut);font-size:13px;white-space:nowrap}}
.c{{font-weight:600;white-space:nowrap}} .l{{color:var(--mut);font-size:13px}} a{{color:var(--acc)}}
tr.done{{opacity:.42}} tr.done .c{{text-decoration:line-through}}
.box{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin:12px 0;font-size:14px}}
code{{background:var(--line);padding:1px 6px;border-radius:5px;font-size:13px}}
#prog{{font-size:16px;font-weight:600;color:var(--ok);margin:8px 0}}
</style></head><body>
<h1>Ashby Click Run — {len(rows)} live, never-applied roles</h1>
<div id="prog"></div>
<div class="box"><b>One-time setup (2 minutes):</b> install the <a href="https://www.tampermonkey.net/" target="_blank">Tampermonkey</a> Chrome extension → Tampermonkey menu → <i>Utilities</i> → <i>Import from file</i> → pick <code>{H.escape(us_path)}</code> → Install. Done forever (it auto-updates from the repo).</div>
<div class="box"><b>The run:</b> click <i>Open &amp; fill</i> → the form fills itself in a few seconds → click <b>Submit application</b> on the page → close the tab → tick the row. Repeat. About 15 seconds each.</div>
<table><thead><tr><th></th><th>Age</th><th>Company</th><th>Role</th><th>Location</th><th></th></tr></thead><tbody>{tr}</tbody></table>
<script>
const K='akf_clickrun_v1';let st={{}};try{{st=JSON.parse(localStorage.getItem(K)||'{{}}')}}catch(e){{}}
const boxes=document.querySelectorAll('input[type=checkbox]');
function paint(){{let d=0;boxes.forEach(b=>{{const on=!!st[b.dataset.i];b.checked=on;b.closest('tr').classList.toggle('done',on);if(on)d++}});
document.getElementById('prog').textContent=d+' of {len(rows)} submitted';}}
function save(){{try{{localStorage.setItem(K,JSON.stringify(st))}}catch(e){{}}}}
boxes.forEach(b=>b.addEventListener('change',()=>{{st[b.dataset.i]=b.checked?1:0;save();paint()}}));
document.querySelectorAll('a[data-i]').forEach(a=>a.addEventListener('click',()=>{{setTimeout(()=>{{st[a.dataset.i]=1;save();paint()}},800)}}));
paint();
</script></body></html>"""
os.makedirs(PRIV, exist_ok=True)
open(OUT, "w").write(page)
print(f"{OUT}: {len(rows)} roles (skipped {len(queue)-len(rows)} already submitted/ledgered)")
