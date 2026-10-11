# Running the Ashby / Lever filler on Windows

The cloud Claude Code session does the searching, screening, Greenhouse / Workday / Oracle / Dice applications, security
codes and the job ledger. Nothing for those needs installing on a laptop: open the same session from the Claude app or
claude.ai/code on any computer and it keeps running.

Only Ashby and Lever need your own browser: Ashby flags applications sent from cloud servers as spam, and Lever shows a
CAPTCHA. The filler is a Tampermonkey userscript that fills and submits those forms in your browser, plus "ASHBY_AUTO_*.html"
pages that hand it a queue of jobs with every question pre-answered.

## One-time setup (about 10 minutes)

1. Install Google Chrome (or use Microsoft Edge).
2. Install the Tampermonkey extension from the Chrome Web Store (Edge: Edge Add-ons store).
3. Let Tampermonkey run scripts: open `chrome://extensions`, then either
   - Chrome 138 or later: click Tampermonkey's **Details** and turn on **Allow User Scripts**, or
   - older Chrome: turn on **Developer mode** (top-right switch).
   In the same Details page also turn on **Allow access to file URLs** (the queue pages are opened from your Downloads folder).
4. Install the filler: open this link in Chrome and click **Install** in the Tampermonkey tab that appears:
   https://raw.githubusercontent.com/krishamb/goExchange/claude/ai-founding-engineer-jobs-l1urgc/job-search/ashby_fill/ashby_fill.user.js
   (It updates itself from the same link, so new answer rules arrive automatically.)
5. Set up the filler once: open any Ashby job page, e.g. https://jobs.ashbyhq.com/ramp . A dark "Ashby filler" panel
   appears at the bottom right. Open **Setup (once)** and fill in:
   - Email: the address you want confirmations sent to (the same one used on your Mac).
   - Phone, and optionally your street address.
   - Resume (architect / engineer roles): your main resume PDF.
   - Executive resume (CTO / VP / Head / Director / Manager): your executive resume PDF.
   - Cover letter (optional).
   - Tick **Fill automatically when an application opens**, then **Save**. The panel lists the saved files.
6. Keep the laptop awake while a run is going: Settings > System > Power > Screen and sleep > "Never" (plugged in).

## Each run

1. In the Claude session, download the newest `ASHBY_AUTO_*.html` file (the file cards in the chat) to Downloads.
2. Double-click it to open it in Chrome.
3. Click **START**. The page opens each job in one tab; the filler fills it, submits only when every required question is
   answered, waits for Ashby's confirmation, and moves on. It pauses on a CAPTCHA (solve it yourself, it continues) and
   stops after two spam blocks in a row.
4. Leave the tab open until it finishes. Confirmation emails arrive in your inbox; the cloud session reads them and
   records the applications in `job-search/applied_gmail.json`.

## Rules that avoid double applications

- Run each page on one computer only. The filler remembers what it submitted in that browser only, so the Mac and the
  Windows laptop do not know about each other's runs.
- Pages marked `_WIN` were rebuilt without the roles already confirmed by email.
- Do not re-run a page after it finishes; ask the session for a fresh page instead.

## Running Claude Code itself on the Windows laptop (optional)

Not needed for the filler. If you want a local Claude Code session (for example to run the Python bots from your own
network), install the Claude desktop app for Windows, or Claude Code in a terminal, open a folder with this repository
(`git clone https://github.com/krishamb/goExchange` then `git checkout claude/ai-founding-engineer-jobs-l1urgc`), and keep
your private files (profile, resumes, passwords) in a folder outside the repository, never in git.
