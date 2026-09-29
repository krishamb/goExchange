#!/usr/bin/env bash
# Ashby-only runner for your own Mac (Ashby rejects applications sent from cloud servers).
#
#   bash job-search/run_ashby.sh          start (runs in the background, no browser windows)
#   bash job-search/run_ashby.sh status   progress so far: submitted / not submitted, last lines of the log
#   bash job-search/run_ashby.sh stop     stop the run
#
# It submits job-search/batches/ashby_all.json: every open Ashby role in the queue, freshest first,
# one role per company, companies already applied to from the cloud session removed.
# Re-running is safe: any company that already has a submitted report in ~/jobs-private/out is skipped.
set -uo pipefail
cd "$(dirname "$0")/.."
export JOBS_DIR="${JOBS_DIR:-$HOME/jobs-private}"
LOG="$JOBS_DIR/ashby_run.log"; PIDF="$JOBS_DIR/ashby_run.pid"
PY=python3; command -v python3 >/dev/null || PY=py
mkdir -p "$JOBS_DIR/out"

summary() {
  "$PY" - <<'EOF'
import json, glob, os
d=os.path.expanduser(os.environ.get("JOBS_DIR","~/jobs-private"))
ok=[];bad=[]
for f in sorted(glob.glob(os.path.join(d,"out","*_report.json")), key=os.path.getmtime):
    try: r=json.load(open(f))
    except Exception: continue
    if r.get("ats")!="ashby": continue
    (ok if r.get("submitted") else bad).append(r)
print(f"Ashby submitted: {len(ok)}   not submitted: {len(bad)}")
for r in bad[-15:]:
    why=(r.get("result") or "")[:70]
    if r.get("unanswered"): why="unanswered: "+"; ".join(u["label"][:40] for u in r["unanswered"][:2])
    print("  FAIL", r["tag"][:45], "|", why, "|", r.get("url",""))
EOF
}

case "${1:-start}" in
  status)
    if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then echo "RUNNING (pid $(cat "$PIDF"))"; else echo "NOT RUNNING"; fi
    summary; echo "--- last log lines"; tail -n 5 "$LOG" 2>/dev/null; exit 0;;
  stop)
    if [ -f "$PIDF" ]; then kill "$(cat "$PIDF")" 2>/dev/null; pkill -f "apply.py batch job-search/batches/ashby_all.json" 2>/dev/null; rm -f "$PIDF"; echo "stopped"; else echo "not running"; fi
    exit 0;;
esac

if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then echo "Already running (pid $(cat "$PIDF")). Use: bash job-search/run_ashby.sh status"; exit 0; fi

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

echo "== installing Playwright + Chromium (first run only takes a minute)"
"$PY" -m pip install -q playwright reportlab 2>/dev/null || "$PY" -m pip install -q --user playwright reportlab 2>/dev/null || "$PY" -m pip install -q --break-system-packages playwright reportlab
"$PY" -m playwright install chromium >/dev/null 2>&1 || "$PY" -m playwright install chromium

N=$("$PY" -c "import json;print(len(json.load(open('job-search/batches/ashby_all.json'))))")
echo "== starting $N Ashby applications in the background (headless, 20-60 s apart)"
KEEP=""; command -v caffeinate >/dev/null && KEEP="caffeinate -i"   # keep the Mac awake while it runs
nohup $KEEP "$PY" job-search/tools/apply.py batch job-search/batches/ashby_all.json --submit --pace 20 60 > "$LOG" 2>&1 &
echo $! > "$PIDF"
echo "Started (pid $(cat "$PIDF")). Log: $LOG"
echo "Check progress any time with:   bash job-search/run_ashby.sh status"
