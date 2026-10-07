#!/usr/bin/env bash
# ~/ashby.sh : every Ashby command in one place (runs on your Mac). It updates itself on every run.
#
#   bash ~/ashby.sh           get the newest job list, then start 2 parallel workers (background, no browser windows)
#   bash ~/ashby.sh start 3   same, with 3 workers (default 2)
#   bash ~/ashby.sh status    submitted / blocked / need-your-answer counts and what each worker is doing
#   bash ~/ashby.sh setup     one-time: opens Tampermonkey's install page (click 'Add to Chrome'), then run 'fill'
#   bash ~/ashby.sh fill      one-time: opens the filler userscript so Tampermonkey installs it (click 'Install')
#   bash ~/ashby.sh click     open the CLICK RUN: only the live never-applied queue; each link auto-fills in your own Chrome (Tampermonkey), you just click Submit
#   bash ~/ashby.sh assist    finish blocked jobs: a window opens with the form filled, you click Submit
#   bash ~/ashby.sh manual    open a page with every job to finish by hand: links plus the answers ready to paste
#   bash ~/ashby.sh report    open a report of every application confirmed as submitted from this Mac
#   bash ~/ashby.sh indeed    open the Indeed jobs to apply by hand (newest first, answers ready to paste)
#   bash ~/ashby.sh sites     open the company-website jobs (Workday, iCIMS...) to apply by hand, grouped by domain
#   bash ~/ashby.sh top       open the top Ashby/Lever roles (leadership, fintech, crypto, AI) to apply by hand in your own browser
#   bash ~/ashby.sh dice      open the Dice jobs to apply by hand while signed in to Dice (Dice's terms do not allow an agent to apply)
#   bash ~/ashby.sh ranked    open every Ashby/Lever role posted in the last 7 days, ranked: executive first, fintech/AI first, newest first
#   bash ~/ashby.sh log       watch the workers live (Ctrl+C stops watching; the run keeps going)
#   bash ~/ashby.sh stop      stop all workers
#   bash ~/ashby.sh update    only download the newest job list and scripts
#   bash ~/ashby.sh fast      keep the Mac awake (12 h) and restart Chrome so a run in a background tab never slows down
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
  # keep this script current: write a new file and rename it over the old one, so the copy bash is
  # reading right now is never rewritten in place (that caused "unexpected EOF" / "near ;;" errors)
  cp -f "$REPO/job-search/ashby.sh" "$HOME/.ashby.sh.new" 2>/dev/null && mv -f "$HOME/.ashby.sh.new" "$HOME/ashby.sh"
}

in_repo() { cd "$REPO" 2>/dev/null || { echo "Not set up yet. Run: bash ~/ashby.sh"; exit 1; }; }

main() {
case "${1:-start}" in
  start)  update; bash job-search/run_ashby.sh start "${2:-2}" ;;
  update) update; echo "Up to date. Start with: bash ~/ashby.sh" ;;
  status) in_repo; bash job-search/run_ashby.sh status ;;
  setup)  update; echo "1) In the tab that opens, click 'Add to Chrome' to install Tampermonkey."; echo "2) Then run:  bash ~/ashby.sh fill   (opens the filler script - click 'Install' on the Tampermonkey page)"
          open "https://chromewebstore.google.com/detail/tampermonkey/dhdgffkkebhmkfjojejmpbldmpobfkfo" 2>/dev/null || echo "Open https://chromewebstore.google.com/detail/tampermonkey/dhdgffkkebhmkfjojejmpbldmpobfkfo" ;;
  fill)   in_repo; open "file://$REPO/job-search/ashby_fill/ashby_fill.user.js" 2>/dev/null || echo "Open file://$REPO/job-search/ashby_fill/ashby_fill.user.js in Chrome"
          echo "Tampermonkey should show an Install page - click Install. If Chrome just shows the code instead: Tampermonkey icon -> Utilities -> Import from file -> pick $REPO/job-search/ashby_fill/ashby_fill.user.js" ;;
  click)  update; python3 job-search/make_click_run.py && { open "$HOME/jobs-private/click_run.html" 2>/dev/null || echo "Open $HOME/jobs-private/click_run.html in your browser"; } ;;
  manual) in_repo; bash job-search/run_ashby.sh manual ;;
  assist) update; bash job-search/run_ashby.sh assist ;;
  report) in_repo; bash job-search/run_ashby.sh report ;;
  indeed) update; open "$REPO/job-search/INDEED_APPLY_BY_HAND.html" 2>/dev/null || echo "Open $REPO/job-search/INDEED_APPLY_BY_HAND.html in your browser" ;;
  top)    update; open "$REPO/job-search/ASHBY_TOP_BY_HAND.html" 2>/dev/null || echo "Open $REPO/job-search/ASHBY_TOP_BY_HAND.html in your browser" ;;
  dice)   update; open "$REPO/job-search/DICE_APPLY_BY_HAND.html" 2>/dev/null || echo "Open $REPO/job-search/DICE_APPLY_BY_HAND.html in your browser" ;;
  ranked) update; open "$REPO/job-search/ASHBY_RANKED_BY_HAND.html" 2>/dev/null || echo "Open $REPO/job-search/ASHBY_RANKED_BY_HAND.html in your browser" ;;
  sites)  update; open "$REPO/job-search/COMPANY_SITES_APPLY_BY_HAND.html" 2>/dev/null || echo "Open $REPO/job-search/COMPANY_SITES_APPLY_BY_HAND.html in your browser" ;;
  stop)   in_repo; bash job-search/run_ashby.sh stop ;;
  log)    tail -n 5 -f "$HOME"/jobs-private/ashby_run/worker_*.log ;;
  fast)   update
          echo "== restarting Chrome with background slow-down switched off (tabs come back if Chrome is set to 'Continue where you left off')"
          osascript -e 'quit app "Google Chrome"' 2>/dev/null; sleep 4
          open -a "Google Chrome" --args --disable-background-timer-throttling --disable-backgrounding-occluded-windows --disable-renderer-backgrounding
          echo "== keeping this Mac awake for 12 hours (the screen stays on). Leave this window open; Ctrl+C stops it."
          echo "   Now open the click-run page in Chrome and press Start. Keep the run tab as the front tab of its own window."
          caffeinate -dimsu -t 43200 ;;
  help|-h|--help) sed -n '2,20p' "$0" ;;
  *)      echo "Unknown command '$1'."; sed -n '2,20p' "$0" ;;
esac
}
# the whole file is read before anything runs, so an update that replaces this file mid-run is harmless
main "$@"; exit $?
