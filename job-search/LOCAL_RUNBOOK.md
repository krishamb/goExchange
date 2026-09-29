# Local runbook (for Claude Code, or the applicant, on the applicant's own computer)

Goal: submit the remaining job applications listed in `job-search/batches/local_01.json` and `local_02.json`
(48 Ashby postings + 4 Lever postings) with `job-search/tools/apply.py`.

Why local: Ashby rejects every submission from a cloud IP as "possible spam" (tested twice, with two email
addresses), and Lever shows an hCaptcha at submit. The Greenhouse postings (batches `cloud_gh_01/02`) were
already submitted from the cloud session (see the report the session produced), so `run.sh` no longer runs them.

## Steps
1. Put four files in `~/jobs-private/` (never inside the repo). They were provided in the cloud session; look in
   `~/Downloads` first:
   `profile.json` (email is ambarishkrishnamurthy@gmail.com), `answers.json`,
   `Ambarish_Krishnamurthy_Resume.pdf`, `Ambarish_Krishnamurthy_Cover_Letter.pdf`.
2. Run `bash job-search/run.sh`. It installs Playwright + Chromium, checks the folder, runs both batches with
   `--submit --headed`, and prints a summary. Each application takes about a minute. When Lever shows an hCaptcha,
   solve it in the Chrome window; the script waits.
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
