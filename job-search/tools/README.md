# Job application pipeline

- `apply.py` fills and submits applications on Lever, Greenhouse, Ashby and Wellfound (Playwright + Chromium).
- `cover.py` generates a per-posting cover letter (text + PDF) from the job description.
- `../batches/*.json` are job lists (ATS, apply URL, company, title, posted pay). No personal data.

## Running locally (recommended for Ashby/Workable/SmartRecruiters, which reject cloud IPs as spam)

```bash
pip install playwright reportlab && python -m playwright install chromium
export JOBS_DIR=~/jobs-private            # NOT inside the repo
mkdir -p $JOBS_DIR && cp Resume.pdf $JOBS_DIR/Ambarish_Krishnamurthy_Resume.pdf
# $JOBS_DIR/profile.json: {"name","email","phone","location","org","linkedin","github","resume","cover_letter"}
# $JOBS_DIR/answers.json: {"why_us","impact","environment"}  (free-text defaults)
# $JOBS_DIR/wf_creds.json (optional): {"outlook":{"email":"you@hotmail.com","password":"..."}} lets the script read
#   Greenhouse's emailed verification codes from your Hotmail inbox in the automated browser (run.sh asks for this once).
#   "imap": {"host","user","password"} works for a Gmail app password instead. With neither, the script prompts you to
#   type each code. "email"/"password" at the top level are the Wellfound login, only if you apply there.
python job-search/tools/apply.py batch job-search/batches/local_01.json --submit --headed   # Ashby + Lever, 50 jobs
python job-search/tools/apply.py batch job-search/batches/cloud_gh_01.json --submit --headed # Greenhouse, 50 jobs (needs emailed codes)
python job-search/tools/apply.py ashby <apply-url> <tag> --submit                        # single job
```
Reports and screenshots land in `$JOBS_DIR/out/`. Jobs with required questions the rules can't answer are left
unsubmitted and listed under `unanswered` in the report; pass `--answers file.json` with label→answer pairs to fill them.
The script never answers "did you use AI assistance" questions; those are left for the applicant.
