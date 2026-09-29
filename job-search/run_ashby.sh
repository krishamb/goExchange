#!/usr/bin/env bash
# Ashby runner for your Mac (Ashby rejects applications sent from cloud servers). Called by ~/ashby.sh.
#
#   bash job-search/run_ashby.sh start [N]   start N parallel workers (default 2), background, no browser windows
#   bash job-search/run_ashby.sh status      submitted / blocked / needs-answers counts, worker state, last log lines
#   bash job-search/run_ashby.sh stop        stop all workers
#   bash job-search/run_ashby.sh manual      build and open a page listing every job to finish by hand, with the links
#                                            and the answers already prepared
#
# Queue: job-search/batches/ashby_all.json (freshest first, at most two roles per company).
# Re-running is safe: submitted jobs are skipped, and jobs the site's spam check blocked are not retried
# automatically (they go to the "manual" page instead).
set -uo pipefail
cd "$(dirname "$0")/.."
export JOBS_DIR="${JOBS_DIR:-$HOME/jobs-private}"
OUTD="$JOBS_DIR/out"; RUN="$JOBS_DIR/ashby_run"
mkdir -p "$OUTD" "$RUN"
PY=python3; command -v python3 >/dev/null || PY=py

stop_workers() {
  for f in "$RUN"/worker_*.pid; do [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null; rm -f "$f"; done
  pkill -f "apply.py batch .*ashby_run/part_" 2>/dev/null
  pkill -f "apply.py batch job-search/batches/ashby_all.json" 2>/dev/null   # an older single-worker run
  [ -f "$JOBS_DIR/ashby_run.pid" ] && kill "$(cat "$JOBS_DIR/ashby_run.pid")" 2>/dev/null
  rm -f "$JOBS_DIR/ashby_run.pid"
}

summary() {
  "$PY" - <<'EOF'
import json, glob, os
d=os.path.expanduser(os.environ.get("JOBS_DIR","~/jobs-private"))
ok=[];spam=[];need=[];other=[]
for f in sorted(glob.glob(os.path.join(d,"out","*_report.json")), key=os.path.getmtime):
    try: r=json.load(open(f))
    except Exception: continue
    if r.get("ats")!="ashby": continue
    res=r.get("result") or ""
    if r.get("submitted"): ok.append(r)
    elif r.get("spam_blocked") or "spam check" in res or "pause browser extensions" in res.lower() or "connection instead" in res: spam.append(r)
    elif r.get("unanswered"): need.append(r)
    else: other.append(r)
print(f"Ashby  submitted: {len(ok)}   blocked by Ashby's spam check: {len(spam)}   need an answer from you: {len(need)}   other: {len(other)}")
for r in need[-8:]: print("  NEEDS ANSWER", r["tag"][:40], "|", "; ".join(u["label"][:60] for u in r["unanswered"][:2]))
for r in other[-5:]: print("  OTHER       ", r["tag"][:40], "|", (r.get("result") or "")[:80])
if spam or need: print("To finish those by hand:  bash ~/ashby.sh manual")
EOF
}

case "${1:-start}" in
  status)
    n=0; for f in "$RUN"/worker_*.pid; do [ -f "$f" ] && kill -0 "$(cat "$f")" 2>/dev/null && n=$((n+1)); done
    echo "workers running: $n"
    summary
    for l in "$RUN"/worker_*.log; do [ -f "$l" ] && { echo "--- $(basename "$l" .log): $(grep -c '"submitted": true' "$l") submitted"; tail -n 1 "$l" | cut -c1-160; }; done
    exit 0;;
  stop) stop_workers; echo "stopped"; exit 0;;
  manual)
    "$PY" - <<'EOF'
import json, glob, os, html, subprocess, sys
d=os.path.expanduser(os.environ.get("JOBS_DIR","~/jobs-private"))
rows=[]
for f in sorted(glob.glob(os.path.join(d,"out","*_report.json")), key=os.path.getmtime):
    try: r=json.load(open(f))
    except Exception: continue
    if r.get("ats")!="ashby" or r.get("submitted"): continue
    res=r.get("result") or ""
    if "ALREADY APPLIED at this company" in res: continue
    why="Ashby's spam check blocked the automated submission" if (r.get("spam_blocked") or "spam check" in res or "connection instead" in res) else ("needs your answer: "+"; ".join(u["label"] for u in r.get("unanswered",[])) if r.get("unanswered") else res[:160])
    ans={**(r.get("filled") or {}), **{k:v for k,v in (r.get("chosen") or {}).items() if v}}
    rows.append((r["tag"], r.get("url",""), why, ans))
out=os.path.join(d,"ashby_apply_by_hand.html")
h=["<!doctype html><meta charset=utf-8><title>Ashby: apply by hand</title>",
   "<style>body{font:15px -apple-system,Segoe UI,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;color:#1d1d1f}",
   "h1{font-size:22px}.job{border:1px solid #ddd;border-radius:10px;padding:14px 16px;margin:14px 0}.job a{font-weight:600}",
   ".why{color:#8a4b00;margin:6px 0}table{border-collapse:collapse;width:100%;margin-top:8px}td{border-top:1px solid #eee;padding:6px;vertical-align:top}",
   "td:first-child{width:38%;color:#555}textarea{width:100%;min-height:38px;font:inherit;border:1px solid #ddd;border-radius:6px}</style>",
   f"<h1>Ashby jobs to finish by hand ({len(rows)})</h1><p>Open each link, fill the form (answers below are ready to copy), and submit. Resume and cover letter: <code>{html.escape(d)}</code>.</p>"]
for tag,url,why,ans in rows:
    h.append(f'<div class=job><a href="{html.escape(url)}" target=_blank>{html.escape(tag.replace("_"," "))}</a><div class=why>{html.escape(why)}</div><table>')
    for k,v in ans.items():
        if k in ("resume","cover letter"): continue
        h.append(f"<tr><td>{html.escape(str(k))}</td><td><textarea readonly onclick='this.select()'>{html.escape(str(v))}</textarea></td></tr>")
    h.append("</table></div>")
open(out,"w").write("\n".join(h))
print(f"{len(rows)} jobs listed in {out}")
if sys.platform=="darwin": subprocess.run(["open",out])
EOF
    exit 0;;
  start) ;;
  *) echo "usage: bash job-search/run_ashby.sh [start [N]|status|stop|manual]"; exit 2;;
esac

N="${2:-2}"
echo "== checking $JOBS_DIR"
missing=0
for f in profile.json answers.json Ambarish_Krishnamurthy_Resume.pdf Ambarish_Krishnamurthy_Cover_Letter.pdf; do
  if [ ! -f "$JOBS_DIR/$f" ]; then
    case "$f" in
      *Resume.pdf) src=$(ls -t "$HOME"/Downloads/*Resume*.pdf 2>/dev/null | head -1 || true);;
      *Cover_Letter.pdf) src=$(ls -t "$HOME"/Downloads/*Cover_Letter*.pdf 2>/dev/null | head -1 || true);;
      *) src=$(ls -t "$HOME"/Downloads/$f 2>/dev/null | head -1 || true);;
    esac
    if [ -n "${src:-}" ] && [ -f "$src" ]; then cp "$src" "$JOBS_DIR/$f"; echo "   copied $src"; else echo "   MISSING: $JOBS_DIR/$f"; missing=1; fi
  fi
done
[ "$missing" = 1 ] && { echo "Put the missing file(s) in $JOBS_DIR and run again."; exit 1; }

echo "== installing Playwright + Chromium (quick after the first time)"
"$PY" -m pip install -q playwright reportlab 2>/dev/null || "$PY" -m pip install -q --user playwright reportlab 2>/dev/null || "$PY" -m pip install -q --break-system-packages playwright reportlab
"$PY" -m playwright install chromium >/dev/null 2>&1 || "$PY" -m playwright install chromium

stop_workers
echo "== splitting the queue across $N workers"
"$PY" - "$N" <<'EOF'
import json, os, re, sys, glob, collections
n=int(sys.argv[1]); d=os.path.expanduser(os.environ.get("JOBS_DIR","~/jobs-private")); run=os.path.join(d,"ashby_run")
q=json.load(open("job-search/batches/ashby_all.json"))
done=set(); blocked=set()
for f in glob.glob(os.path.join(d,"out","*_report.json")):
    try: r=json.load(open(f))
    except Exception: continue
    res=r.get("result") or ""
    if r.get("submitted"): done.add(r.get("tag"))
    elif r.get("spam_blocked") or "spam check" in res or "connection instead" in res: blocked.add(r.get("tag"))
todo=[j for j in q if j["tag"] not in done and j["tag"] not in blocked]
# keep every role of one company on the same worker (the two-per-company check stays exact), spread companies evenly
by=collections.OrderedDict()
for j in todo:
    m=re.search(r"ashbyhq\.com/([^/]+)",j["url"]); by.setdefault((m.group(1) if m else j["tag"]).lower(),[]).append(j)
parts=[[] for _ in range(n)]
for i,(k,js) in enumerate(by.items()): parts[i%n].extend(js)
for i,p in enumerate(parts): json.dump(p,open(os.path.join(run,f"part_{i+1}.json"),"w"),indent=1)
print(f"   {len(todo)} to apply ({len(done)} already submitted, {len(blocked)} blocked earlier and left for 'manual'); per worker: {[len(p) for p in parts]}")
EOF

KEEP=""; command -v caffeinate >/dev/null && KEEP="caffeinate -i"   # keep the Mac awake while it runs
for i in $(seq 1 "$N"); do
  PART="$RUN/part_$i.json"
  [ -s "$PART" ] || continue
  [ "$("$PY" -c "import json;print(len(json.load(open('$PART'))))")" = "0" ] && continue
  nohup $KEEP "$PY" job-search/tools/apply.py batch "$PART" --submit --pace 20 60 > "$RUN/worker_$i.log" 2>&1 &
  echo $! > "$RUN/worker_$i.pid"
  sleep 7   # stagger the starts so the workers do not hit Ashby at the same moment
done
echo "Started. Check progress:  bash ~/ashby.sh status     Finish blocked ones by hand:  bash ~/ashby.sh manual"
