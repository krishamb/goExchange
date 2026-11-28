# Job-search routine: standing rules (durable copy)

The session scratchpad is wiped when the cloud container is replaced (it happened at ~04:22Z on 2026-11-28 and took
every sweep tool, queue and private file with it). Rules, tools and open work that carry no personal data now live
here, in the repository, and are committed after each change. Personal data never goes in the repository.

## Goal and routing
- At least 100 applications per Pacific day.
- Apply directly with a bot whenever one can submit: Greenhouse `tools/apply.py`, Workday `tools/apply_workday.py`,
  Oracle Recruiting Cloud `tools/apply_oraclecloud.py`, Jobvite `tools/apply_jobvite.py`.
- Ashby and Lever roles go to the one-click file (never submitted from the cloud).
- Everything else goes to the Apply Myself file (contact-free).
- Send each file in its own message when 5+ new rows have accumulated, and in the 9 PM routine.
- Rows for the files live in `pipeline/rows.json` (`rows.py add` a JSON list with route one_click / apply_myself /
  bot_hold). When 5+ unsent one_click + apply_myself rows exist run `rows.py build new`; in the 9 PM routine run
  `rows.py build all`. Send each built file in its own SendUserFile call, then `rows.py mark-sent`. Bot-lane roles
  that cannot submit yet are bot_hold rows, listed last in the Apply Myself file.

## Screening
- Pay: the stated maximum must be at least $180K; unstated pay is fine.
- At most 3 roles per company, each in a different level bucket; never the same role twice.
- Posting window: 7 days (LinkedIn / Indeed 24 h; applicant-named company lists: any open role). Use the employer
  ATS publish date; a LinkedIn or aggregator repost does not reset it.
- Location: remote US, or SF Bay Area on-site / hybrid. No on-site / hybrid elsewhere, no NYC unless the applicant
  allows it again. Financial institutions: remote or Bay Area only.
- Titles: leadership first (CTO, VP / SVP Engineering, VP / Head of AI, Head of Engineering, Director / Sr Director
  of Engineering), then Senior / Staff / Principal IC engineers (software, AI/ML, platform, data, infra, backend,
  full-stack, FDE) and architects.
- Excluded roles: sales, pre-sales, field, customer success, product management, design, security-only, SRE / DevOps,
  QA, front-end, mobile, hardware / firmware / manufacturing, research.
- Excluded titles: unleveled ("Software Engineer"), founding, MTS, co-founder.
- Excluded employers / terms: staffing and recruiters (incl. hiring-platform listings for unnamed clients), consulting
  delivery, contract / hourly, active clearance, never-apply companies (NEVER_APPLY in tools/apply.py; never Global
  Settlement Miami, Morgan Stanley, Apaca).
- Frontier labs: finance-related engineering roles only.
- Companies the applicant is interviewing with (interviewing.json) or that rejected the applicant stay blocked.

## Source rules
- Stop at the first 401 / 403 / 406 / 429 / 503 and pause that host 24 h; never retry past a refusal.
- LinkedIn: public guest pages only, never signed in; about 8 requests a day at hourly spacing work, then 429.
  Spend them on search pages (one Boolean leadership query per request) and resolve candidates on employer sites.
- Greenhouse boards API: harvest every other hour at most. Never read the seatgeek board.
- Jobvite: one board at a time with 3-4 s gaps.
- Never fetch the a16z (Consider) board, indeed.com or theladders.com; job-alert emails are read in Gmail only and
  their tracking links are never followed.
- Never sign in to Built In, YC Work at a Startup, LinkedIn or any job board.

## Safety
- Gmail is read-only. Never solve CAPTCHAs or human checks, never enter SSN / DOB / ID numbers, never take
  assessments, never sign e-signatures or attestations, never answer a question outside the applicant's facts.
- Salary answer, when asked: "$220,000 - $350,000 (negotiable, depending on scope)".
- Before every commit: no email addresses and no phone numbers in the diff.

## Sweep tools (pipeline/, rebuilt 2026-11-28)
Rows land in `<scratchpad>/harvest/`; review them, then route them with `rows.py add`.
- `harvest.py <tag> [days] [ats]`: Ashby / Lever every check-in; Greenhouse every other hour (`gh_last` in blocks.json).
- `builtin.py <tag>`: Built In remote / Bay Area listings, every check-in.
- `feeds.py <tag>`: RemoteOK, We Work Remotely, Working Nomads every check-in; Remotive at most every 6 h and Jobicy
  every 3 h (the tool enforces both).
- `getro.py <tag> [hours]`: VC / crypto Getro boards, every few hours.
- `oracle.py <tag> [days]`: Oracle Recruiting Cloud tenants in orc_tenants.json (keyword searches, newest first),
  every few hours; add tenants found on other boards (host + CX site number) to orc_tenants.json.
- `gates.py "Company|Title"`: the company / role gates; `rows.py`: the file rows.
- Job-alert emails (Indeed, LinkedIn, Built In ...): read in Gmail, resolve each role on the employer's own site.

## Seen cutoff after the reset
The old pipeline had screened every Ashby / Lever posting published before 2026-11-28T03:40Z and every Greenhouse
posting published before 2026-11-27T04:19:36Z (its rows are in the applicant's files, applied, or dropped on closer
reading), so harvest.py only surfaces newer postings (HARVEST_ALL=1 disables the cutoff).

## Private files (outside the repo; must be re-provided after a container reset)
`JOBS_DIR` (the bots default to `<scratchpad>/f`): profile.json, the resume PDFs (main, executive, architect),
the cover letter PDF, answers.json, wf_creds.json (email-code reader / Workday sign-in) and the private rejected list.
