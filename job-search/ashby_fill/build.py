#!/usr/bin/env python3
"""Build the browser filler from tools/apply.py's rules + core.js:
  ashby_fill.user.js  Tampermonkey/Violentmonkey userscript (fills automatically, runs category batches)
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
ver = re.search(r"const VERSION = '([^']+)'", core).group(1)
header = f"""// ==UserScript==
// @name         Ashby filler (Ambarish)
// @namespace    https://github.com/krishamb/goExchange
// @version      {ver.replace('-', '.')}
// @description  Attaches your resume and answers Ashby and Lever application forms with your rules; batch mode submits only fully answered forms.
// @match        https://jobs.ashbyhq.com/*
// @match        https://jobs.lever.co/*
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_notification
// @run-at       document-idle
// @noframes
// @updateURL    {RAW}
// @downloadURL  {RAW}
// ==/UserScript==
"""
body = rules + "\n" + core
open(os.path.join(HERE, "ashby_fill.user.js"), "w").write(header + body)
open(os.path.join(HERE, "ashby_fill.js"), "w").write(body)
print(f"built {ver}: ashby_fill.user.js {len(header + body)//1024} KB, ashby_fill.js {len(body)//1024} KB")
