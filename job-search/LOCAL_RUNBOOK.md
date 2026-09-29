# Local runbook (for Claude Code running on the applicant's own computer)

Goal: submit the job applications listed in `job-search/batches/*.json` using `job-search/tools/apply.py`.
They must run from the applicant's own machine because Ashby rejects cloud IPs as spam, Lever shows hCaptcha,
and Greenhouse emails a verification code.

## Steps
1. Ask the applicant for four files and copy them into `~/jobs-private/` (never into the repo):
   `profile.json`, `answers.json`, `Ambarish_Krishnamurthy_Resume.pdf`, `Ambarish_Krishnamurthy_Cover_Letter.pdf`.
   They were provided in the cloud session; look in `~/Downloads` first.
2. Optional: if the applicant wants Greenhouse codes read automatically, help them create `~/jobs-private/wf_creds.json`
   with an `imap` block (Gmail app password; forward the application mailbox to that Gmail). Otherwise the script prompts.
3. Run `bash job-search/run.sh`. It installs Playwright + Chromium, checks the folder, runs all four batches with
   `--submit --headed`, and prints a summary. Each application takes about a minute.
4. For every report in `~/jobs-private/out/*_report.json` with `submitted: false`:
   - `unanswered` non-empty → ask the applicant for those answers, write them to a JSON file of label→answer pairs, and
     re-run that single job: `python3 job-search/tools/apply.py <ats> <url> <tag> --submit --headed --answers file.json`.
   - CAPTCHA / spam / other error → tell the applicant and give them the URL to finish by hand.
5. Report the counts of submitted vs not, and the list of companies submitted.

## Rules
- Never answer a question asking to confirm that no AI assistance was used; leave it for the applicant.
- Never try to bypass CAPTCHAs or spam filters.
- Keep `~/jobs-private/` out of git.
