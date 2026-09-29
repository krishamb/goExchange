# Ashby applications: one script in your home folder

Ashby blocks applications sent from cloud servers, so this part runs on your own Mac. The script runs in the
background, opens no browser windows, keeps the Mac awake, and can be stopped and restarted at any time without
applying twice.

## Install once (paste into Terminal)

Paste the whole block from the chat message (or copy `job-search/ashby.sh` from this repo to `~/ashby.sh`).
It creates `~/ashby.sh`.

## Commands

```
bash ~/ashby.sh           # get the newest job list, then start 2 parallel workers
bash ~/ashby.sh status    # submitted / blocked by Ashby's spam check / need your answer
bash ~/ashby.sh manual    # open a page with every job to finish by hand (links + answers ready to paste)
bash ~/ashby.sh log       # watch the workers live (Ctrl+C stops watching; the run keeps going)
bash ~/ashby.sh stop      # stop all workers
bash ~/ashby.sh start 3   # use a different number of workers
```

About Ashby's spam check: Ashby blocks some automated submissions ("use a different connection / pause browser
extensions"). The script does not try to get around that. Those jobs are not retried automatically; they appear on
the `manual` page with the answers prepared, so each one takes about a minute by hand.

`bash ~/ashby.sh` downloads the repo to `~/goExchange` the first time, and updates it every time after that.

## Private files it needs

Folder `~/jobs-private` (never in the repo): `profile.json`, `answers.json`, `Ambarish_Krishnamurthy_Resume.pdf`,
`Ambarish_Krishnamurthy_Cover_Letter.pdf`. They are already there from your earlier run. If one is missing, the
script copies it from `~/Downloads` or tells you exactly which file to put back.

## What it applies to

`job-search/batches/ashby_all.json`: every queued Ashby role, freshest first, at most two roles per company,
companies already at two applications from the cloud session removed. About 20 to 60 seconds between
applications. Confirmation emails go to amba_rish@hotmail.com.

## If something looks wrong

- "Already running": a run is in progress; use `bash ~/ashby.sh status`.
- An older full run (`run.sh`) is also going: stop it with `pkill -f "apply.py batch"`, then start again.
- Jobs listed as not submitted with "unanswered" questions need a human answer; open the link and apply by hand.
