#!/usr/bin/env python3
"""Build a retry batch from the jobs of one or more batch files whose latest report says submitted=false.
Usage: python3 job-search/tools/retry_batch.py <out.json> <batch.json> [<batch.json> ...]
Reads $JOBS_DIR/out/<tag>_report.json (default JOBS_DIR: the session scratchpad). Jobs without a report are included too."""
import json, os, sys
JOBS_DIR=os.path.expanduser(os.environ.get("JOBS_DIR","/tmp/claude-0/-home-user-goExchange/8d20ffb7-2488-5f8f-a666-35334b9e3ba6/scratchpad/f"))
OUT=os.path.join(JOBS_DIR,"out")
dest,srcs=sys.argv[1],sys.argv[2:]
retry=[]; done=[]; seen=set()
for s in srcs:
    for job in json.load(open(s)):
        if job["tag"] in seen: continue
        seen.add(job["tag"])
        rp=os.path.join(OUT,job["tag"]+"_report.json")
        r=json.load(open(rp)) if os.path.exists(rp) else None
        if r and r.get("submitted"): done.append(job["tag"]); continue
        job=dict(job); job["last_result"]=(r or {}).get("result","(no report)")[:100]
        job["last_unanswered"]=[u.get("label","")[:80] for u in (r or {}).get("unanswered",[])]
        retry.append(job)
json.dump(retry,open(dest,"w"),indent=1)
print(f"submitted: {len(done)}   to retry: {len(retry)} -> {dest}")
for j in retry: print(" -", j["tag"][:55], "|", j["last_result"][:60], "|", j["last_unanswered"][:3])
