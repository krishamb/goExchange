# Local runbook (for Claude Code, or the applicant, on the applicant's own computer)

Goal: submit the remaining job applications listed in the local batches with `job-search/tools/apply.py`.
`run.sh` runs them in this order: `local_08_fresh7.json` (13 Ashby/Lever roles posted in the last 7 days, incl.
two Lever links found through Wellfound), `local_06_bay_ai.json`, `local_07_fresh14.json`, `local_05_fresh.json`,
`local_04_cpp_rust.json` (C++/Rust), then `local_01.json`, `local_02.json`, `local_03.json`.
Before every run: `git pull` on branch `claude/ai-founding-engineer-jobs-l1urgc` (new batches and filler fixes
land there through the day). The filler submits one application per company: it skips any job whose company already
has a submitted report in `~/jobs-private/out/`, so re-running the whole list never double-applies.
Every local batch entry carries `"email": "amba_rish@hotmail.com"` (the filler uses it instead of the profile
email), so Ashby/Lever confirmations arrive in that Hotmail inbox; Greenhouse stays on Gmail (security codes)
and Wellfound on ambarishmd23@hotmail.com (the account email).
Re-tested on 2026-09-29 19:05 UTC: Ashby still returns "Your application submission was flagged as possible
spam" for any submission from the cloud IP, so these batches only work from the applicant's own computer.

Why local: Ashby rejects every submission from a cloud IP as "possible spam" (tested twice, with two email
addresses), and Lever shows an hCaptcha at submit. The Greenhouse postings (batches `cloud_gh_01/02`) were
already submitted from the cloud session (see the report the session produced), so `run.sh` no longer runs them.

## Ashby only (simplest)
From the repo folder on your Mac:
1. `git pull origin claude/ai-founding-engineer-jobs-l1urgc`
2. `bash job-search/run_ashby.sh` (starts in the background, no browser windows, keeps the Mac awake)
Progress: `bash job-search/run_ashby.sh status`. Stop: `bash job-search/run_ashby.sh stop`.
It submits `batches/ashby_all.json`: every queued Ashby role, freshest first, one per company, with companies
already applied to from the cloud removed.

## Steps
1. Put four files in `~/jobs-private/` (never inside the repo). They were provided in the cloud session; look in
   `~/Downloads` first:
   `profile.json` (email is (your Gmail)), `answers.json`,
   `Ambarish_Krishnamurthy_Resume.pdf`, `Ambarish_Krishnamurthy_Cover_Letter.pdf`.
2. Run it in the background so no browser windows appear (the run is headless):
   `nohup bash job-search/run.sh > ~/jobs-private/run.log 2>&1 &` and follow it with `tail -f ~/jobs-private/run.log`.
   It installs Playwright + Chromium, checks the folder, runs every batch with `--submit` and a 20-60 s pace, and
   prints a summary. A Lever hCaptcha cannot be solved headless: those jobs are reported as not submitted with the
   URL, to finish by hand.
3. For every report in `~/jobs-private/out/*_report.json` with `submitted: false`:
   - `unanswered` non-empty → the report lists the question and its options; write label→answer pairs to a JSON
     file and re-run that single job:
     `python3 job-search/tools/apply.py <ats> <url> <tag> --submit --headed --answers file.json`.
   - CAPTCHA / spam / other error → give the applicant the URL to finish by hand.
4. Report the counts of submitted vs not, and the list of companies submitted.

Indeed comes last: from a cloud IP its search and sign-in pages show a security check / CAPTCHA, so it needs a
real browser on this computer, signed in with the applicant's Google account.

## Rules
- Never answer a question asking to confirm that no AI assistance was used; leave it for the applicant
  (the script leaves such questions unanswered and lists them in the report).
- Never try to bypass CAPTCHAs or spam filters.
- Keep `~/jobs-private/` out of git.
