"""Company / role gates for every sweep, queue and applicant file (rebuilt 2026-11-28 after the container reset).

allow(company, title) -> (ok, reason). A row passes only if the company is not on the never-apply list, the
applicant is not interviewing there, the company never rejected the applicant, and the company is still under the
3-roles cap: applied (ledger) + queued / listed (queued.json) roles stay under 3, the new role is not the same role
as one already applied to or queued, and its level bucket is not used yet at that company.
Sources (all in the repository, no personal data): ../applied_gmail.json (Gmail ledger), ../interviewing.json,
NEVER_APPLY in ../tools/apply.py, and queued.json here (rows listed in the files or bot queues)."""
import json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
JS = os.path.dirname(HERE)
CAP = 3
QUEUED = os.path.join(HERE, "queued.json")
NO_LIMIT = {"nvidia", "openai", "anthropic", "xai", "meta"}   # applicant 2026-11-22: frontier labs / NVIDIA have no cap (frontier labs: finance roles only)

_SUFFIX = re.compile(r"\b(incorporated|inc|llc|corporation|corp|ltd|limited|technologies|technology|labs|hq|group|holdings|co|company|ai|io|com)\b")
def norm(s): return re.sub(r"[^a-z0-9]", "", (s or "").lower())
def key(s): return norm(_SUFFIX.sub(" ", (s or "").lower())) or norm(s)

def _load_ledger():
    d = json.load(open(os.path.join(JS, "applied_gmail.json")))["companies"]
    idx, rej = {}, set()
    for k, v in d.items():
        names = {k, v.get("name") or "", v.get("company") or ""} | set(v.get("aliases") or [])
        rejected = bool(v.get("rejected")) or "rejected" in str(v.get("status") or "").lower()
        for n in names:
            for f in (norm, key):
                if f(n):
                    idx.setdefault(f(n), []).append(v)
                    if rejected: rej.add(f(n))
    return idx, rej
LEDGER, REJECTED = _load_ledger()

def _load_iv():
    try: d = json.load(open(os.path.join(JS, "interviewing.json")))
    except Exception: return set()
    return {f(n) for e in d.get("companies", []) for n in [e.get("company")] + list(e.get("aliases") or []) for f in (norm, key) if n and f(n)}
INTERVIEWING = _load_iv()

def _never():
    src = open(os.path.join(JS, "tools", "apply.py")).read()
    m = re.search(r'^NEVER_APPLY=re\.compile\((r"(?:[^"\\]|\\.)*")', src, re.M)   # the line ends with a comment, so match only the literal
    if not m: raise SystemExit("gates: NEVER_APPLY not found in tools/apply.py")
    import ast
    return re.compile(ast.literal_eval(m.group(1)), re.I)
NEVER = _never()
EXTRA_NEVER = re.compile(r"global settlement|morgan stanley|apaca", re.I)   # applicant 2026-11-25

ROWS = os.path.join(HERE, "rows.json")
def queued():
    """Rows listed or waiting: queued.json plus the file rows in rows.json (rows.py), one entry per company + title."""
    q = []
    for f in (QUEUED, ROWS):
        try: q += json.load(open(f))
        except Exception: pass
    seen, out = set(), []
    for x in q:
        k = (key(x.get("company")), (x.get("title") or "").strip().lower())
        if k not in seen: seen.add(k); out.append(x)
    return out

def add_queued(company, title, url, note=""):
    q = queued(); q.append({"company": company, "title": title, "url": url, "note": note}); json.dump(q, open(QUEUED, "w"), indent=0)

LEVELS = [("exec", r"\b(chief|cto|cio|cdo|caio|vp|svp|evp|vice president|head of|president)\b"),
          ("director", r"\b(director|sr\.? director|senior director)\b"),
          ("manager", r"\b(manager|management|engineering lead|team lead|tech lead manager)\b"),
          ("staff", r"\b(staff|principal|distinguished|fellow|architect)\b"),
          ("senior", r"\b(senior|sr\.?|lead)\b")]
def level(title):
    t = (title or "").lower()
    for name, rx in LEVELS:
        if re.search(rx, t): return name
    return "other"

def _words(t): return set(re.findall(r"[a-z0-9]+", (t or "").lower())) - {"the", "of", "and", "for", "a", "an", "to", "in", "remote", "us", "usa", "-"}
def same_role(a, b):
    wa, wb = _words(a), _words(b)
    return bool(wa and wb) and (wa == wb or len(wa & wb) / max(1, len(wa | wb)) >= 0.8)

def prior(company):
    hits = []
    for f in (norm, key):
        hits += LEDGER.get(f(company), [])
    roles = [r for v in hits for r in (v.get("roles") or [])]
    return {"entries": len(hits), "roles": roles, "count": max([v.get("count") or 0 for v in hits] or [0])}

def allow(company, title, url="", extra=()):
    """extra: rows the calling sweep already kept in this run (dicts with company / title), counted like queued rows."""
    k1, k2 = norm(company), key(company)
    blob = " ".join([company or "", title or "", url or ""])
    if NEVER.search(blob) or EXTRA_NEVER.search(blob): return False, "never-apply list"
    if k1 in INTERVIEWING or k2 in INTERVIEWING: return False, "interviewing with the applicant"
    nolimit = k2 in NO_LIMIT or k1 in NO_LIMIT   # applicant 2026-11-22: lift limits for NVIDIA / frontier labs (a rejection of one role does not block the others)
    if not nolimit and (k1 in REJECTED or k2 in REJECTED): return False, "rejected the applicant before"
    p = prior(company)
    if any(same_role(title, r) for r in p["roles"]): return False, "same role already applied"
    q = [x for x in list(queued()) + list(extra) if key(x.get("company")) == k2 or norm(x.get("company")) == k1]
    q = [x for x in q if not any(same_role(x.get("title"), r) for r in p["roles"])]   # a listed role the applicant has since applied to counts once
    if any(same_role(title, x.get("title")) for x in q): return False, "same role already queued / listed"
    if nolimit: return True, f"ok (no-limit company, {len(p['roles'])} prior)"
    used = [level(r) for r in p["roles"]] + [level(x.get("title")) for x in q]
    if len(set(p["roles"])) + len(q) >= CAP: return False, "company cap (3 roles, applied + queued)"
    if level(title) in used and level(title) != "other": return False, f"level bucket '{level(title)}' already used at this company"
    return True, f"ok ({len(p['roles'])} prior)"

if __name__ == "__main__":
    import sys
    for a in sys.argv[1:]:
        co, _, ti = a.partition("|")
        ok, why = allow(co, ti)
        print(("OK  " if ok else "DROP"), co, "|", ti, "|", why)
