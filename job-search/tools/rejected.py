"""Companies that rejected the applicant: never apply to them again (applicant 2026-10-02 / 2026-10-05:
"DO NOT APPLY TO COMPANIES THAT HAS REJECTED me"). The list is private: JOBS_DIR/rejected.json (outside the
repo), a JSON list of normalized company keys and ATS board tokens, e.g. ["braze", "datadog", "hubspot"]."""
import json, os, re

_N = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
_SUFFIX = ("incorporated", "inc", "llc", "corporation", "corp", "ltd", "limited", "technologies", "technology", "labs", "hq", "group", "holdings", "co")


def load(jobs_dir):
    try:
        return {_N(x) for x in json.load(open(os.path.join(jobs_dir, "rejected.json"))) if _N(x)}
    except Exception:
        return set()


def board(url):
    """The ATS board / tenant token of a posting URL (Greenhouse, Lever, Ashby, Workday), or ""."""
    u = (url or "").lower()
    m = re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([a-z0-9_-]+)|jobs\.lever\.co/([a-z0-9_-]+)|jobs\.ashbyhq\.com/([a-z0-9_.-]+)|//([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com", u)
    return _N(next((g for g in m.groups() if g), "")) if m else ""


def hit(rej, company, url=""):
    """The rejected-list key this company / posting matches, or "" (exact keys only: 'Step' never matches 'StepStone')."""
    if not rej:
        return ""
    k = _N(company)
    if k in rej:
        return k
    for s in _SUFFIX:
        if k.endswith(s) and k[: -len(s)] in rej:
            return k[: -len(s)]
    b = board(url)
    return b if b and b in rej else ""
