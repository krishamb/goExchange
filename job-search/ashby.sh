#!/usr/bin/env bash
# ~/ashby.sh : every Ashby command in one place (runs on your Mac). It updates itself on every run.
#
#   bash ~/ashby.sh           get the newest job list, then start 2 parallel workers (background, no browser windows)
#   bash ~/ashby.sh start 3   same, with 3 workers (default 2)
#   bash ~/ashby.sh status    submitted / blocked / need-your-answer counts and what each worker is doing
#   bash ~/ashby.sh assist    finish blocked jobs: a window opens with the form filled, you click Submit
#   bash ~/ashby.sh manual    open a page with every job to finish by hand: links plus the answers ready to paste
#   bash ~/ashby.sh report    open a report of every application confirmed as submitted from this Mac
#   bash ~/ashby.sh indeed    open the Indeed jobs to apply by hand (newest first, answers ready to paste)
#   bash ~/ashby.sh log       watch the workers live (Ctrl+C stops watching; the run keeps going)
#   bash ~/ashby.sh stop      stop all workers
#   bash ~/ashby.sh update    only download the newest job list and scripts
#   bash ~/ashby.sh help      show this list

REPO="$HOME/goExchange"
BRANCH="claude/ai-founding-engineer-jobs-l1urgc"
URL="https://github.com/krishamb/goExchange.git"

update() {
  if [ ! -d "$REPO/.git" ]; then
    echo "== downloading the repo to $REPO (first time only)"
    git clone -b "$BRANCH" "$URL" "$REPO" || { echo "Could not download the repo. Check your internet / GitHub login and try again."; exit 1; }
  fi
  cd "$REPO" || exit 1
  echo "== getting the newest job list"
  git fetch -q origin "$BRANCH" && git checkout -q "$BRANCH" && git pull -q --ff-only origin "$BRANCH" \
    || echo "   (could not update, using the copy already on this Mac)"
  cp -f "$REPO/job-search/ashby.sh" "$HOME/ashby.sh" 2>/dev/null   # keep this script current
}

in_repo() { cd "$REPO" 2>/dev/null || { echo "Not set up yet. Run: bash ~/ashby.sh"; exit 1; }; }

case "${1:-start}" in
  start)  update; bash job-search/run_ashby.sh start "${2:-2}" ;;
  update) update; echo "Up to date. Start with: bash ~/ashby.sh" ;;
  status) in_repo; bash job-search/run_ashby.sh status ;;
  manual) in_repo; bash job-search/run_ashby.sh manual ;;
  assist) update; bash job-search/run_ashby.sh assist ;;
  report) in_repo; bash job-search/run_ashby.sh report ;;
  indeed) update; open "$REPO/job-search/INDEED_APPLY_BY_HAND.html" 2>/dev/null || echo "Open $REPO/job-search/INDEED_APPLY_BY_HAND.html in your browser" ;;
  stop)   in_repo; bash job-search/run_ashby.sh stop ;;
  log)    tail -n 5 -f "$HOME"/jobs-private/ashby_run/worker_*.log ;;
  help|-h|--help) sed -n '2,15p' "$0" ;;
  *)      echo "Unknown command '$1'."; sed -n '2,15p' "$0" ;;
esac
