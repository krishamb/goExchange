#!/usr/bin/env bash
# ~/ashby.sh : every Ashby job-application command in one place (runs on your Mac).
#
#   bash ~/ashby.sh          get the newest job list, then start applying (background, no browser windows)
#   bash ~/ashby.sh status   how many submitted / not submitted so far, plus the last log lines
#   bash ~/ashby.sh log      watch the live log (Ctrl+C stops watching; the run keeps going)
#   bash ~/ashby.sh stop     stop the run
#   bash ~/ashby.sh update   only download the newest job list and scripts, do not start
#   bash ~/ashby.sh help     show this list
#
# Safe to run again at any time: jobs already submitted are skipped, and no company gets more than two applications.

REPO="$HOME/goExchange"
BRANCH="claude/ai-founding-engineer-jobs-l1urgc"
URL="https://github.com/krishamb/goExchange.git"
LOG="$HOME/jobs-private/ashby_run.log"

update() {
  if [ ! -d "$REPO/.git" ]; then
    echo "== downloading the repo to $REPO (first time only)"
    git clone -b "$BRANCH" "$URL" "$REPO" || { echo "Could not download the repo. Check your internet / GitHub login and try again."; exit 1; }
  fi
  cd "$REPO" || exit 1
  echo "== getting the newest job list"
  git fetch -q origin "$BRANCH" && git checkout -q "$BRANCH" && git pull -q --ff-only origin "$BRANCH" \
    || echo "   (could not update, using the copy already on this Mac)"
}

case "${1:-start}" in
  start)  update; bash job-search/run_ashby.sh ;;
  update) update; echo "Up to date. Start with: bash ~/ashby.sh" ;;
  status) cd "$REPO" 2>/dev/null || { echo "Not set up yet. Run: bash ~/ashby.sh"; exit 1; }; bash job-search/run_ashby.sh status ;;
  stop)   cd "$REPO" 2>/dev/null || { echo "Nothing to stop."; exit 0; }; bash job-search/run_ashby.sh stop ;;
  log)    [ -f "$LOG" ] && tail -n 30 -f "$LOG" || echo "No log yet. Start with: bash ~/ashby.sh" ;;
  help|-h|--help) sed -n '2,11p' "$0" ;;
  *)      echo "Unknown command '$1'."; sed -n '2,11p' "$0" ;;
esac
