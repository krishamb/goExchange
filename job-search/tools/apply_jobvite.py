"""Jobvite career-site application filler: jobs.jobvite.com/<slug>/job/<id> (also careers.jobvite.com), guest apply.

usage: apply_jobvite.py <queue.json> [--submit] [--headed] [--pace MIN MAX] [--locations]
  queue items: {"ats","url","tag","company","title","loc","where","jd","resume"}   (resume: exec | main | blockchain)
  optional per item: "answers": {"<label substring>": "<answer>" | [...]} - the applicant's own answers to questions the
  rules leave open (reported as unanswered by a dry run); they win over the rules. "cover_letter": true attaches the
  applicant's cover letter PDF as an additional file.
  --locations: print the location-gate verdict of every queue item (one JSON line each) and exit; no browser is opened.
env: JV_JOB_TIMEOUT (s, default 900), JV_DUMP=1 (save each step's screenshot + HTML in out/), JOBS_DIR, ME_JSON.

Flow: the job page (/job/<id>?nl=1; nl=1 keeps the tenant's redirect to its own careers site off) is read first for the
location gate, then /job/<id>/apply?nl=1. Every tenant starts with a Data Consent step ("Location of Residence and
Language" + I Accept / I Decline): the filler picks United States / English (else the option that covers the US, e.g.
"All Countries" / "Global") and accepts; the applicant consents to data processing and AI screening. No account, login
or e-mail code is involved. The form is an Angular wizard of up to four steps (main -> EEO -> OFCCP self-ID ->
pre-screen questions) joined by Next. The resume is uploaded as a file (pasted as text when the upload fails), and
every field is answered from apply.py's reviewed rule tables (TEXT_RULES / CHOICE_RULES / tech_answer). A dry run
(default) stops on the last step before "Send Application", writes out/<tag>_jobvite_dry.png and
out/<tag>_jobvite_report.json, and lists what is missing, including required questions on later steps it could not
reach. In a dry run any request to /submitApplication is also blocked at the network level.

With --submit it clicks "Send Application". Most tenants run Google reCAPTCHA v2 *invisible* on that click (it runs
silently, like the Greenhouse bot's); a visible challenge (image grid, checkbox, hCaptcha, Turnstile, DataDome) is never
touched: the item is reported as "NOT SUBMITTED: captcha". "submitted": true only after the site's own confirmation.
A required question with no rule is never guessed; AI-use / "I personally completed this application" certifications
and human-verification questions ("which of these is a real color") are never answered (left for the applicant and
reported). Source questions: LinkedIn when offered, else a job-board / internet option, never a referral, recruiter,
employee or event. Contact details come from /root/jobs-private/me.json (email, phone) and JOBS_DIR/profile.json at run
time only.

Location rule (applicant, 2026-10-08): remote roles in the USA; SF Bay Area roles in any work mode but never 5 days a
week in the office; New York City hybrid; Los Angeles hybrid. Hybrid anywhere else, and on-site outside the Bay Area,
are reported as "NOT SUBMITTED: location (...)" before any page is opened.

Output: one JSON line per item on stdout {"tag","ats","url","submitted","result","unanswered","errors"}; every other
log line goes to stderr."""
import asyncio, json, os, re, sys, time, random, datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from playwright.async_api import async_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.expanduser(os.environ.get("JOBS_DIR", "/tmp/claude-0/-home-user-goExchange/8d20ffb7-2488-5f8f-a666-35334b9e3ba6/scratchpad/f"))
OUT = os.path.join(JOBS_DIR, "out"); os.makedirs(OUT, exist_ok=True)
ME_FILE = os.environ.get("ME_JSON", "/root/jobs-private/me.json")
P = json.load(open(os.path.join(JOBS_DIR, "profile.json")))
for _k in ("resume", "cover_letter"):
    if P.get(_k): P[_k] = os.path.expanduser(P[_k])
try:   # contact details: the private me.json wins over profile.json
    _me = json.load(open(ME_FILE))
    for _k in ("email", "phone"):
        if _me.get(_k): P[_k] = _me[_k]
except Exception:
    pass
ANS = json.load(open(os.path.join(JOBS_DIR, "answers.json"))) if os.path.exists(os.path.join(JOBS_DIR, "answers.json")) else {}
SUBMIT = "--submit" in sys.argv
HEADED = "--headed" in sys.argv
PACE = (float(sys.argv[sys.argv.index("--pace") + 1]), float(sys.argv[sys.argv.index("--pace") + 2])) if "--pace" in sys.argv else (20, 60)
JOB_TIMEOUT = int(os.environ.get("JV_JOB_TIMEOUT", "900"))
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
ATS = "jobvite"
TZ = ZoneInfo("America/Los_Angeles")   # the browser context's time zone (today's-date fields)

# ---- the shared answer rules, taken from apply.py's source (apply.py runs its CLI at import time, so it is not imported)
_src = open(os.path.join(HERE, "apply.py")).read()
def _seg(a, b):
    i = _src.index(a); return _src[i:_src.index(b, i)]
G = {"re": re, "json": json, "os": os, "time": time, "datetime": datetime, "date": datetime.date, "P": P, "ANS": ANS}
exec(_src[_src.index("first,last="):_src.index("\n", _src.index("first,last="))], G)
exec(_seg("TEXT_RULES=[", "\ndef pick("), G)          # TEXT_RULES, CHOICE_RULES and tech_answer()
exec(_seg("def pick(", "\nLABEL_JS"), G)
exec(_seg("EDU_START=", "\nasync def is_edu_date"), G)
exec(_seg("def _match(", "\nasync def open_menu"), G)
exec(_seg("HEAR_Q=", "\nasync def choose_react_select"), G)
exec(_seg("NEVER_APPLY=", "\n"), G)
exec(_seg("NJ_LOC=", "\n    return None\n") + "\n    return None\n", G)   # applicant: no NJ hybrid/on-site roles, no investment-bank roles on site in New York
TEXT_RULES, CHOICE_RULES, pick, best_index, _match, mask_hear, NEVER_APPLY, tech_answer, location_block = (G[k] for k in ("TEXT_RULES", "CHOICE_RULES", "pick", "best_index", "_match", "mask_hear", "NEVER_APPLY", "tech_answer", "location_block"))
HEAR_Q, HEAR_BAD = G["HEAR_Q"], G["HEAR_BAD"]
FIRST, LAST = G["first"], G["last"]
_sal = pick("salary expectations", TEXT_RULES) or ""
_m = re.search(r"\d[\d,]{4,}", _sal)
SALARY_NUM = _m.group(0).replace(",", "") if _m else None

# 'have you applied to us before?': answered from the applicant's own submitted applications to the company, as apply.py
# does (its prior_company_apps and the run_one patterns); when apply.py's layout no longer allows this, the generic rule answers
try:
    G.update({"OUT": OUT, "JOBS_DIR": JOBS_DIR, "HERE_REPO": os.path.dirname(os.path.dirname(HERE))})
    exec(_seg("GENERIC_TOKENS=", "\n# companies the applicant never wants"), G)
    exec(_seg("BOARD_ALIAS=", "\ndef applied_elsewhere"), G)
    exec(_seg("APPLIED_BY_APPLICANT=", "\n"), G)
    exec(_seg("def prior_company_apps(", "\nasync def run("), G)
    PRIOR_Q = re.search(r'\n\s*_PAT=r"(.+?)"\n', _src).group(1) + r"|have you (ever |previously )?applied\b.{0,60}\b(before|previously|in the past)"
    PRIOR_FOLLOWUP = re.search(r'JOB_TEXT_RULES=\[\(r"(.+?)", \("Yes: "', _src).group(1)
    re.compile(PRIOR_Q); re.compile(PRIOR_FOLLOWUP)
    prior_company_apps = G["prior_company_apps"]
except Exception as _e:
    prior_company_apps = PRIOR_Q = PRIOR_FOLLOWUP = None
    print(f"[jv] note: apply.py's prior-application helper could not be loaded ({type(_e).__name__}); 'applied before' uses the generic rule", file=sys.stderr)

# ---- Jobvite questions the shared tables phrase differently. Each line restates an applicant answer that apply.py already
# records (cited), so nothing new is decided here; they apply only when the shared tables have no rule for the label.
JV_CHOICE_RULES = [
    # apply.py CHOICE_RULES "(uses|use) text messag|text messag.{0,80}(interview|application|hiring|recruit)|consent to (receive )?(sms|text)"
    # -> Yes (applicant: consent -> yes): texts about this application / position
    (r"(contact|reach|text|message) you (via |by )?(text|sms)\b.{0,40}(position|application|role|job|interview)|\btext you about (your|this|the) (application|position|role|candidacy)|via text about (this|the|your) (position|role|job|application)", ["Yes", "yes"]),
    # apply.py CHOICE_RULES "would you be interested in hearing about contract roles" -> No (applicant: full-time only)
    (r"full[- ]time or part[- ]time|part[- ]time or full[- ]time|(desired|preferred) (employment|job|work) (type|status)", ["Full-Time", "Full-time", "Full time", "Full Time"]),
]

RESUME_VARIANTS = {"exec": "Ambarish_Krishnamurthy_Executive_Resume.pdf", "main": "Ambarish_Krishnamurthy_Resume.pdf", "blockchain": "Ambarish_Krishnamurthy_Blockchain_AI_Resume.pdf"}
EXEC_RESUME = os.path.join(JOBS_DIR, RESUME_VARIANTS["exec"])
def resume_for(item):
    v = RESUME_VARIANTS.get(str(item.get("resume") or ""))
    if v and os.path.exists(os.path.join(JOBS_DIR, v)): return os.path.join(JOBS_DIR, v)
    title = item.get("title") or ""
    if os.path.exists(EXEC_RESUME) and re.search(r"\b(CTO|Chief|VP|SVP|Vice President|Head of|Director|Manager)\b", title, re.I) and not re.search(r"Architect", title, re.I):
        return EXEC_RESUME
    return P["resume"]
_RESUME_TEXT = {}
def resume_text(path):
    """Plain text of a resume PDF (for the paste fallback and for 'is a GitHub link in your resume?'); '' if unreadable."""
    if path not in _RESUME_TEXT:
        try:
            from pdfminer.high_level import extract_text
            _RESUME_TEXT[path] = re.sub(r"\n{3,}", "\n\n", extract_text(path)).strip()
        except Exception:
            _RESUME_TEXT[path] = ""
    return _RESUME_TEXT[path]

# ---- guards (never answered by the filler; the applicant answers these) - the reviewed set from apply_oraclecloud.py
AI_CERT = re.compile(r"personally (completed|filled|prepared|written|wrote|answered)|(completed|filled( out)?|written|prepared) (this|the|my) (application|form) (myself|personally|on my own|without)|"
                     r"no (ai|artificial intelligence)\b|without (the )?(use of |help of |assistance of )?(any )?(ai|artificial intelligence|generative)|(ai|artificial intelligence) (was|were|has been|have been) (not )?used|"
                     r"(did|have) (not |n.t )?use[d]? (any )?(ai|artificial intelligence|chatgpt|generative)|are you an ai\b|ai agent (is|was) (applying|completing)|ai policy|ai assistance|"
                     r"(certify|attest|confirm) .{0,60}(own words|not (been )?(generated|written)|myself)", re.I)
AI_CERT_STRONG = re.compile(r"personally (completed|filled|prepared|written|wrote|answered)|(completed|filled( out)?|written|prepared) (this|the|my) (application|form) (myself|personally|on my own|without)|"
                            r"no (ai|artificial intelligence)\b|without (the )?(use of |help of |assistance of )?(any )?(ai|artificial intelligence|generative)|(did|have) (not |n.t )?use[d]? (any )?(ai|artificial intelligence|chatgpt|generative)|"
                            r"(answers|responses|application|statements|work|writing) (provided |given |submitted )?(here(in)? )?(are|is|were|was) (entirely |all |wholly |solely )?my own|(certify|attest|confirm) .{0,60}(own words|my own|not (been )?(generated|written)|myself)", re.I)
AI_CONSENT = re.compile(r"transcri|note-?tak|record(ing)? (of )?(your|the|my) interview|interview (notes|recordings?)|(ai|artificial intelligence) (to|in) (screen|review|evaluat|assess|match)", re.I)
# a human-verification question inside the form ('To confirm you are a human, which of the following is a real color'): it is
# a human check, so the filler never answers it, not even from an "answers" override; the applicant answers it by hand
HUMAN_Q = re.compile(r"confirm (that )?you('re| are) (a )?(human|real person|not a (robot|bot))|are you (a )?(human|robot|bot)\b|not a robot|prove (that )?you('re| are) (a )?(human|real)|human verification|"
                     r"anti-?(spam|bot) (question|check)|which of the following is (a |an )?(real |actual )?(color|colour|animal|fruit|vegetable|number|day|month|shape)|type the (word|letters|characters)|what is \d+\s*(\+|plus|x|times|-|minus)\s*\d+", re.I)
VISA_STATUS_Q = re.compile(r"\b(based on|because of|by virtue of|derived from|depend\w* on|through|status as)\b.{0,60}\b(spouse|dependent|h-?1b|h-?4|l-?1|l-?2|f-?1|j-?1|opt|cpt|ead|tn|visa|asylum|refugee|daca|tps)\b", re.I)
COMMUTE_Q = re.compile(r"^(?!.*\b(willing to relocate|or relocate|able to relocate)\b).*\b(live|living|reside|residing|located|based)\b.{0,30}\b(within|in|near)\b.{0,50}\b(commut\w*|the office|office location|this location|job location|(the|our|designated|nearest)\b.{0,30}\b(office|hub|site|location))", re.I)
# 'can you work on site 5 days a week?': the applicant's location rule (2026-10-08) is never 5 days a week in an office, so a
# rule that says Yes is a conflict here (left for the applicant), in the Bay Area too
FIVE_DAYS_Q = re.compile(r"(5|five) days? (per|a|each|every) week|5 days/week|(5|five)[- ]days?[- ](on-?site|in[- ]office|in[- ]person|in the office)|\b5x\b|fully on-?site|100% (on-?site|in[- ]office)", re.I)
DISC = re.compile(r"non-?compete|non-?solicit|financial interest|conflict of interest|relatives?\b|family member|government official|convicted|felony|yes, i (have|had) (a |an )?(disabilit|relative|conflict|criminal|conviction)|^\s*i have a disability", re.I)
ACK = re.compile(r"i (have read|acknowledge|agree|understand|consent|certify|confirm|accept)|terms and conditions|privacy (notice|policy|statement)|^accept\*?$|by (selecting|checking|clicking)", re.I)
# the current employer's business with the hiring company (reseller / customer / partner / its staff on site): facts the
# applicant knows and the rules do not. Jobvite: 'Do you currently work with a Blackboard client or channel partner?'
EMPLOYER_REL = re.compile(r"(current|previous|past|your) employer.{0,90}\b(a |an )?(reseller|partner|customer|client|vendor|supplier|distributor|competitor|relationship|business with)\b|\b(reseller|distributor|supplier|vendor) of\b|personnel .{0,90}(on ?site|at your employer|your employer)|interact with .{0,80}personnel|provides? (services|products) to your employer|"
                          r"\bwork(s|ing)? with (a |an |any |one of )?.{0,40}\b(clients?|customers?|channel partners?|partners?|resellers?|vendors?|suppliers?)\b", re.I)
CONSENT_Q = re.compile(r"\b(consent|permission|i agree|agree to|acknowledge|i understand)\b|grant(ing)? .{0,40}permission|"
                       r"(keep|retain|store|hold) (on to )?your (application|information|data|resume|profile|details)|reach out (to you )?(about|if|when|for) .{0,40}(roles?|positions?|opportunit)|"
                       r"considered for other (roles|positions|opportunities|openings|jobs)", re.I)
ACK_OPT = re.compile(r"^\s*(yes,? )?i (hereby )?(understand|acknowledge|agree|consent|accept)|^\s*(i agree|agree|accept|acknowledged?)\.?\s*$", re.I)
ACK_TOPIC = re.compile(r"record|interview|video|audio|photograph|screenshot|consent|acknowledg|privacy|policy|terms|notice|understand|agree|permission|disclos", re.I)
ACK_ASK = re.compile(r"please acknowledge|acknowledge (this|the|that|receipt)|confirm (your )?(understanding|acknowledg|acceptance)|indicate (your )?(acknowledg|acceptance|understanding)", re.I)
OTHER_PERSON_Q = re.compile(r"\b(parent|caregiver|guardian|mother|father|spouse|partner)s?\b.{0,40}\b(education|degree|school|occupation|employ|status|served|veteran|military)|\b(education|degree)\b.{0,30}\b(of|for) (your )?(parent|caregiver|guardian|mother|father)", re.I)
SALARY_SHARE = re.compile(r"(would you like|do you want|are you willing|willing) to (share|provide|disclose) (your )?(salary|compensation|pay)", re.I)
MARKETING = re.compile(r"marketing|newsletter|job alerts?|updates about new job|new job opportunities|talent community|text messages?|\bsms\b|whatsapp|news and events|promotional|linkedin recruiter|"
                       r"\b(receive|get|send me|sign me up|sign up for|subscribe( to)?)\b.{0,40}\b(career|careers|recruiting|e-?mails?|news|updates|communications?|messages|alerts|events|offers|promotions?)\b", re.I)
VET_Q = re.compile(r"veteran|military", re.I)
VET_BAD = re.compile(r"^\s*(i am a |i identify as (a|one)|yes\b|protected veteran$)|^\s*(disabled|recently separated|active duty|armed forces|special disabled|vietnam era|newly separated|other protected|veteran$|veteran other)", re.I)
DIS_Q = re.compile(r"disabilit", re.I)
DIS_BAD = re.compile(r"^\s*yes\b|^\s*i have a disability", re.I)
RACE_Q = re.compile(r"\brace\b|races|racial|ethnic", re.I)
NEG_OPT = re.compile(r"^\s*no\b|\bnot\b|\bnever\b|\bdon'?t\b|\bdo not\b|\bhave not\b|\bhaven'?t\b|\bnone\b", re.I)
DECLINE_OPT = re.compile(r"wish|decline|prefer not|not to (say|answer|disclose|identify)|choose not|self[- ]identif", re.I)
# a label that says nothing on its own ('Choose One' under 'Pre-Employment request for Veteran Classification'): the
# section heading above it is the question
GENERIC_LABEL = re.compile(r"(please )?(choose|select)( one| an option| all that apply)?:?|answer|response|your (answer|response)|options?|yes/no", re.I)
ACK_LABEL = re.compile(r"acknowledg|agree|certif|attest|accept|confirm|understand", re.I)
# the generic 'previously worked / currently work for <company>' rule also matches 'experience in your current or former jobs ...'
# and 'currently work with a <company> client': there it answers a different question, so it is not used
EMPLOY_RULE = re.compile(r"previously,\? \(applied\|worked\|employed\)|\(ever\|currently\|previously\) \(work\|employ")
EMPLOY_MISFIRE = re.compile(r"\bexperience\b|\bwork(s|ing)? with\b|\bclients?\b|\bcustomers?\b|channel partner", re.I)
# the source question: LinkedIn when offered, else a job board / internet option (never a referral, recruiter, employee, event)
SOURCE_Q = re.compile(r"hear about|learn about|find out about|how did you (first |initially )?(hear|learn|find)|\bsource\b|where did you (see|find|hear)", re.I)
INTERNET_OPT = re.compile(r"job ?boards?|job (site|website|search|posting)s?|online|internet|web ?site|search engine|google|career ?(site|page|website)|company (web ?site|careers?)", re.I)
NOTICE_Q = re.compile(r"notice period|how (soon|quickly) can you start|available to start|availability to start|start date|before being able to start|when (can|could) you (start|begin|join)", re.I)
START_DATE_Q = re.compile(r"(desired|preferred|earliest|available|availability|possible) (start|starting) date|earliest date .{0,40}\bstart|start date|date (you are|you're) available|date available|available to start|earliest availability|availability to (start|begin|join)|when (can|could) you (start|begin|join)", re.I)
TODAY_Q = re.compile(r"today'?s? date|signature date|date signed|^date\*?$|^signed on|date of signature|current date", re.I)
RESIDE_IF_Q = re.compile(r"^\s*if you (currently )?(live|reside|are located|are based) in (?!.*\b(california|ca|santa clara|san jose|bay area|silicon valley|united states|the us|usa)\b)", re.I)
NA_OPT = re.compile(r"^\s*n/?a\b|not applicable|(do not|don.t) (live|reside)|does not apply|not in (that|this) (state|city)", re.I)
GITHUB_Q = re.compile(r"(link|url).{0,40}(portfolio|github).{0,60}(resume|cv)|(portfolio|github).{0,60}(included|listed|in|on) (in |on )?your (resume|cv)", re.I)
IF_FOLLOWUP = re.compile(r"^\s*(if (yes|so|applicable|other|you were referred|referred|you answered|you selected)|please (list|provide|explain|specify).{0,30}(if|referr))|who (can we thank|referred you)|"
                         r"^\s*if (your|the|my) .{0,40}(w(as|ere) not|is not|are not|isn.t|aren.t) listed|not listed (above|here)|^\s*if (none|other) of the above|^\s*(please )?specify( other)?:?$", re.I)

def log(tag, msg): print(f"[jv {tag}] {msg}", file=sys.stderr, flush=True)
PRINTED = set()   # tags whose one stdout JSON line has been printed
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
def loose(s):
    s = re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
    s = re.sub(r"^(i am|i m|im|i)\s+", "", s)
    return re.sub(r"\bdeclines\b", "decline", s)

def usable(texts, label):
    # apply.py's source-question mask ('never a referral / recruiter option'); not on a Yes/No list, where it would hide both
    # answers of 'Were you referred ...? No, I was not referred / Yes, I was referred'
    yn = any(re.match(r"\s*(yes|no)\b", t or "", re.I) for t in texts)
    out = list(texts) if yn else mask_hear(texts, label)
    if VET_Q.search(label or ""): out = ["" if VET_BAD.search(t or "") else t for t in out]
    if DIS_Q.search(label or ""): out = ["" if DIS_BAD.search(t or "") else t for t in out]
    return out
def rank(texts, prefs, label):
    """Index of the option matching the earliest preference: exact / leading / whole-word (apply.py's best_index), then a
    loose match ('I am not a protected veteran' = 'I AM NOT A PROTECTED VETERAN'). A positive preference never picks a
    negated option. A plain 'No' with no matching option picks the single negative option."""
    u0 = usable(texts, label)
    for p in prefs or []:
        if not isinstance(p, str) or p == "__ASK__": continue
        u = [t if not (t and NEG_OPT.search(t) and not NEG_OPT.search(p)) else "" for t in u0]
        k = best_index(u, p)
        if k is not None: return k
        lp = loose(p)
        k = next((i for i, t in enumerate(u) if t and lp and (loose(t) == lp or loose(t).startswith(lp + " "))), None)
        if k is not None: return k
    if prefs and isinstance(prefs[0], str) and re.fullmatch(r"\s*no\s*", prefs[0], re.I):
        neg = [i for i, t in enumerate(u0) if t and NEG_OPT.search(t)]
        if len(neg) == 1: return neg[0]
    return None
def rules_value(label, table, q=None):
    """apply.py's pick() (same tables, same order, per-job rules first), except that the generic 'worked for <company>
    before' rule is passed over where it answers a different question ('experience in your current or former jobs
    protecting ...'): the next matching rule answers instead."""
    rules = (G["JOB_CHOICE_RULES"] + CHOICE_RULES) if table == "choice" else (G["JOB_TEXT_RULES"] + TEXT_RULES)
    l = (label or "").lower(); qq = q or label or ""
    for pat, val in rules:
        if re.search(pat, l) or (re.search(r"[A-Z]", pat) and re.search(pat, label)):
            if EMPLOY_RULE.search(pat) and EMPLOY_MISFIRE.search(qq): continue
            return val
    return None
def choice_for(label, q=None):
    v = rules_value(label, "choice", q)
    if v is None:
        v = next((val for pat, val in JV_CHOICE_RULES if re.search(pat, (label or "").lower())), None)
    if v is None: return None
    return v if isinstance(v, list) else [v]
def text_for(label, q=None):
    v = rules_value(label, "text", q)
    return v if isinstance(v, str) and v.strip() else None

def years_index(opts, n):
    """A years-of-experience bucket list ('Less than 3 years', '3 to 5 years', 'More then 7 years'): the bucket holding n."""
    for i, o in enumerate(opts):
        s = (o or "").lower().replace("then", "than")
        m = re.search(r"(\d+)\s*(-|–|to)\s*(\d+)", s)
        if m and int(m.group(1)) <= n <= int(m.group(3)): return i
        if m: continue
        m = re.search(r"(less|fewer) than (\d+)|under (\d+)|up to (\d+)", s)
        if m:
            hi = int(next(g for g in m.groups()[1:] if g))
            if n < hi or (m.group(4) and n == hi): return i
            continue
        m = re.search(r"(more|greater) than (\d+)|over (\d+)", s)
        if m:
            if n > int(next(g for g in m.groups()[1:] if g)): return i
            continue
        m = re.search(r"(\d+)\s*(\+|or more|or greater|years? or more|years?\+)|at least (\d+)", s)
        if m and n >= int(m.group(1) or m.group(4)): return i
    return None

# ---- the location gate
REMOTE_RE = re.compile(r"\bremote\b|work from home|\bwfh\b|home[- ]based|anywhere in the (us|u\.s\.|usa|united states)", re.I)
HYBRID_RE = re.compile(r"\bhybrid\b", re.I)
ONSITE_RE = re.compile(r"\bon-?site\b|\bin[- ]office\b|\bin[- ]person\b|office[- ]based", re.I)
BAY_RE = re.compile(r"san francisco|bay area|silicon valley|palo alto|menlo park|mountain view|sunnyvale|san jose|santa clara|redwood city|redwood shores|san mateo|foster city|burlingame|san bruno|millbrae|daly city|san carlos|"
                    r"belmont,? (ca|california)|cupertino|milpitas|los altos|los gatos|campbell,? (ca|california)|saratoga,? (ca|california)|oakland|emeryville|berkeley(?! heights)|alameda|san leandro|hayward|fremont,? (ca|california)|"
                    r"newark,? (ca|california)|union city,? (ca|california)|pleasanton|dublin,? (ca|california)|livermore|san ramon|walnut creek|concord,? (ca|california)|east palo alto|half moon bay|sausalito|san rafael|mill valley|novato|richmond,? (ca|california)|brisbane,? (ca|california)", re.I)
NYC_RE = re.compile(r"new york,? (new york|ny)\b|new york city|\bnyc\b|manhattan(?! beach)|brooklyn|queens|long island city|\bbronx\b|staten island|^\s*new york\s*(,\s*(us|usa|united states))?\s*$", re.I)
LA_RE = re.compile(r"los angeles|\bL\.?A\.?,? (ca|california)\b|santa monica|culver city|playa vista|marina del rey|venice,? (ca|california)|el segundo|burbank|pasadena,? (ca|california)|glendale,? (ca|california)|beverly hills|west hollywood|"
                   r"hollywood,? (ca|california)|century city|long beach,? (ca|california)|torrance|manhattan beach|hawthorne,? (ca|california)|inglewood|studio city|sherman oaks|woodland hills|calabasas", re.I)
NON_US_RE = re.compile(r"canada|toronto|vancouver|montreal|united kingdom|\buk\b|england|london|ireland|dublin(?!,? (ca|california|oh|ohio))|germany|berlin|munich|france|paris|spain|madrid|barcelona|portugal|lisbon|netherlands|amsterdam|poland|"
                       r"india|bangalore|bengaluru|hyderabad|pune|chennai|mumbai|noida|gurgaon|singapore|australia|sydney|melbourne|japan|tokyo|mexico|brazil|argentina|colombia|costa rica|philippines|israel|tel aviv|emea|apac|latam|europe|"
                       r"romania|ukraine|serbia|belgrade|czech|hungary|sweden|denmark|norway|finland|switzerland|austria|italy|greece|turkey|dubai|south africa|nigeria|kenya|egypt|china|hong kong|taiwan|korea|vietnam|thailand|malaysia|indonesia|new zealand", re.I)
US_STATES = ["Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland",
             "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
             "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming", "District of Columbia"]
US_RE = re.compile(r"united states|\busa\b|\bu\.s\.(a\.)?|\bus\b|nationwide|north america|" + "|".join(re.escape(s) for s in US_STATES), re.I)
_NEGATED = re.compile(r"\b(not|no|never|don'?t|doesn'?t|isn'?t|aren'?t|won'?t|without|nor)\b[^.;]{0,40}$", re.I)
FIVE_DAY_RE = re.compile(r"(5|five) days? (a|per|each|every) week.{0,40}(office|on-?site|in[- ]person)|(office|on-?site|in[- ]person).{0,40}(5|five) days? (a|per|each|every) week|"
                         r"(in the office|on-?site|in[- ]office|in[- ]person) full[- ]time|full[- ]time (in the office|on-?site|in[- ]office|in[- ]person)|fully (on-?site|in[- ]office|in[- ]person)|100% (on-?site|in[- ]office|in[- ]person|in the office)|"
                         r"(monday|mon) (through|to|-|–) (friday|fri) (in|at|from) (the|our) office|(5|five)[- ]day (in[- ]office|on-?site|return[- ]to[- ]office|rto|office)", re.I)
def five_days(text):
    """A posting that asks for 5 days a week in the office ('expected to work in the office full-time'), not negated."""
    for m in FIVE_DAY_RE.finditer(text or ""):
        if not _NEGATED.search(text[max(0, m.start() - 60):m.start()]): return m.group(0)
    return None

def location_gate(item, desc=""):
    """(verdict, reason): verdict 'ok', 'out' or 'unknown' (the work mode is not stated; read the posting and decide again).
    The rule (applicant, 2026-10-08): remote roles in the USA; SF Bay Area roles in any work mode, never 5 days a week in the
    office; New York City hybrid; Los Angeles hybrid. Hybrid anywhere else, and on-site outside the Bay Area, are out."""
    loc, where, title = str(item.get("loc") or ""), str(item.get("where") or "").lower(), str(item.get("title") or "")
    jd = " ".join(x for x in (str(item.get("jd") or ""), desc or "") if x)
    head = f"{loc} | {title}"
    hybrid = bool(HYBRID_RE.search(head) or "hybrid" in where)
    remote = where.startswith("remote") or (bool(REMOTE_RE.search(head)) and not hybrid)
    if remote:
        if NON_US_RE.search(loc) and not US_RE.search(loc) and not BAY_RE.search(loc):
            return "out", "remote, but outside the USA"
        states = {s for s in US_STATES if re.search(r"\b" + re.escape(s) + r"\b", loc)}
        if len(states) >= 3 and "California" not in states and not re.search(r"\bCA\b", loc):
            return "out", "remote, but only for residents of states that do not include California"
        return "ok", "remote (USA)"
    five = five_days(jd + " " + loc)
    jd_hybrid = bool(HYBRID_RE.search(jd))
    onsite = bool(ONSITE_RE.search(head) or "onsite" in where or "on-site" in where)
    if BAY_RE.search(loc) or where.startswith("bay"):
        if five: return "out", f"SF Bay Area role, but 5 days a week in the office ({five!r})"
        return "ok", "SF Bay Area" + (" (on-site: check the days in the office)" if onsite and not hybrid else "")
    place = "NYC" if (NYC_RE.search(loc) or (not loc.strip() and where in ("nyc", "ny-hybrid"))) else "Los Angeles" if (LA_RE.search(loc) or where.startswith("la-")) else None
    if place:
        if five: return "out", f"{place} role with 5 days a week in the office (only {place} hybrid is allowed)"
        if hybrid or (jd_hybrid and not onsite): return "ok", f"{place} hybrid"
        if onsite: return "out", f"{place} on-site (only {place} hybrid is allowed)"
        return "unknown", f"{place} role, work mode not stated (only {place} hybrid is allowed)"
    if hybrid or (jd_hybrid and not onsite and not REMOTE_RE.search(jd)): return "out", f"hybrid outside the SF Bay Area, NYC and Los Angeles ({loc.strip()[:60] or where})"
    if onsite: return "out", f"on-site outside the SF Bay Area ({loc.strip()[:60] or where})"
    if not loc.strip() and not where: return "unknown", "no location given"
    return "out", f"not remote and not in the SF Bay Area, NYC or Los Angeles ({loc.strip()[:60] or where})"

# ---- page helpers
CHALLENGE_JS = r"""()=>{
 // a CAPTCHA the person would have to solve. reCAPTCHA v2 *invisible* keeps a badge iframe (anchor, size=invisible) and a
 // hidden challenge frame (bframe, visibility:hidden, top:-10000px) on the page: neither is a challenge until the bframe shows
 const shown=(el)=>{const r=el.getBoundingClientRect(); if(r.width<40||r.height<40) return false;
   for(let e=el;e&&e.nodeType===1;e=e.parentElement){const cs=getComputedStyle(e); if(cs.display==='none'||cs.visibility==='hidden'||parseFloat(cs.opacity)<0.05) return false;}
   return r.bottom>0&&r.right>0&&r.top>-500&&r.left<innerWidth+50;};
 const hits=[];
 for(const f of document.querySelectorAll('iframe')){
   const s=(f.getAttribute('src')||'')+' '+(f.title||'');
   if(/recaptcha\/(api2|enterprise)\/bframe|recaptcha challenge/i.test(s)){ if(shown(f)) hits.push('reCAPTCHA challenge'); continue; }
   if(/recaptcha\/(api2|enterprise)\/anchor/i.test(s)){ if(!/size=invisible/.test(s)&&!f.closest('.grecaptcha-badge')&&shown(f)) hits.push('reCAPTCHA checkbox'); continue; }
   if(/hcaptcha\.com|challenges\.cloudflare\.com|turnstile|captcha-delivery\.com|geo\.captcha|arkoselabs|funcaptcha|px-captcha|perimeterx/i.test(s)&&shown(f)) hits.push(s.slice(0,90));
 }
 for(const sel of ['#px-captcha','.h-captcha','.cf-turnstile','#challenge-form','#cf-challenge-running']){const e=document.querySelector(sel); if(e&&shown(e)) hits.push(sel);}
 return hits;}"""
async def challenge(page):
    try: return await page.evaluate(CHALLENGE_JS)
    except Exception: return []
async def text(page):
    try: return await page.evaluate("()=>document.body.innerText")
    except Exception: return ""
async def dismiss_cookies(page):
    """Cookie banners: strictly necessary cookies only. Never a button inside the application or consent form."""
    try:
        h = await page.evaluate_handle(r"""()=>{const re=/^(decline|decline all|reject|reject all|opt out|necessary only|only necessary.*|accept only necessary.*)$/i;
          return [...document.querySelectorAll('button, [role="button"]')].find(b=>!b.closest('form, .jv-form, .jv-apply-form') && (b.offsetParent||b.getClientRects().length)
            && re.test(((b.innerText||'').trim()||b.getAttribute('aria-label')||'').replace(/\s+/g,' ').trim()))||null}""")
        el = h.as_element()
        if el:
            await el.click(timeout=2500); await page.wait_for_timeout(600); return True
    except Exception: pass
    return False

FIELDS_JS = r"""()=>{
 const vis=e=>!!(e&&(e.offsetParent||e.getClientRects().length));
 const clean=s=>(s||'').replace(/\s+/g,' ').trim();
 const strip=s=>clean(s).replace(/\s*[*✱]+\s*$/,'').trim();
 document.querySelectorAll('[data-jv]').forEach(e=>e.removeAttribute('data-jv'));   // indices from an earlier step are stale
 const root=document.querySelector('form[name="scopeData.applyForm"]')||document.querySelector('.jv-apply-form')||document.body;
 const rows=[...root.querySelectorAll('.jv-form-field')].filter(r=>vis(r));
 const out=[]; let ctx=[], head='', lastStep=null;
 rows.forEach((r,i)=>{
  r.setAttribute('data-jv',String(i));
  const step=r.closest('.jv-apply-step');
  if(step!==lastStep){ctx=[]; head=''; lastStep=step;}
  const sec=r.closest('.jv-prescreen-section'); const secHead=sec?clean((sec.querySelector('.jv-prescreen-section-header')||{}).innerText):'';
  const box=r.querySelector('.jv-form-field-control')||r;
  const sel=box.querySelector('select'), ta=box.querySelector('textarea');
  const radios=[...box.querySelectorAll('input[type=radio]')], cbs=[...box.querySelectorAll('input[type=checkbox]')];
  const inp=box.querySelector('input:not([type=radio]):not([type=checkbox]):not([type=hidden]):not([type=file])');
  const labEl=r.querySelector('label.jv-form-field-label, legend.jv-form-field-legend');
  let label=labEl?strip(labEl.innerText):'';
  let kind='', opts=[], oidx=[], val='', multi=false, itype='';
  const req=!!r.querySelector('.jv-required-label, [aria-required="true"], [required]');
  if(sel){ kind=sel.multiple?'mselect':'select';
    [...sel.options].forEach((o,j)=>{ if(o.value!==''&&!/^\?/.test(o.value)&&!/^select an option/i.test(clean(o.text))){opts.push(clean(o.text)); oidx.push(j);} });
    val=sel.multiple?[...sel.selectedOptions].map(o=>clean(o.text)).join('; '):((sel.selectedIndex>=0&&sel.value!==''&&!/^\?/.test(sel.value))?clean(sel.options[sel.selectedIndex].text):'');
    if(/^select an option/i.test(val)) val=''; }
  else if(radios.length){ kind='radio'; const ls=[...box.querySelectorAll('label.jv-input-group-row')]; opts=(ls.length===radios.length?ls:radios.map(x=>x.closest('label')||x.parentElement)).map(l=>strip(l.innerText));
    val=radios.map((x,j)=>x.checked?opts[j]:null).filter(x=>x).join('; '); }
  else if(cbs.length){ kind='checkbox'; const ls=[...box.querySelectorAll('label.jv-input-group-row')]; opts=(ls.length===cbs.length?ls:cbs.map(x=>x.closest('label')||x.parentElement)).map(l=>strip(l.innerText));
    multi=cbs.length>1; val=cbs.map((x,j)=>x.checked?opts[j]:null).filter(x=>x).join('; '); if(!label&&cbs.length===1) label=opts[0]; }
  else if(ta){ kind='textarea'; val=ta.value; }
  else if(inp){ itype=(inp.getAttribute('type')||'text').toLowerCase(); kind=itype==='date'?'date':(itype==='tel'?'tel':(itype==='number'?'number':'text')); val=inp.value; if(inp.readOnly||inp.disabled) kind='readonly'; }
  else { const h=box.querySelector('h4'), p=box.querySelector('p');
    if(h&&clean(h.innerText)){ head=clean(h.innerText); ctx=[]; out.push({i,kind:'heading',label:head}); return; }
    if(p&&clean(p.innerText)){ const t=strip(p.innerText); if(t&&!/^\*?\s*required$/i.test(clean(p.innerText))) ctx.push(t); out.push({i,kind:'p',label:t.slice(0,300)}); return; }
    out.push({i,kind:'hr',label:''}); return; }
  out.push({i,label,kind,req,opts,oidx,val:clean(val),multi,itype,head:secHead||head,ctx:ctx.join(' ').slice(-1500)});
 });
 return out;}"""
ROW = lambda i: f'[data-jv="{i}"]'
FIELD_KINDS = ("text", "textarea", "select", "mselect", "radio", "checkbox", "date", "tel", "number", "readonly")

class Job:
    def __init__(self, item):
        self.item = item; self.tag = item["tag"]; self.url = item["url"]; self.title = item.get("title", "")
        self.report = {"tag": self.tag, "ats": ATS, "url": self.url, "company": item.get("company", ""), "title": self.title, "submitted": False, "result": "", "unanswered": [], "errors": [], "answers": {}}
        self.why = {}   # label -> why a field is left for the applicant
        self.resume = resume_for(item)
    def ans(self, label, val): self.report["answers"][(label or "")[:140]] = val
    def note(self, key, val):
        lst = self.report.setdefault(key, [])
        if val not in lst: lst.append(val)
    def miss(self, f, why=None, step=None):
        u = {"label": (f.get("label") or f.get("head") or "?")[:300], "type": f.get("kind")}
        if f.get("opts"): u["options"] = f["opts"][:25]
        why = why or self.why.get(u["label"])
        if why: u["why"] = why
        if step: u["step"] = step
        if not any(x["label"] == u["label"] and x.get("step") == u.get("step") for x in self.report["unanswered"]): self.report["unanswered"].append(u)

def contact_value(f):
    """The fixed contact / address / signature fields, by label (None: not one of them)."""
    low = re.sub(r"\s*:\s*$", "", (f["label"] or "").lower().strip())
    if re.search(r"(postal|zip) code extension|zip ?\+ ?4|plus ?4|^\+4$|middle (name|initial)|pronunciation|phonetic|maiden name|former (last )?name|other names?|second last name|previous last name", low): return ""
    if re.fullmatch(r"(chosen |preferred |legal )?(last name|family name|surname)( \(legal\))?", low): return LAST
    if re.fullmatch(r"(chosen |legal )?(first name|given name)( \(legal\))?", low): return FIRST
    if re.fullmatch(r"preferred (first )?name|known as|nickname", low): return text_for(f["label"]) or FIRST
    if re.fullmatch(r"suffix|name suffix|prefix|honorific|apt\.?(, suite.*)?|apartment.*|suite", low): return ""
    if re.search(r"address|street", low) and re.search(r"(line|ln)\.?\s*[2-9]\b|address\s*[2-9]\b|\b(apt|apartment|suite|unit)\b", low): return ""   # line 2: empty
    if re.fullmatch(r"(your )?e-?mail( address)?", low): return P["email"]
    if re.fullmatch(r"(street |home |mailing |current |residential )?address( line)?( ?1)?|street( address)?( line)?( ?1)?|street (number and )?name( or p\.?o\.? box)?", low): return P.get("street") or ""
    if re.fullmatch(r"(zip|postal)( code)?|zip/postal code", low): return P.get("zip") or ""
    if re.fullmatch(r"city|town|city/town", low): return P.get("city") or "Santa Clara"
    if re.fullmatch(r"county", low): return "Santa Clara"
    if re.fullmatch(r"state|state/province|province|region|state of residence", low): return "California"
    if re.fullmatch(r"country|country/region|country of residence", low): return "United States"
    if re.fullmatch(r"full name|legal full name|signature|e-?signature|electronic signature|your (full |legal )?name|name", low): return P["name"]
    if re.fullmatch(r"(applicant'?s? )?initials|your initials|initial here", low): return FIRST[0].upper() + LAST[0].upper()   # apply.py TEXT_RULES 'your initials' -> AK
    if re.search(r"linkedin", low) and not re.search(r"\?|recruiter|status", low): return P["linkedin"]
    if re.fullmatch(r"(personal )?(web ?site|url|portfolio)( url)?", low): return P["linkedin"]
    return None

def today_local():
    return datetime.datetime.now(TZ).date()

def hear_index(opts, label):
    """Source question: an option naming LinkedIn, else the rules' order (job board / online job posting), else a job-board /
    internet option; never a referral, recruiter, employee or event option."""
    ok = [o if (o and not HEAR_BAD.search(o) and not re.search(r"referr|recruit|employee|event|fair|conference|agency|friend|internal|former|hiring manager|contractor", o, re.I)) else "" for o in opts]
    k = next((i for i, o in enumerate(ok) if o and re.search(r"linked\s?in", o, re.I) and not re.search(r"recruiter|inmail", o, re.I)), None)
    if k is not None: return k
    prefs = [p for p in (choice_for("How did you hear about this position?") or []) if isinstance(p, str)]
    head = prefs[:prefs.index("Social Media")] if "Social Media" in prefs else prefs
    k = rank(ok, head, label)
    if k is not None: return k
    k = next((i for i, o in enumerate(ok) if o and re.search(r"job ?boards?", o, re.I)), None)
    if k is None: k = next((i for i, o in enumerate(ok) if o and INTERNET_OPT.search(o)), None)
    if k is not None: return k
    tail = [p for p in (prefs[prefs.index("Social Media"):] if "Social Media" in prefs else []) if re.search(r"social", p, re.I)]   # LinkedIn is social media; never 'Other'
    return rank(ok, tail, label)

def notice_index(opts):
    """'Immediately (within 2 weeks at most)' on a bucket list ('0 - 15 Days', '15 - 30 Days', ...): the bucket that starts at 0
    and covers two weeks."""
    for i, o in enumerate(opts):
        m = re.match(r"\s*(0|zero)\s*(-|–|to)\s*(\d+)\s*(day|week)", o or "", re.I)
        if m:
            days = int(m.group(3)) * (7 if m.group(4).lower().startswith("week") else 1)
            if 14 <= days <= 31: return i
    for i, o in enumerate(opts):
        if re.search(r"^\s*(immediate(ly)?|asap|right away)|less than (2|two) weeks|under (2|two) weeks|within (2|two) weeks|(2|two) weeks or less|^\s*(1|one)\s*(-|–|to)\s*(2|two) weeks", o or "", re.I): return i
    return None

def decide(job, f):
    """What to do with one field, from the rules (no page access; also used for the later-step preview).
    act: text / date / pick (k) / picks (ks) / check / skip (left empty on purpose) / keep (its current value) /
    leave (the applicant's: why) / none (no rule)."""
    label, kind, opts, cur = f.get("label") or "", f["kind"], f.get("opts") or [], f.get("val") or ""
    low = label.lower().strip()
    generic = bool(GENERIC_LABEL.fullmatch(re.sub(r"[:?.]\s*$", "", low))) or not low
    q = ((f.get("head") or "") + " - " + label).strip(" -") if generic and f.get("head") else label
    gtxt = q + ((" " + (f.get("ctx") or "")[-900:]) if (generic or (ACK_LABEL.search(low) and len(low) < 90)) else "")
    if kind == "readonly": return {"act": "keep"} if cur else {"act": "skip"}
    # ---- the applicant's own (never the filler's): human checks, AI-use certifications, the employer's business relations
    if HUMAN_Q.search(q):
        return {"act": "leave", "why": "human-verification question: never answered by the bot (answer it by hand)"}
    if (AI_CERT.search(gtxt) and not AI_CONSENT.search(gtxt)) or AI_CERT_STRONG.search(gtxt):
        return {"act": "leave", "why": "AI-use / 'I completed this application myself' certification: always the applicant's"}
    # ---- a per-item "answers" override from the queue file ({"label substring": answer}): the applicant's own answer
    # (never used for the human checks and AI-use certifications above)
    ov = next((v for k, v in (job.item.get("answers") or {}).items() if k and k.lower() in q.lower()), None)
    if ov is None and EMPLOYER_REL.search(q):
        return {"act": "leave", "why": "about your current work's business with the hiring company: only you know it (an \"answers\" override can give it)"}
    if ov is not None:
        ovl = [ov] if isinstance(ov, str) else [str(x) for x in ov]
        if kind in ("text", "textarea", "tel", "number"): return {"act": "text", "val": ovl[0], "src": "override"}
        if kind == "date": return {"act": "date", "val": ovl[0], "src": "override"}
        if kind in ("select", "radio") or (kind == "checkbox" and f.get("multi")):
            k = rank(opts, ovl, q)
            return {"act": "pick", "k": k, "src": "override"} if k is not None else {"act": "none", "why": "override matched no option"}
        if kind == "checkbox": return {"act": "check", "src": "override"} if re.match(r"\s*(yes|true|checked?|i agree|agree|i acknowledge)", ovl[0], re.I) else {"act": "skip"}
    # ---- contact, address, e-signature
    cv = contact_value(f)
    if cv is not None and kind not in ("checkbox", "radio"):
        if cv == "": return {"act": "skip"}
        if kind == "select":
            l2 = re.sub(r"\s*:\s*$", "", low)
            prefs = ["United States", "United States of America", "USA", "US"] if l2.startswith("country") else ["California", "CA"] if re.match(r"state|province|region", l2) else [cv]
            k = rank(opts, prefs, label)
            return {"act": "pick", "k": k} if k is not None else {"act": "none", "why": f"no option for {cv!r}"}
        if kind == "date": return {"act": "none"}
        return {"act": "text", "val": cv}
    if kind == "tel" or re.search(r"\b(cell|mobile|phone|telephone)\b", low) and kind in ("text", "number"):
        if re.search(r"\b(home|work|office|other|alternate|secondary|fax|business)\b", low) and not f.get("req"): return {"act": "skip"}
        return {"act": "text", "val": re.sub(r"\D", "", P["phone"])[-10:]}
    # ---- EEO / voluntary self-identification
    if kind in ("radio", "select") and RACE_Q.search(q) and not re.search(r"hispanic or latino\??$", low):
        decl = [i for i, t in enumerate(opts) if DECLINE_OPT.search(t)]
        if decl: return {"act": "pick", "k": decl[0]}
    if kind == "checkbox" and f.get("multi") and RACE_Q.search(q):
        decl = [i for i, t in enumerate(opts) if DECLINE_OPT.search(t)]
        if decl: return {"act": "picks", "ks": decl[:1]}
        if not f.get("req"): return {"act": "skip", "note": "(declined: left blank)"}
    if kind == "checkbox" and not f.get("multi") and re.search(r"hispanic", " ".join(opts), re.I) and re.search(r"ethnic|hispanic", low + " " + (f.get("head") or "").lower()):
        return {"act": "skip", "note": "(not Hispanic or Latino: left blank)"}   # a lone 'Hispanic or Latino' box: unticked is the true answer
    # ---- single checkbox (e.g. a pre-screen 'I agree' box): an acknowledgement is ticked; a disclosure or opt-in never is
    if kind == "checkbox" and not f.get("multi"):
        t = opts[0] if opts else label
        if MARKETING.search(t) and not f.get("req"): return {"act": "skip"}
        if DISC.search(t): return {"act": "none"} if f.get("req") else {"act": "skip"}
        if ACK.search(t) or ACK.search(label) or AI_CONSENT.search(t): return {"act": "check"}
        if not f.get("req"): return {"act": "skip"}
        prefs = choice_for(t)
        if prefs and re.match(r"\s*(yes|i agree|agree|i acknowledge|i consent|accept)", str(prefs[0]), re.I): return {"act": "check"}
        return {"act": "none"}
    # ---- an optional 'If ...' follow-up ('If yes, ...', 'If a reasonable accommodation is requested, ...') stays empty
    if not f.get("req") and (re.match(r"\s*if\b", low) or IF_FOLLOWUP.search(low)): return {"act": "skip"}
    # ---- choice questions (select / radio / checkbox group)
    if kind in ("select", "radio", "checkbox", "mselect"):
        if SOURCE_Q.search(q) and not any(re.match(r"\s*(yes|no)\b", o, re.I) for o in opts):
            k = hear_index(opts, q)
            return {"act": "pick", "k": k} if k is not None else {"act": "none", "why": "no LinkedIn / job-board / internet option"}
        if RESIDE_IF_Q.search(q):   # 'If you live in Illinois, is your address in Chicago?': the applicant lives in Santa Clara, CA
            k = next((i for i, o in enumerate(opts) if NA_OPT.search(o)), None)
            if k is not None: return {"act": "pick", "k": k}
        prefs = choice_for(label, q) or (choice_for(q, q) if q != label else None)
        ack = [o for o in opts if ACK_OPT.search(o) and not NEG_OPT.search(o)]
        if ACK_ASK.search(q) and len(ack) == 1 and not DISC.search(q): prefs = ack
        elif SALARY_SHARE.search(q) and any(re.fullmatch(r"\s*yes\s*", o, re.I) for o in opts): prefs = ["Yes", "yes"]
        if OTHER_PERSON_Q.search(q):
            decl = [o for o in opts if re.search(r"wish|decline|prefer not|not to (say|answer|disclose)|choose not|don.t know|do not know|unknown", o, re.I)]
            if not decl: return {"act": "leave", "why": "about another person: only you can answer it"}
            prefs = decl[:1]
        if GITHUB_Q.search(q) and any(re.fullmatch(r"\s*yes\s*", o, re.I) for o in opts):
            prefs = ["Yes"] if re.search(r"github\.com/\S+", resume_text(job.resume)) else None   # read from the resume file itself
            if prefs: job.note("derived", f"{label[:80]}: the resume ({os.path.basename(job.resume)}) has a GitHub link")
        if prefs == ["__ASK__"]: return {"act": "leave", "why": "the rules leave this to you"}
        if prefs is None:
            t = text_for(label, q)   # a Yes/No rule written for free text ('No', 'Yes. I am a US citizen ...') also answers the choice
            if t and re.match(r"\s*(yes|no)\b", t, re.I):
                prefs = [re.match(r"\s*(yes|no)\b", t, re.I).group(1).capitalize()]
        if not prefs and ack and ACK_TOPIC.search(gtxt) and not DISC.search(q) and len(ack) == 1:
            prefs = ack; job.note("consent_fallback", label[:120])
        if not prefs and CONSENT_Q.search(q) and not DISC.search(q) and not MARKETING.search(q):
            prefs = ["Yes", "I agree", "I consent", "I acknowledge", "Agree", "Accept", "I accept"]; job.note("consent_fallback", label[:120])
        if not prefs: return {"act": "keep"} if cur else {"act": "none"}
        p0 = prefs[0] if isinstance(prefs[0], str) else ""
        if VISA_STATUS_Q.search(q) and re.match(r"\s*yes", p0, re.I):
            return {"act": "leave", "why": f"rule conflict: the rule says {p0!r} to a visa-status question"}
        if COMMUTE_Q.search(q) and re.match(r"\s*no\b", p0, re.I):
            return {"act": "leave", "why": f"rule conflict: the rule says {p0!r} to a commuting-distance question"}
        if FIVE_DAYS_Q.search(q) and re.match(r"\s*yes", p0, re.I):
            # 'on-site daily (5 days/week) or hybrid (3 days/week)?': the hybrid option only (the location gate has passed
            # this role, and a hybrid schedule is within the rule); a plain 5-day question stays with the applicant
            hy = [i for i, o in enumerate(opts) if re.search(r"hybrid", o, re.I) and not NEG_OPT.search(o) and not FIVE_DAYS_Q.search(o) and not re.search(r"daily|5 days|five days", o, re.I)]
            if len(hy) == 1:
                job.note("derived", f"{label[:80]}: the hybrid option only (never 5 days a week in the office)")
                return {"act": "picks", "ks": hy} if kind in ("checkbox", "mselect") and (f.get("multi") or kind == "mselect") else {"act": "pick", "k": hy[0]}
            return {"act": "leave", "why": "rule conflict: 5 days a week in the office (the location rule says never)"}
        if kind in ("checkbox", "mselect") and (f.get("multi") or kind == "mselect"):
            ks = []
            for p in prefs:
                k = rank(opts, [p], q)
                if k is not None and k not in ks:
                    ks.append(k)
                    if not re.search(r"select all|check all|all that apply", q, re.I): break
            return {"act": "picks", "ks": ks} if ks else {"act": "none", "rule": [str(x) for x in prefs[:6]]}
        k = rank(opts, prefs, q)
        if k is None and re.search(r"how many years|years of (\w+ )?experience", q, re.I):   # the bucket that holds the rules' number
            t = text_for(label, q) or ""
            m = re.match(r"\s*(\d+)", t) or re.match(r"\s*(\d+)", p0)
            if m:
                k = years_index(opts, int(m.group(1)))
                if k is not None: job.note("derived", f"{label[:80]}: {m.group(1)} years (rules) -> {opts[k]!r}")
        if k is None and NOTICE_Q.search(q) and re.match(r"\s*(immediate|asap|as soon|right away|2 weeks|two weeks|within)", p0, re.I):
            k = notice_index(opts)
            if k is not None: job.note("derived", f"{label[:80]}: 'immediately, within 2 weeks at most' -> {opts[k]!r}")
        if k is None and len(ack) == 1 and ACK_TOPIC.search(gtxt) and not DISC.search(q) and re.match(r"\s*(yes|i agree|agree|i consent|i acknowledge|accept|i understand|opt in)", p0, re.I):
            k = opts.index(ack[0]); job.note("consent_fallback", label[:120])
        if k is None: return {"act": "none", "rule": [str(x) for x in prefs[:6]]}
        return {"act": "pick", "k": k}
    # ---- dates
    if kind == "date":
        if TODAY_Q.search(low): return {"act": "date", "val": today_local().isoformat()}
        if START_DATE_Q.search(low):   # apply.py: 'Immediately (available to start right away)'; a few days out keeps the date valid (as apply_workday.py)
            job.note("derived", f"{label[:80]}: available immediately -> today + 3 days")
            return {"act": "date", "val": (today_local() + datetime.timedelta(days=3)).isoformat()}
        return {"act": "keep"} if cur else {"act": "none"}
    # ---- free text
    if kind in ("text", "textarea", "number"):
        numeric = kind == "number" or bool(re.search(r"numeric|number only|numbers only|digits only|whole number", q, re.I))
        v = text_for(label, q) or (text_for(q, q) if q != label else None)
        if v is None:
            c = choice_for(label, q) or (choice_for(q, q) if q != label else None)
            if c and c != ["__ASK__"] and isinstance(c[0], str) and re.fullmatch(r"(yes|no|none|n/a)", c[0].strip(), re.I): v = c[0]
        if v is None and f.get("req") and not cur:
            v = tech_answer(label)
            if v: job.note("tech_fallback", label[:120])
        if v and numeric:
            if re.search(r"salary|compensation|pay|remuneration|\bbase\b|\bote\b", q, re.I) and SALARY_NUM: v = SALARY_NUM
            else:
                m = re.search(r"\d[\d,]*(\.\d+)?", v); v = m.group(0).replace(",", "") if m else None
        if not v: return {"act": "keep"} if cur else {"act": "none"}
        if kind != "textarea": v = re.sub(r"\s*\n+\s*", " ", v)   # a newline in an input could submit the form
        return {"act": "text", "val": v}
    return {"act": "keep"} if cur else {"act": "none"}

async def fill_text(page, loc, val):
    """fill() only (never typing, never Enter: Enter in an input on the last step would send the application)."""
    try:
        await loc.scroll_into_view_if_needed(timeout=3000)
        await loc.fill("")
        await loc.fill(val)
        await loc.evaluate("(e)=>{e.dispatchEvent(new Event('change',{bubbles:true})); e.blur();}")
        await page.wait_for_timeout(120)
        return (await loc.input_value()).strip() != ""
    except Exception:
        return False

async def click_group(page, row, k, want=True, kind="radio"):
    """Tick option k of a radio / checkbox group (the label row first: the input itself is covered by an icon)."""
    inp = row.locator(f'input[type="{kind}"]').nth(k)
    try:
        if await inp.is_checked() == want: return True
        lab = row.locator("label.jv-input-group-row").nth(k)
        for tgt in (lab, lab.locator("i.icon").first):
            try:
                if await tgt.count():
                    await tgt.scroll_into_view_if_needed(timeout=2000); await tgt.click(timeout=3000); await page.wait_for_timeout(250)
                    if await inp.is_checked() == want: return True
            except Exception: pass
        await inp.evaluate("(e)=>e.click()"); await page.wait_for_timeout(250)
        return await inp.is_checked() == want
    except Exception:
        return False

async def apply_decision(page, job, f, d):
    """Carry out a decision on the page; returns the value shown afterwards, '' (left empty on purpose) or None."""
    row = page.locator(ROW(f["i"])).first
    kind, cur, opts = f["kind"], f.get("val") or "", f.get("opts") or []
    act = d["act"]
    if act == "keep": return cur or None
    if act == "skip": return d.get("note", "")
    if act in ("leave", "none"): return cur if (cur and act == "none" and f.get("kind") != "checkbox") else None
    if act == "text":
        v = d["val"]
        if cur and norm(cur) == norm(v): return cur
        loc = row.locator("textarea").first if kind == "textarea" else row.locator("input:not([type=radio]):not([type=checkbox]):not([type=hidden])").first
        return v if await fill_text(page, loc, v) else None
    if act == "date":
        if cur == d["val"]: return cur
        loc = row.locator('input[type="date"], input').first
        return d["val"] if await fill_text(page, loc, d["val"]) else None
    if act == "pick":
        k = d["k"]
        if kind in ("select", "mselect"):
            sel = row.locator("select").first
            if cur and norm(cur) == norm(opts[k]): return cur
            try:
                await sel.scroll_into_view_if_needed(timeout=3000)
                await sel.select_option(index=f["oidx"][k]); await page.wait_for_timeout(250)
                got = await sel.evaluate("(s)=>s.selectedIndex>=0?s.options[s.selectedIndex].text.replace(/\\s+/g,' ').trim():''")
                return got if norm(got) == norm(opts[k]) else None
            except Exception:
                return None
        if kind == "radio": return opts[k] if await click_group(page, row, k, True, "radio") else None
        if kind == "checkbox": return opts[k] if await click_group(page, row, k, True, "checkbox") else None
    if act == "picks":
        got = []
        for k in d["ks"]:
            if kind == "mselect":
                try: await row.locator("select").first.select_option(index=[f["oidx"][x] for x in d["ks"]]); got = [opts[x] for x in d["ks"]]; break
                except Exception: return None
            if await click_group(page, row, k, True, "checkbox"): got.append(opts[k])
        return "; ".join(got) or None
    if act == "check":
        return ("checked: " + (opts[0] if opts else f.get("label", ""))[:80]) if await click_group(page, row, 0, True, "checkbox") else None
    return None

async def fields(page):
    try: return await page.evaluate(FIELDS_JS)
    except Exception: return []

async def fill_step(page, job, step_no):
    """Answer every visible field of the current step; answers can reveal follow-up fields, so re-read until nothing new
    appears. Returns the fields still required and empty."""
    tried = set()
    def fkey(fs):   # (label, heading, kind, n-th such field): DOM indices shift when a follow-up field appears
        seen, out = {}, []
        for f in fs:
            k = (f["label"], f.get("head"), f["kind"]); seen[k] = seen.get(k, 0) + 1
            out.append((f, k + (seen[k],)))
        return out
    for _ in range(4):
        fs = fkey([f for f in await fields(page) if f["kind"] in FIELD_KINDS])
        todo = [(f, k) for f, k in fs if k not in tried]
        if not todo: break
        for f, k in todo:
            tried.add(k)
            key = (f["label"] or f.get("head") or "?")
            try:
                d = decide(job, f)
                if d["act"] == "leave":
                    job.why[key[:300]] = d["why"]; job.note("left_for_applicant", key[:200])
                    if f.get("val"):   # a value the site put there (resume parser): never vouched for by the filler
                        job.miss(f, why=d["why"] + f"; the form already shows {f['val'][:60]!r}: check it")
                elif d["act"] == "none" and d.get("rule"):
                    job.report.setdefault("no_matching_option", []).append({"label": key[:150], "rule": d["rule"]})
                elif d["act"] == "none" and d.get("why"):
                    job.why[key[:300]] = d["why"]
                if d.get("src") == "override": job.note("overrides_used", key[:120])
                v = await apply_decision(page, job, f, d)
                if v: job.ans(key, v)
                elif d["act"] in ("text", "date", "pick", "picks", "check"):
                    job.report["errors"].append(f"could not set {key[:70]!r} ({d['act']})")
            except Exception as e:
                job.report["errors"].append(f"{key[:60]}: {type(e).__name__}: {str(e)[:80]}")
        await page.wait_for_timeout(600)
    missing = []
    for f in await fields(page):
        if f["kind"] in FIELD_KINDS and f.get("req") and not f.get("val") and f["kind"] != "readonly":
            missing.append(f)
    return missing

# ---- the whole form, from the page's preloadedData (to report required questions on steps a dry run cannot reach)
def _js_value(t, key):
    m = re.search(key + r"\s*:\s*(\{|\[)", t)
    if not m: return None
    i = m.end() - 1; depth = 0; instr = False; esc = False
    for k in range(i, len(t)):
        ch = t[k]
        if instr:
            if esc: esc = False
            elif ch == "\\": esc = True
            elif ch == '"': instr = False
            continue
        if ch == '"': instr = True
        elif ch in "{[": depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                try: return json.loads(t[i:k + 1])
                except Exception: return None
    return None
KIND_OF = {"Name": "text", "Email": "text", "Hyperlink": "text", "Currency": "text", "Phone": "tel", "Zip": "text", "Number": "number", "Amount": "number", "Percentage": "number",
           "Date": "date", "Text": "textarea", "DropDown": "select", "Radio": "radio", "CheckBox": "checkbox"}
def form_outline(html):
    """[(step name, [field dicts as FIELDS_JS gives them])] in wizard order: main, EEO, OFCCP self-ID, pre-screen."""
    steps = []
    def conv(fl, head, ctx):
        out = []
        for x in fl or []:
            if not isinstance(x, dict): continue
            ot, ft = x.get("objectType"), x.get("fieldType")
            name = re.sub(r"<[^>]+>", " ", str(x.get("name") or x.get("Name") or "")).strip()
            if ot in ("Heading",) and not ft: head[0] = name; ctx.clear(); continue
            if (ot in ("Text", "Divider") and not ft) or not ft:
                if name: ctx.append(name)
                continue
            vals = [str(v.get("value") or "") for v in (x.get("values") or []) if isinstance(v, dict)]
            kind = KIND_OF.get(ft, "text")
            if kind == "select" and x.get("multiSelect"): kind = "checkbox"
            label = name
            if kind == "checkbox" and not label and len(vals) == 1: label = vals[0]
            out.append({"label": label, "kind": kind, "req": bool(x.get("required")), "opts": vals, "multi": kind == "checkbox" and len(vals) > 1,
                        "val": "", "head": head[0], "ctx": " ".join(ctx)[-1500:]})
        return out
    af = _js_value(html, "applyFields")
    if af: steps.append(("main", conv(af, [""], [])))
    ee = _js_value(html, "eeoFields")
    if ee: steps.append(("EEO", conv(ee, [""], [])))
    for key, name in (("ofccpFields", "OFCCP self-identification"), ("preScreeningFormFields", "pre-screen questions")):
        d = _js_value(html, key)
        if not isinstance(d, dict): continue
        fl = []
        for sec in d.get("section") or []:
            head, ctx = [str(sec.get("name") or "")], []
            for el in sec.get("element") or []:
                fs = el.get("fields") or []
                if el.get("kind") == "IAgreeCheckbox" and fs and isinstance(fs[0], dict):
                    fs = [dict(fs[0], values=[{"key": "x", "value": fs[0].get("name")}], name="")]
                fl += conv(fs, head, ctx)
        if fl: steps.append((name, fl))
    return steps

async def upload_resume(page, job):
    """Step 1 'Add Resume': Select -> File (a file chooser); the pasted text is the fallback. Jobvite parses the resume
    and may prefill fields; the filler then sets every field it has a rule for."""
    path = job.resume; name = os.path.basename(path); stem = os.path.splitext(name)[0]
    box = page.locator("#attachResume").first
    if not await box.count():
        job.miss({"label": "Resume upload (no 'Add Resume' section found)", "kind": "file"}); return False
    async def attached():
        try:
            t = re.sub(r"\s+", " ", await box.locator(".jv-file-list").first.inner_text())
            return stem.lower() in t.lower() or "pasted resume" in t.lower()
        except Exception: return False
    if await attached(): job.ans("Resume", name + " (already attached)"); return True
    btn = box.locator("button[jv-add-attachment], button").first
    ok = False
    try:
        await btn.scroll_into_view_if_needed(timeout=3000); await btn.click(timeout=4000); await page.wait_for_timeout(900)
        opt = page.locator(".jv-add-attachment:visible [jv-file-input], .jv-add-attachment:visible label:has-text('File')").first
        async with page.expect_file_chooser(timeout=8000) as fc:
            await opt.click(timeout=4000)
        await (await fc.value).set_files(path); ok = True
    except Exception as e:
        try:   # the hidden file input that the 'File' label opens
            inp = page.locator(".jv-add-attachment:visible input[type=file]").first
            if await inp.count(): await inp.set_input_files(path); ok = True
        except Exception: pass
        if not ok: job.report["errors"].append(f"resume file chooser: {type(e).__name__}")
    if ok:
        for _ in range(60):
            await page.wait_for_timeout(1000)
            if await attached() and not await box.locator(".jv-spinner:visible").count(): break
    if ok and await attached():
        err = await box.locator(".jv-error:visible").all_inner_texts()
        if err: job.report["errors"].append("resume upload: " + " ".join(err)[:200])
        job.ans("Resume", name); return True
    # fallback: paste the resume as text
    txt = resume_text(path)
    if txt:
        try:
            await page.keyboard.press("Escape")
            await btn.click(timeout=4000); await page.wait_for_timeout(800)
            await page.locator(".jv-add-attachment:visible").get_by_text(re.compile(r"^\s*paste", re.I)).first.click(timeout=4000)
            ta = page.locator(".jv-add-attachment:visible textarea").first
            await ta.fill(txt); await page.wait_for_timeout(300)
            await page.locator(".jv-add-attachment:visible button:has-text('Save')").first.click(timeout=4000)
            for _ in range(30):
                await page.wait_for_timeout(1000)
                if await attached(): break
            if await attached():
                job.ans("Resume", f"pasted text of {name}"); job.note("review_notes", "the resume was pasted as text (the file upload did not go through)"); return True
        except Exception as e:
            job.report["errors"].append(f"resume paste: {type(e).__name__}")
    job.miss({"label": "Resume upload (not confirmed on the page)", "kind": "file"})
    return False

async def attach_cover_letter(page, job):
    cl = P.get("cover_letter")
    if not cl or not os.path.exists(cl): return
    try:
        btn = page.locator("button[on-success^='addCoverLetter']").first
        if not await btn.count() or not await btn.is_visible(): return
        await btn.click(timeout=4000); await page.wait_for_timeout(800)
        async with page.expect_file_chooser(timeout=8000) as fc:
            await page.locator(".jv-add-attachment:visible [jv-file-input], .jv-add-attachment:visible label:has-text('File')").first.click(timeout=4000)
        await (await fc.value).set_files(cl); await page.wait_for_timeout(5000)
        job.ans("Cover Letter", os.path.basename(cl))
    except Exception as e:
        job.report["errors"].append(f"cover letter: {type(e).__name__}")

async def step_buttons(page):
    """(Next button or None, Send Application button or None), the visible ones."""
    nxt = page.locator('form[name="scopeData.applyForm"] button[ng-click="nextStep()"]:visible, .jv-apply-form button[ng-click="nextStep()"]:visible').first
    snd = page.locator('form[name="scopeData.applyForm"] button[type="submit"]:visible, .jv-apply-form button[type="submit"]:visible').first
    return (nxt if await nxt.count() else None), (snd if await snd.count() else None)

async def consent(page, job):
    """Data Consent: 'Location of Residence and Language' -> United States / English (else the option covering the US),
    then 'I Accept'. Returns True when the application form is showing."""
    sel = page.locator("select#jv-country-select, select[name='jv-country-select']").first
    if not await sel.count(): return True
    opts = await sel.evaluate("s=>Array.from(s.options).map(o=>[o.value,(o.text||'').replace(/\\s+/g,' ').trim()])")
    real = [o for o in opts if o[0] and not re.match(r"select your", o[1], re.I)]
    order = [lambda t: re.search(r"united states|\busa?\b", t, re.I) and re.search(r"english", t, re.I),
             lambda t: re.search(r"united states|\busa?\b|u\.s\.", t, re.I),
             lambda t: re.search(r"north america|americas", t, re.I),
             lambda t: re.search(r"english", t, re.I) and not NON_US_RE.search(t),
             lambda t: re.search(r"global|all countries|worldwide|international|rest of (the )?world|other countries", t, re.I)]
    choice = next((o for test in order for o in real if test(o[1])), None) or (real[0] if len(real) == 1 else None)
    if not choice:
        job.report["consent_options"] = [o[1] for o in real][:30]
        return False
    job.report["consent"] = f"residence/language: {choice[1]}; accepted"
    await sel.select_option(choice[0]); await page.wait_for_timeout(2500)
    form_sel = 'form[name="scopeData.applyForm"] .jv-form-field, #attachResume'
    if not await page.locator(form_sel).count():
        acc = page.get_by_role("button", name=re.compile(r"^\s*i accept\s*$", re.I))
        for _ in range(10):
            if await acc.count(): break
            if await page.locator(form_sel).count(): break
            await page.wait_for_timeout(1000)
        if await acc.count() and not await page.locator(form_sel).count():
            job.report["consent_text"] = re.sub(r"\s+", " ", await text(page))[:400]
            await acc.first.click(timeout=5000)
    for _ in range(40):
        await page.wait_for_timeout(1000)
        if await page.locator(form_sel).count(): return True
    return False

async def dump(page, job, tag):
    if not os.environ.get("JV_DUMP"): return
    try:
        await page.screenshot(path=f"{OUT}/{job.tag}_{ATS}_{tag}.png", full_page=True)
        open(f"{OUT}/{job.tag}_{ATS}_{tag}.html", "w").write((await page.content()).replace(P["email"], "<EMAIL>"))
    except Exception: pass

async def at_end(page, job):
    """Last step reached (or stopped early): the dry run ends with a screenshot; --submit sends the application and waits
    for the site's own confirmation."""
    shot = f"{OUT}/{job.tag}_{ATS}_dry.png"
    try: await page.screenshot(path=shot, full_page=True); job.report["screenshot"] = shot
    except Exception: pass
    await dump(page, job, "end")
    if "Resume" not in job.report["answers"] and not any("Resume" in u["label"] for u in job.report["unanswered"]):
        job.miss({"label": "Resume upload (no resume was attached)", "kind": "file"})   # never sent without the resume
    later = [u for u in job.report["unanswered"] if u.get("step")]
    here = len(job.report["unanswered"]) - len(later)
    if job.report["unanswered"]:
        job.report["result"] = ("DRY RUN: " if not SUBMIT else "NOT SUBMITTED: ") + f"{here} required field(s) unanswered" + (f" (+{len(later)} on later steps not reached)" if later else "")
        return
    nxt, snd = await step_buttons(page)
    if snd is None or nxt is not None:
        job.report["result"] = ("DRY RUN: " if not SUBMIT else "NOT SUBMITTED: ") + "the last step was not reached"; return
    if await challenge(page):
        job.report["captcha_seen"] = True; job.report["result"] = "NOT SUBMITTED: captcha"; return
    if not SUBMIT:
        job.report["result"] = "DRY RUN: ready"; return
    CONFIRM = re.compile(r"thank you for (applying|your (job )?application|your interest|submitting)|thanks for applying|application (was |has been )?(successfully )?(submitted|received|sent)|"
                         r"we('ve| have) received your application|successfully (applied|submitted)|your application is (complete|on its way)", re.I)
    job.report["submit_clicked"] = True
    before = page.url
    await snd.click(timeout=5000)
    for _ in range(60):
        await page.wait_for_timeout(1000)
        hits = await challenge(page)
        if hits:   # never solved, clicked or bypassed
            job.report["captcha_seen"] = True; job.report["captcha"] = hits
            await page.screenshot(path=f"{OUT}/{job.tag}_{ATS}_captcha.png", full_page=True)
            job.report["result"] = "NOT SUBMITTED: captcha"; return
        body = await text(page)
        _, snd2 = await step_buttons(page)
        if CONFIRM.search(body) and snd2 is None:
            job.report["submitted"] = True; job.report["result"] = re.sub(r"\s+", " ", body)[:300]; job.report["confirmation_url"] = page.url
            await page.screenshot(path=f"{OUT}/{job.tag}_{ATS}_submitted.png", full_page=True); return
        err = [t for t in await page.locator(".jv-message-error:visible, .jv-apply-error:visible, .jv-form-error:visible").all_inner_texts() if t.strip()]
        if err and page.url == before and not await page.locator(".jv-submit-spinner:visible").count():
            job.report["errors"] += [re.sub(r"\s+", " ", e)[:200] for e in err[:6]]
            break
    await page.screenshot(path=f"{OUT}/{job.tag}_{ATS}_after_submit.png", full_page=True)
    job.report["result"] = "NOT SUBMITTED: no confirmation after Send Application (it was clicked: check the site before any retry)"

def urls(url):
    """(job page, apply page) with nl=1, from a job or apply URL."""
    m = re.match(r"(https?://[^/]+/[^/?#]+/job/[A-Za-z0-9]+)", url or "")
    if not m: return None, None
    return m.group(1) + "?nl=1", m.group(1) + "/apply?nl=1"

async def run_one(br, item):
    job = Job(item); rp = f"{OUT}/{job.tag}_{ATS}_report.json"
    G["JOB_CHOICE_RULES"] = [(COMMUTE_Q.pattern, ["Yes", "yes"] if BAY_RE.search(str(item.get("where") or "") + " " + str(item.get("loc") or "")) else ["No", "no"])]
    G["JOB_TEXT_RULES"] = []
    if prior_company_apps:
        try: prior = prior_company_apps(job.tag, item.get("company"))
        except Exception: prior = []
        G["JOB_CHOICE_RULES"].insert(0, (PRIOR_Q, ["Yes", "yes"] if prior else ["No", "no", "No, I have not", "I have not applied"]))
        G["JOB_TEXT_RULES"] = [(PRIOR_FOLLOWUP, ("Yes: " + "; ".join(prior[:3]) + " (2026)") if prior else "N/A")]
        if prior: job.report["prior_company_apps"] = prior[:5]
    ctx = page = None
    blocked = []
    try:
        if NEVER_APPLY.search(job.tag + " " + item.get("company", "") + " " + job.url):
            job.report["result"] = "NOT SUBMITTED: do-not-apply company"; return job.report
        _lb = location_block(item.get("company", ""), job.url, item.get("loc", ""), item.get("where", ""))
        if _lb:
            job.report["result"] = "NOT SUBMITTED: location (" + _lb + ")"; return job.report
        verdict, why = location_gate(item)
        job.report["location"] = why
        if verdict == "out":
            job.report["result"] = f"NOT SUBMITTED: location ({why})"; return job.report
        job_url, apply_url = urls(job.url)
        if not job_url:
            job.report["result"] = "ERROR: not a Jobvite job URL (expected https://jobs.jobvite.com/<company>/job/<id>)"; return job.report
        ctx = await br.new_context(ignore_https_errors=True, user_agent=UA, viewport={"width": 1280, "height": 1800}, locale="en-US", timezone_id="America/Los_Angeles")
        page = await ctx.new_page()
        if not SUBMIT:   # hard guard: a dry run can never send the application, whatever happens on the page
            async def _block(route):
                blocked.append(route.request.url[:120]); await route.abort()
            await page.route(re.compile(r"/submitApplication"), _block)
        # ---- the job page: open / closed, and the posting's text for the location gate (5 days a week, work mode)
        await page.goto(job_url, wait_until="domcontentloaded", timeout=60000); await page.wait_for_timeout(2500)
        await dismiss_cookies(page)
        desc = ""
        try:
            d = page.locator(".jv-job-detail-description, .jv-job-detail-meta")
            desc = " ".join(await d.all_inner_texts()) if await d.count() else await text(page)
        except Exception: pass
        body = await text(page)
        if "/job/" not in page.url or re.search(r"no longer (available|accepting|open)|job (posting )?(is )?(closed|expired|not found)|position has been filled|page (you are looking for )?(doesn.t|does not) exist", body, re.I) and not await page.locator("a.jv-button-apply").count():
            job.report["result"] = "NOT SUBMITTED: job closed"; job.report["redirect"] = page.url; return job.report
        verdict, why = location_gate(item, desc)
        job.report["location"] = why
        if verdict != "ok":
            job.report["result"] = f"NOT SUBMITTED: location ({why})"; return job.report
        # ---- the apply page: Data Consent, then the form
        await page.wait_for_timeout(random.uniform(1500, 3500))
        await page.goto(apply_url, wait_until="domcontentloaded", timeout=60000); await page.wait_for_timeout(3000)
        await dismiss_cookies(page)
        if await challenge(page):
            job.report["captcha_seen"] = True; job.report["result"] = "NOT SUBMITTED: captcha"; return job.report
        if not await consent(page, job):
            await page.screenshot(path=f"{OUT}/{job.tag}_{ATS}_error.png", full_page=True)
            job.report["result"] = "NOT SUBMITTED: the Data Consent step has no United States option" if job.report.get("consent_options") else "NOT SUBMITTED: the application form did not open after Data Consent"
            job.report["errors"].append(re.sub(r"\s+", " ", await text(page))[:300]); return job.report
        await page.wait_for_timeout(2000)
        if await challenge(page):
            job.report["captcha_seen"] = True; job.report["result"] = "NOT SUBMITTED: captcha"; return job.report
        html = await page.content()
        job.report["recaptcha_invisible"] = bool(re.search(r"recaptcha/api\.js|initializeCaptcha\(", html))
        outline = form_outline(html)
        job.report["steps"] = [s for s, _ in outline]
        if item.get("cover_letter"): await attach_cover_letter(page, job)
        # ---- the wizard: main -> EEO -> OFCCP -> pre-screen
        for n in range(1, 8):
            await dismiss_cookies(page)
            if await challenge(page):
                job.report["captcha_seen"] = True; job.report["result"] = "NOT SUBMITTED: captcha"; return job.report
            if await page.locator("#attachResume").count() and "Resume" not in job.report["answers"]:
                await upload_resume(page, job)
            missing = await fill_step(page, job, n)
            for f in missing: job.miss(f)
            await dump(page, job, f"step{n}")
            nxt, snd = await step_buttons(page)
            log(job.tag, f"step {n}: {'Next' if nxt else ''}{'Send' if snd else ''}; unanswered {len(job.report['unanswered'])}")
            if job.report["unanswered"] or nxt is None:
                if job.report["unanswered"] and nxt is not None:   # the steps not reached: their required questions without a rule
                    for name, fl in outline[n:]:
                        for f in fl:
                            if not f["req"]: continue
                            d = decide(job, f)
                            if d["act"] in ("none", "leave"): job.miss(f, why=(d.get("why") or "no rule") + f" (later step: {name}, not reached)", step=name)
                await at_end(page, job); return job.report
            before = sorted((f["label"], f["kind"]) for f in await fields(page) if f["kind"] in FIELD_KINDS)
            await nxt.click(timeout=5000); await page.wait_for_timeout(2500)
            after = sorted((f["label"], f["kind"]) for f in await fields(page) if f["kind"] in FIELD_KINDS)
            if after == before:
                errs = [re.sub(r"\s+", " ", t)[:160] for t in await page.locator(".jv-invalid-field:visible").all_inner_texts()][:8]
                job.report["errors"] += errs or ["Next did not advance"]
                await at_end(page, job)
                job.report["result"] = "NOT SUBMITTED: the step did not advance (" + "; ".join(errs[:3])[:200] + ")"; return job.report
        job.report["result"] = "NOT SUBMITTED: too many steps"; return job.report
    except asyncio.CancelledError:   # the per-job timeout: the finally below still prints this item's one JSON line
        if not job.report["submitted"]:
            job.report["result"] = (f"NOT SUBMITTED: timed out after {JOB_TIMEOUT}s" + (" after Send Application was clicked (check the site before any retry)" if job.report.get("submit_clicked") else ""))
            job.report["errors"].append("job timeout")
        raise
    except Exception as e:
        job.report["result"] = f"ERROR {type(e).__name__}: {str(e)[:200]}"
        try:
            if page: await page.screenshot(path=f"{OUT}/{job.tag}_{ATS}_exception.png", full_page=True)
        except Exception: pass
        return job.report
    finally:
        try:
            if not SUBMIT and page is not None and blocked:
                job.report["errors"].append(f"a submitApplication request was blocked (dry run): {blocked[0]}")
        except Exception: pass
        json.dump(job.report, open(rp, "w"), indent=1)
        out = {k: job.report.get(k) for k in ("tag", "ats", "url", "submitted", "result", "unanswered", "errors")}
        out["errors"] = [str(e)[:300] for e in (out["errors"] or [])][:12]
        print(json.dumps(out), flush=True); PRINTED.add(job.tag)
        try:
            if ctx: await ctx.close()
        except Exception: pass

async def main():
    q = json.load(open(sys.argv[1]))
    if isinstance(q, dict): q = q.get("jobs") or q.get("items") or []
    q = [x for x in q if (x.get("ats") or ATS) == ATS]
    if "--locations" in sys.argv:
        for it in q:
            lb = location_block(it.get("company", ""), it.get("url", ""), it.get("loc", ""), it.get("where", ""))
            v, why = ("out", lb) if lb else location_gate(it)
            print(json.dumps({"tag": it.get("tag"), "company": it.get("company"), "title": it.get("title"), "loc": it.get("loc"), "where": it.get("where"), "url": it.get("url"), "verdict": v, "reason": why}), flush=True)
        return
    async with async_playwright() as p:
        kw = dict(headless=not HEADED, args=["--no-sandbox"])
        if os.path.exists("/opt/pw-browsers/chromium"): kw["executable_path"] = "/opt/pw-browsers/chromium"
        br = await p.chromium.launch(**kw)
        for n, item in enumerate(q):
            if not item.get("tag") or not item.get("url"):   # malformed queue item: reported, the batch goes on
                print(json.dumps({"tag": item.get("tag"), "ats": ATS, "url": item.get("url"), "submitted": False, "result": "ERROR: queue item without tag or url", "unanswered": [], "errors": []}), flush=True); continue
            rp = f"{OUT}/{item['tag']}_{ATS}_report.json"
            if os.path.exists(rp):
                try:
                    if json.load(open(rp)).get("submitted"):
                        print(json.dumps({"tag": item["tag"], "ats": ATS, "url": item.get("url"), "submitted": True, "result": "ALREADY SUBMITTED earlier (skipped)", "unanswered": [], "errors": []}), flush=True); continue
                except Exception: pass
            t0 = time.time()
            try: await asyncio.wait_for(run_one(br, item), timeout=JOB_TIMEOUT)
            except asyncio.TimeoutError:   # run_one's finally has normally printed the line already: exactly one line per item
                if item.get("tag") not in PRINTED:
                    print(json.dumps({"tag": item.get("tag"), "ats": ATS, "url": item.get("url"), "submitted": False, "result": f"NOT SUBMITTED: timed out after {JOB_TIMEOUT}s", "unanswered": [], "errors": ["job timeout"]}), flush=True)
            except Exception as e:
                if item.get("tag") not in PRINTED:
                    print(json.dumps({"tag": item.get("tag"), "ats": ATS, "url": item.get("url"), "submitted": False, "result": f"ERROR {type(e).__name__}: {str(e)[:200]}", "unanswered": [], "errors": [f"{type(e).__name__}"]}), flush=True)
            if n < len(q) - 1 and time.time() - t0 > 15:   # a gate stop opened no page: no need to wait
                g = random.uniform(*PACE); log("pace", f"waiting {int(g)}s before the next application"); await asyncio.sleep(g)
        await br.close()

if __name__ == "__main__":
    asyncio.run(main())
