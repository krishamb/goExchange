#!/usr/bin/env python3
"""Build the browser filler from tools/apply.py's rules + generic.js + core.js:
  ashby_fill.user.js  Tampermonkey/Violentmonkey userscript (fills automatically, runs category batches on Ashby / Lever;
                      on the other ATS domains below generic.js only fills - the applicant reviews and submits)
  ashby_fill.js       the same code for the "Fill Ashby" bookmarklet (loaded from jsDelivr)
usage: python3 build.py <profile.json> <answers.json>
The applicant's email, phone and street address are NOT in the output (export_rules.py writes placeholders and refuses
to export them); the applicant types them once in the filler's Setup panel, which keeps them in their own browser."""
import os, re, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
BRANCH = "claude/ai-founding-engineer-jobs-l1urgc"
RAW = f"https://raw.githubusercontent.com/krishamb/goExchange/{BRANCH}/job-search/ashby_fill/ashby_fill.user.js"
rules = subprocess.run([sys.executable, os.path.join(HERE, "export_rules.py"), sys.argv[1], sys.argv[2]], capture_output=True, text=True, check=True).stdout
core = open(os.path.join(HERE, "core.js")).read()
generic = open(os.path.join(HERE, "generic.js")).read()
# generic.js (fill only) runs on these ATS domains; frames are allowed so embedded forms (iCIMS, Greenhouse embeds) fill too -
# core.js still runs Ashby / Lever in the top window only
GENERIC_MATCH = ["https://jobs.smartrecruiters.com/*", "https://*.icims.com/*", "https://apply.workable.com/*", "https://*.bamboohr.com/*",
    "https://ats.rippling.com/*", "https://jobs.gem.com/*", "https://*.successfactors.com/*", "https://*.successfactors.eu/*",
    "https://*.sapsf.com/*", "https://*.sapsf.eu/*", "https://*.pinpointhq.com/*", "https://workforcenow.adp.com/*", "https://myjobs.adp.com/*",
    "https://*.teamtailor.com/*", "https://*.zohorecruit.com/*", "https://app.dover.com/*", "https://*.ultipro.com/*",
    "https://recruitingbypaycor.com/*", "https://www.recruitingbypaycor.com/*", "https://*.applytojob.com/*", "https://*.clearcompany.com/*",
    "https://www.comeet.com/*", "https://*.oraclecloud.com/*", "https://jobs.jobvite.com/*", "https://app.jobvite.com/*",
    "https://job-boards.greenhouse.io/*", "https://job-boards.eu.greenhouse.io/*", "https://boards.greenhouse.io/*", "https://boards.eu.greenhouse.io/*"]
matches = "".join(f"// @match        {m}\n" for m in GENERIC_MATCH)
ver = re.search(r"const VERSION = '([^']+)'", core).group(1)
header = f"""// ==UserScript==
// @name         Ashby filler (Ambarish)
// @namespace    https://github.com/krishamb/goExchange
// @version      {ver.replace('-', '.')}
// @description  Attaches your resume and answers Ashby and Lever application forms with your rules; batch mode submits only fully answered forms. On SmartRecruiters, iCIMS, Workable, BambooHR, Greenhouse, Jobvite, Oracle and the other ATS sites below it only fills the form: you review, answer the rest and submit.
// @match        https://jobs.ashbyhq.com/*
// @match        https://jobs.lever.co/*
{matches}// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_notification
// @grant        GM_addElement
// @run-at       document-idle
// @updateURL    {RAW}
// @downloadURL  {RAW}
// ==/UserScript==
"""
body = rules + "\n" + generic + "\n" + core
open(os.path.join(HERE, "ashby_fill.user.js"), "w").write(header + body)
open(os.path.join(HERE, "ashby_fill.js"), "w").write(body)
print(f"built {ver}: ashby_fill.user.js {len(header + body)//1024} KB, ashby_fill.js {len(body)//1024} KB")
