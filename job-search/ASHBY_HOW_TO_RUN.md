# Ashby applications — how to run them on your Mac

Ashby blocks applications sent from cloud servers, so this part runs on your own Mac. It runs in the
background, opens no browser windows, keeps the Mac awake, and can be stopped and restarted at any time
without applying twice.

## Every time (2 commands)

Open **Terminal** and paste:

```
cd ~/goExchange && git checkout claude/ai-founding-engineer-jobs-l1urgc && git pull origin claude/ai-founding-engineer-jobs-l1urgc
bash job-search/run_ashby.sh
```

That's it. The first line gets the newest job list. The second line starts applying and returns you to the
prompt right away; the applications continue in the background.

## Check progress, or stop

```
bash job-search/run_ashby.sh status
bash job-search/run_ashby.sh stop
```

`status` shows how many were submitted, the last few that were not (with the reason and link), and the end of
the log. You can close Terminal; the run keeps going. If the Mac restarts, run the two commands again. Jobs
already submitted are skipped automatically.

## Only the very first time on a new Mac

If `cd ~/goExchange` says "No such file or directory", download the repo once:

```
git clone -b claude/ai-founding-engineer-jobs-l1urgc https://github.com/krishamb/goExchange.git ~/goExchange
```

The script also needs four private files in the folder `~/jobs-private` (never in the repo):
`profile.json`, `answers.json`, `Ambarish_Krishnamurthy_Resume.pdf`, `Ambarish_Krishnamurthy_Cover_Letter.pdf`.
They are already there from your earlier run. If one is missing, the script copies it from `~/Downloads`
or tells you exactly which file to put back.

## What it applies to

`job-search/batches/ashby_all.json`: every queued Ashby role, freshest first, at most two roles per company,
companies already at two applications from the cloud session removed. About 20 to 60 seconds between
applications. Confirmation emails go to amba_rish@hotmail.com.

## If something looks wrong

- "Already running": a run is in progress; use `status`.
- An older full run (`run.sh`) is also going: stop it with `pkill -f "apply.py batch"`, then start again.
- Jobs listed as not submitted with "unanswered" questions need a human answer; open the link and apply by hand.
