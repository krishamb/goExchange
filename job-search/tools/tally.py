#!/usr/bin/env python3
"""Summarise application reports for the jobs in the given batch files into a Markdown table.
Usage: python3 job-search/tools/tally.py <out.md> <batch.json> [<batch.json> ...]"""
import json, os, sys, datetime
JOBS_DIR=os.path.expanduser(os.environ.get("JOBS_DIR","/tmp/claude-0/-home-user-goExchange/8d20ffb7-2488-5f8f-a666-35334b9e3ba6/scratchpad/f"))
OUT=os.path.join(JOBS_DIR,"out")
dest,srcs=sys.argv[1],sys.argv[2:]
rows=[]; seen=set()
for s in srcs:
    for job in json.load(open(s)):
        if job["tag"] in seen: continue
        seen.add(job["tag"])
        rp=os.path.join(OUT,job["tag"]+"_report.json")
        r=json.load(open(rp)) if os.path.exists(rp) else {}
        status="submitted" if r.get("submitted") else ("not submitted" if r else "not attempted")
        why=""
        if not r.get("submitted"):
            why="; ".join(u.get("label","")[:60] for u in r.get("unanswered",[])[:2]) or ((r.get("errors") or [""])[0][:80]) or r.get("result","")[:80]
        comp=job.get("comp"); comp=f"${int(comp):,}" if isinstance(comp,(int,float)) and comp else ""
        rows.append((job.get("company",""),job.get("title",""),comp,status,why,job.get("url","")))
ok=sum(1 for x in rows if x[3]=="submitted")
with open(dest,"w") as f:
    f.write(f"# Applications submitted {datetime.date.today().isoformat()}\n\n")
    f.write(f"**{ok} submitted** out of {len(rows)} attempted (Greenhouse, from the cloud session, applicant email ambarishkrishnamurthy@gmail.com).\n\n")
    f.write("| # | Company | Title | Posted pay | Status | Note |\n|---|---|---|---|---|---|\n")
    for i,(c,t,p,st,why,u) in enumerate(sorted(rows,key=lambda x:(x[3]!="submitted",x[0])),1):
        f.write(f"| {i} | {c} | [{t}]({u}) | {p} | {st} | {why} |\n")
print(f"{ok}/{len(rows)} submitted -> {dest}")
for c,t,p,st,why,u in rows:
    if st!="submitted": print(" -",st,":",c,"|",t[:50],"|",why[:70])
