#!/usr/bin/env bash
# One-shot runner: installs what it needs, checks your private folder, submits every batch, prints a summary.
# Usage:  bash job-search/run.sh            (from the repo root, on your own computer)
set -euo pipefail
cd "$(dirname "$0")/.."
export JOBS_DIR="${JOBS_DIR:-$HOME/jobs-private}"
PY=python3; command -v python3 >/dev/null || PY=py

echo "== 1/4 installing dependencies"
$PY -m pip install -q playwright reportlab
$PY -m playwright install chromium >/dev/null 2>&1 || $PY -m playwright install chromium

echo "== 2/4 checking $JOBS_DIR"
mkdir -p "$JOBS_DIR"
missing=0
for f in profile.json answers.json Ambarish_Krishnamurthy_Resume.pdf Ambarish_Krishnamurthy_Cover_Letter.pdf; do
  if [ ! -f "$JOBS_DIR/$f" ]; then
    # try to pick it up from ~/Downloads automatically
    case "$f" in
      Ambarish_Krishnamurthy_Resume.pdf) src=$(ls -t "$HOME"/Downloads/*Resume*.pdf "$HOME"/Downloads/*Distinguished_Architect*.pdf 2>/dev/null | head -1 || true);;
      Ambarish_Krishnamurthy_Cover_Letter.pdf) src=$(ls -t "$HOME"/Downloads/*Cover_Letter*.pdf 2>/dev/null | head -1 || true);;
      *) src=$(ls -t "$HOME"/Downloads/$f 2>/dev/null | head -1 || true);;
    esac
    if [ -n "${src:-}" ] && [ -f "$src" ]; then cp "$src" "$JOBS_DIR/$f"; echo "   copied $src -> $JOBS_DIR/$f"; else echo "   MISSING: $JOBS_DIR/$f"; missing=1; fi
  fi
done
if [ "$missing" = 1 ]; then
  echo "Put the missing file(s) in $JOBS_DIR (or in ~/Downloads) and run this again."; exit 1
fi
# The Greenhouse batches (cloud_gh_01/02) were submitted from the cloud session; only Ashby + Lever remain.
# Ashby rejects cloud IPs as "possible spam" and Lever shows hCaptcha, so these must run from your own computer.
echo "== 3/4 submitting batches, one application every few minutes (a Chrome window will open; leave it alone; solve any hCaptcha it shows)"
for b in job-search/batches/local_01.json job-search/batches/local_02.json job-search/batches/local_03.json; do
  [ -f "$b" ] || continue
  echo "---- $b"
  $PY job-search/tools/apply.py batch "$b" --submit --headed --pace 45 150 || true
done

echo "== 4/4 summary"
$PY - <<'EOF'
import json, glob, os
ok=fail=0
for f in sorted(glob.glob(os.path.join(os.path.expanduser(os.environ.get("JOBS_DIR","~/jobs-private")),"out","*_report.json"))):
    r=json.load(open(f)); s=bool(r.get("submitted")); ok+=s; fail+=(not s)
    print(("OK   " if s else "FAIL "), r["tag"][:55], "|", [u["label"][:40] for u in r.get("unanswered",[])], "|", (r.get("errors") or [""])[0][:70])
print(f"\nsubmitted: {ok}   not submitted: {fail}   (details + screenshots in $JOBS_DIR/out)")
EOF
