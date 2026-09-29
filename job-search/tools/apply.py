#!/usr/bin/env python3
"""Generic job-application filler/submitter for Lever, Greenhouse, Ashby and Wellfound.
Usage: python3 job-search/tools/apply.py <lever|greenhouse|ashby|wellfound> <url> <tag> [--submit] [--answers file.json]
Profile/credentials are read from JOBS_DIR (default: session scratchpad), never from this repo.
"""
import asyncio, sys, json, os, re, time
from playwright.async_api import async_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cover
JOBS_DIR=os.environ.get("JOBS_DIR","/tmp/claude-0/-home-user-goExchange/8d20ffb7-2488-5f8f-a666-35334b9e3ba6/scratchpad/f")
OUT=os.path.join(JOBS_DIR,"out"); os.makedirs(OUT,exist_ok=True)
JOBS_DIR=os.path.expanduser(JOBS_DIR)
P=json.load(open(os.path.join(JOBS_DIR,"profile.json")))
for _k in ("resume","cover_letter"):
    if P.get(_k): P[_k]=os.path.expanduser(P[_k])
ANS=json.load(open(os.path.join(JOBS_DIR,"answers.json"))) if os.path.exists(os.path.join(JOBS_DIR,"answers.json")) else {}
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
CODE_WAIT=int(os.environ.get("CODE_WAIT","420"))   # seconds to wait for an emailed verification code handed over via out/<tag>_code.txt
LAST_OPTIONS={}                                     # label -> option texts seen in the last dropdown scan (for reports)
def applicant_cover_text():
    """Body text of the applicant's own cover letter PDF (profile.json "cover_letter"), cached beside it; '' if unavailable."""
    pdf=P.get("cover_letter")
    if not pdf or not os.path.exists(pdf): return ""
    cache=os.path.join(JOBS_DIR,"cover_letter.txt")
    if os.path.exists(cache) and os.path.getmtime(cache)>=os.path.getmtime(pdf): return open(cache).read()
    try:
        from pdfminer.high_level import extract_text
        t=re.sub(r"\n{3,}","\n\n",extract_text(pdf)).strip()
    except Exception: t=""
    open(cache,"w").write(t); return t
CL_OWN=applicant_cover_text()
HEADED="--headed" in sys.argv
import shutil, platform
if HEADED and platform.system()=="Linux" and not os.environ.get("DISPLAY") and shutil.which("xvfb-run"):
    os.execvp("xvfb-run",["xvfb-run","-a","-s","-screen 0 1280x2000x24",sys.executable]+sys.argv)
submit="--submit" in sys.argv
# --pace MIN MAX: in batch mode, wait a random MIN..MAX seconds between applications (one at a time, human-paced)
PACE=(float(sys.argv[sys.argv.index("--pace")+1]),float(sys.argv[sys.argv.index("--pace")+2])) if "--pace" in sys.argv else None
BATCH = sys.argv[1]=="batch"
if BATCH:
    JOBS=json.load(open(sys.argv[2])); ats=url=tag=None; extra={}
elif sys.argv[1]=="outlook-test":
    ats=url=tag=None; extra={}
else:
    ats,url,tag=sys.argv[1],sys.argv[2],sys.argv[3]
    extra=json.load(open(sys.argv[sys.argv.index("--answers")+1])) if "--answers" in sys.argv else {}
first,last=P["name"].split(" ",1)
# label regex -> value ; order matters
TEXT_RULES=[
 (r"first and last name|legal name|full legal name|^(full )?name\b|^your name|_systemfield_name", P["name"]),
 (r"first ?name", first),(r"last ?name|surname|family name", last),
 (r"preferred name", first),(r"e-?mail", P["email"]),(r"phone|mobile", P["phone"]),
 (r"zip|postal", "95050"),
 (r"country( of residence| you (live|reside) in)?$|^country\b|which country|country of residence", "United States"),
 (r"sponsorship needs?|require (employer |visa |company )?sponsorship|sponsorship to work|need sponsorship", "None. I am a US citizen and need no sponsorship or visa transfer."),
 (r"where do you (currently )?(reside|live)|city,? state|current city|city and state|city of residence", "Santa Clara, CA"),
 (r"countries .{0,30}(right|authori[sz]ed|eligible) to work|(right|eligib\w+) to work|which countr|what countr", "United States"),
 (r"^company name|^(most recent |current )?(company|employer)( name)?$|name of your .{0,30}(company|employer)|(current|most recent|last) .{0,20}(company|employer)", P["org"]),
 (r"start (date )?year|^from year|start \(year\)", "2023"),
 (r"end (date )?year|^to year|end \(year\)", "2026"),
 (r"if (you answered|yes,? please|applicable)|not applicable|type 'n/a'|government entity|please (list|specify|explain).*(if|when) (yes|applicable)", "N/A"),
 (r"^(street |home |mailing )?address", P["location"]),
 (r"linkedin", P["linkedin"]),(r"github", P["github"]),(r"portfolio|website|personal site", P["github"]),
 (r"current (company|employer)|most recent (company|employer)|^company$|^employer$", P["org"]),
 (r"current (title|role)|job title|^title$", "CTO & Technical Co-Founder / Principal Architect"),
 (r"^(current |your |home )?location\b|^city\b|where (are you|do you) (based|live|located)", P["location"]),
 (r"salary|compensation|pay expectation|desired (base|comp)|expected (base|salary|comp)", "$300,000 - $350,000 base"),
 (r"today'?s date|date of application|application date|date \(mm/dd/yy", time.strftime("%m/%d/%y")),
 (r"^middle (name|initial)|middle name", "N/A"),
 (r"snack|favou?rite (food|coffee|drink|song|movie|book|meal)|fun fact|hobby|hobbies|for fun|outside of work|guilty pleasure|spirit animal|superpower", "Whatever is on the table: the ideas come from the problem, not the snack. Outside of work I read widely and tinker with open-weight models on my own hardware."),
 (r"able to travel|willing to travel|travel (for|requirements?|expectations?)|percentage of travel|% travel", "Yes, I can travel as needed for the role."),
 (r"know anyone (who works|at|employed)|anyone you know (works|at)|friends or family (at|who work)", "No"),
 (r"(average |typical |largest )?size of (the )?teams? (you've|you have|you) (managed|led)|how many (people|engineers|direct reports|reports) (have you|do you|did you) (managed|manage|lead|led)|team size|number of direct reports", "It varies by role: as Chief Architect at Yahoo Finance I directed 75+ engineers and partners across the platform modernization program; as CTO and Technical Co-Founder at Hyperion AI I led a small founding engineering team hands-on."),
 (r"start date|available to start|availability|notice period", "Immediately"),
 (r"years? of (relevant |professional |total )?experience|how many years", "25"),
 (r"when (can|could|would|are you able to) you (realistically |potentially |ideally )?start|start date|earliest (start|availability)|available to start|notice period|availability to start|how soon", "Immediately (available now, no notice period)"),
 (r"compensation expectation|salary expectation|desired (salary|compensation|base)|expected (salary|compensation|base)|(salary|compensation|pay) (requirements|expectations|target)|target (salary|compensation)", "Flexible: my recent base compensation has been in the $300-350K range, and I am open to the right mix of base and equity for the right role."),
 (r"heard about us from a (friend|family|current|former)|referr(ed|al).*(name|who)|name of (the |your )?(employee|referrer|person who)|who referred you|referred by", "N/A"),
 (r"how your (experience|background) aligns|aligns? (to|with) (the )?(role|position|requirements|job)|why (are you|would you be|you are) a (good |great |strong )?fit|what makes you a (good |great |strong )?fit|relevant experience for this role", "25+ years building and leading distributed, low-latency systems at JPMorgan Chase, Morgan Stanley, Bloomberg and Yahoo Finance (Chief Architect for the AWS modernization serving ~40M daily users), and most recently CTO & Technical Co-Founder of Hyperion AI, where I built agentic AI platforms end to end. I combine hands-on architecture and code (Python, Rust, C++, Go) with leading engineering teams through delivery and 24x7 operation."),
 (r"(iac|infrastructure as code).*(tools|used|experience)|(which|what) (iac |infrastructure |devops |cloud )?(tools|technologies|platforms|frameworks) (have you|do you)", "Terraform and Kubernetes on AWS and GCP (plus Azure), with Jenkins and Puppet deployment pipelines earlier at JPMorgan Chase and Morgan Stanley; CI/CD with correctness gates and observability via OpenTelemetry and Prometheus/Grafana."),
 (r"from where do you (intend|plan|expect) to work|where (will|would|do) you (be )?work(ing)? from|intended (work )?location|where would you (be )?(based|located)", "Santa Clara, CA (San Francisco Bay Area); open to hybrid in the SF Bay Area or New York City"),
 (r"willing to (work|come|be)|open to working|days? (a|per) week|days (from|in|at) (one of )?our office|office hub|in.office|on.?site|hybrid", "Yes"),
 (r"(ever|currently|previously) (work|employ|been employed)|worked (at|for) .* before|former .{0,30}(employee|contractor)|current or former", "No"),
 (r"programming language|language\(s\) do you prefer|preferred language|which languages?", "Python and Go (also Rust and C++)"),
 (r"legal address|full address|home address|\baddress\b", P["location"]),
 (r"state/region|state or province|\bstate\b.*(reside|live|located|residence)|\bregion\b|province", "California"),
 (r"(how|where) did you (first |initially )?(hear|learn|find out)|hear about|learn about|find out about|referral source|source", "Company careers page"),
 (r"^why\b|why (do you want|are you interested|.*join|.*this role|.*us)|interest(ed)? in (this|the) (role|position|company)|tell us (a little )?about yourself|cover letter|anything else|additional information|why .*good fit|what excites you", ANS.get("why_us","")),
 (r"romanticize|startup life|early[- ]stage life|what (do you )?(dislike|hate) about|hardest part of", "People romanticize the pace and the upside; the reality is long stretches of unglamorous work: infrastructure, correctness, hiring, and keeping customers happy while the roadmap keeps changing. What genuinely excites me is owning outcomes end to end, shipping code that matters, and building the team and the architecture at the same time, which is exactly what I did as CTO and Technical Co-Founder at Hyperion AI."),
 (r"makes you excited|excited to contribute|excites? you|interests? you (about|in|most)|what (specifically )?(interests|appeals|attracts) (you|to you)|appeal(s|ing)? (to you )?about|mission or approach|why (this|our) (mission|company|team|startup)|not somewhere else|what draws you|what attracts you|what motivates you|your motivation", ANS.get("why_us","")),
 (r"describe (a|an|the) (backend |distributed |large[- ]scale |complex |production |critical |high[- ]scale )?(system|service|architecture|platform|pipeline) (that )?you('ve| have)? (designed|built|architected|re-?architected|owned|led|shipped)|system you('ve| have)? (designed|built|architected|re-?architected)|being wrong costs money|significantly re-?architected|hardest (technical|engineering) (problem|challenge)|most (complex|challenging) (system|technical|engineering)", "At JPMorgan Chase I architected multi-asset execution paths where being wrong costs money directly: sub-250-microsecond paths designed for the 100K-500K TPS range, where my contribution was the end-to-end architecture and the correctness and latency discipline around it. Later, as Chief Architect at Yahoo Finance, I led the re-architecture of the quotes, charts, portfolios, screeners and research platform (roughly 40M daily and 150M monthly active users) through its bare-metal-to-AWS migration: phased migration, cutover and rollback planning, and 24x7 operation, directing 75+ engineers and partners. Most recently at Hyperion AI I built the agentic platform end to end (multi-agent plan-validate-dispatch-replan orchestration, open-weight model serving through llama.cpp and vLLM paths, evaluation workflows) with correctness gates, replay harnesses and observability in production."),
 (r"largest[- ]scale|biggest (system|scale)|scale (of|at which) .{0,40}(system|built|operated)|requests/sec|requests per second|\bQPS\b|\bTPS\b|\bTPM\b|\bDAU\b|data volume|highest[- ]scale|scale you.ve (built|operated|worked)", "Largest scale: at Yahoo Finance I was Chief Architect for a platform serving roughly 40M daily and 150M monthly active users (quotes, charts, portfolios, screeners, research), leading its bare-metal-to-AWS modernization with 75+ engineers and 24x7 operation. Earlier at JPMorgan Chase I architected sub-250-microsecond multi-asset execution paths designed for the 100K-500K TPS range. Most recently at Hyperion AI I built the agentic platform end to end (multi-agent orchestration, open-weight model serving via vLLM and llama.cpp, evaluation and observability) with production correctness gates."),
 (r"most recent (production )?(software )?project|recent project you (worked|built|shipped)|describe (a|the) (recent|technical|significant) project|project you.re (most )?proud|proudest (technical )?(work|project|achievement)", "Most recently I built Hyperion AI's agentic platform end to end: MCP clients and servers (3 servers, 9 tools), a multi-agent plan-validate-dispatch-replan loop, open-weight model serving (Qwen, Llama 3.3-70B, gpt-oss) through llama.cpp and vLLM integration paths, fine-tuning and evaluation workflows, and a reproducible 121-measure benchmarking scorecard informed by MLPerf Inference and BFCL. It runs in production with correctness gates, replay harnesses and observability (OpenTelemetry, Prometheus/Grafana)."),
 (r"experience (managing|leading|building|running|owning|with|in).*(explain|describe|elaborate|tell us)|please (explain|describe|elaborate)|describe your (experience|background|leadership)|tell us about your (experience|background|leadership)|walk us through|what is your experience (leading|managing|with|in|building|running|owning)|share (an example|your experience)", "Yes. As CTO & Technical Co-Founder at Hyperion AI (2023-2026) I built and led the engineering team and owned customer-facing deployments end to end, from architecture through production rollouts with customers. Earlier, as VP / Lead Architect at JP Morgan Chase and VP / Technical Lead at Morgan Stanley, I led technical leads and architects delivering trading and application platforms directly with client and trading-desk teams, and at Cadence and Ankr I was the architect embedded with customer-facing engineering. In total 25+ years of hands-on engineering and 10+ years leading engineers, architects, and solutions-oriented teams."),
 (r"greatest (impact|achievement)|proudest|accomplishment|most exceptional|exceptional thing|most impressive (thing|work|project)|biggest (achievement|win)|achieved or built|what have you built that|most proud", ANS.get("impact","")),
 (r"work environment|thrive|attributes", ANS.get("environment","")),
 (r"pronoun", "He/him"),
 (r"gender identity|^gender$|\bgender\b", "Male"),
 (r"university|school|college|alma mater", "University of Madras"),
 (r"degree|field of study|major", "Bachelor of Engineering, Computer Science and Engineering"),
]
CHOICE_RULES=[
 (r"authori[sz]ed? .{0,40}without (company |employer |visa |any )?sponsorship|without (company |employer |visa )?sponsorship|legal(ly)? authori[sz]ation to work in the (us|u\.s\.|united states)", ["Yes","yes"]),   # US citizen: authorized without sponsorship
 (r"(require|need|will you .{0,30}require) .{0,30}(work authori[sz]ation|visa|sponsorship|immigration)", ["No","no"]),   # US citizen: will never require work authorization / sponsorship (Wellfound's standard question)
 (r"(5|five) days? (per|a|each) week|five days a week|5 days/week|(5|five)[- ]days? (on-?site|in[- ]office|in[- ]person)", ["No","no"]),   # applicant: no fully on-site 5-day roles
 (r"engineering blog|influence your decision|how much did .{0,60}influence", ["3 = Neutral","Neutral","3","Moderate","4 = Moderate"]),   # marketing-attribution scale questions
 (r"level of experience with (ai|llm|genai|generative ai|ai tools|coding assistants)|experience with ai (tools|coding)|proficien(cy|t) with ai|how (often|much) do you use ai", ["4 - Cross-functional","Cross-functional","Expert","Advanced","Extensive","Daily","Every day","Power user","5","4"]),   # AI-tooling experience scale (not an AI-disclosure question)
 (r"personally built|built and (operated|shipped|deployed)|(built|shipped|deployed|operated) .{0,30}(ai agent|agentic|llm|ml model|machine learning).{0,30}(production|in prod)|production (ai|ml|llm|agent)", ["Yes","yes"]),   # hands-on AI/agent production experience
 (r"grow into (greater )?leadership|developed? another (engineering )?leader|helped another engineer|grow(n)? (an engineer|engineers) into|promoted .{0,30}(engineer|report)s? (to|into)", ["Yes, I developed an engineer into","Yes, I coached","Yes, I have","Yes","yes"]),   # has grown engineers into leads/managers (CTO, Chief Architect)
 (r"partner(ed|ship)? with product|collaborat\w* with product|co-?own(ed)? product|work(ed)? with product (teams|managers)", ["I co-owned product direction","Co-owned","I regularly collaborated","Regularly","Yes"]),   # co-founder/CTO: co-owned product direction
 (r"formal(ly)? (people |line )?manag|people management experience|formal manager", ["I have been the formal manager","Formal manager","I have managed","Yes","yes"]),   # has been the formal manager of engineers
 (r"accommodation|assistance to participate|reasonable adjustment", ["No, I do not require","No, I do not","No","no"]),   # no accommodation needed
 (r"how often did you (interact|work|meet|communicate)|how frequently .{0,40}(stakeholders|customers|clients)|interact directly with (non-technical|customers|clients|stakeholders)", ["Daily","Every day","Weekly"]),   # CTO/co-founder: daily stakeholder contact
 (r"athlete|esports? (competitor|player)|professional (gamer|player)|participate in (games|contests)", ["No","no"]),
 (r"proof of (employment |work )?authori[sz]ation|employment authori[sz]ation|provide (proof|documentation) .{0,30}(eligib|authori)", ["Yes","yes"]),
 (r"(EST|EDT|ET|Eastern|PST|PDT|PT|Pacific|CST|Central|MST|Mountain)\b.{0,30}(business )?hours|work (in|during) .{0,20}(time ?zone|hours)|overlap with .{0,30}(hours|time ?zone)", ["Yes","yes"]),   # remote: works any US business hours
 (r"credentialed|been a (client|patient|provider|therapist|customer) of|used our (product|service|platform) as a", ["No","no"]),   # never a provider/client of the hiring company
 (r"immediate family|relatives? (who )?(work|employed)|family members? (who )?(work|employed)|debarred|excluded by the OIG|convicted|felony|criminal|non-?compete|conflict of interest|restrictive covenant", ["No","no"]),   # compliance questions: none apply
 (r"are you ready|ready to (take|do|complete|go through|participate)|actively involved in product development|technical (portion|assessment|interview|screen|take-?home|challenge)|hands[- ]on (coding|technical)|comfortable (writing|with) code|still (write|writing) code|willing to (code|write code)", ["Yes","yes"]),   # hands-on leader: yes to technical interviews
 (r"^location( \(city\))?$|^(current |your |home )?location$|^city$", ["Santa Clara, California","Santa Clara, CA","Santa Clara"]),
 (r"select your (current )?location|your current location|which (hub|location|city|metro) (are you|is closest|do you)|where (are|do) you (currently )?(based|live|located|reside)", ["San Francisco Bay Area","SF Bay Area","Bay Area","San Francisco","San Jose","Santa Clara","Bay Area, CA","California","Remote, United States","Remote - United States","Remote (US)","US Remote","United States","Remote","Outside of","Outside the","Other location","Elsewhere","Other","None of the above"]),
 (r"sponsor", ["No","no"]),
 (r"interviewed .*before|applied .*before|previously (applied|interviewed)", ["No","no"]),
 (r"in[- ]person|open to working|come into the office|days? (a|per) week|times (a|per) week|commit to being in|being in (one of )?(these|our|the) offices?|days (from|in|at) (one of )?our office|office hub", ["Yes","yes"]),
 (r"understand that .{0,40}(may )?use ai|company may use ai|we (may )?use ai|ai tools to assist in the (application|interview)", ["Yes","I understand","I acknowledge","Acknowledge"]),
 (r"how (do )?you use ai|use ai tools today|describes (how )?you use ai|your (use|usage) of ai tools|ai (proficiency|fluency)", ["I design or automate workflows with AI","I regularly use AI tools","I have experimented with AI tools","Advanced","Expert"]),
 (r"ai policy|(did|have) you use(d)? (any )?ai|without (the use of )?(any )?ai|no ai (assistance|tools)|ai.{0,20}(was|were) not used|(did not|didn't|have not) use.{0,20}ai|used? ai (to|in|for) (this|the|your|my) application|ai assistance", ["__ASK__"]),
 (r"authori[sz]ed to (lawfully |legally )?work|lawfully work|authori[sz]ation to work|legally (able|eligible|authorized)|work authori[sz]ation|eligible to work|right to work|employment eligibility",["Yes","yes","Can work for any employer","Any employer","I am authorized","Authorized","U.S. Citizen","US Citizen","Citizen"]),
 (r"currently an? .{0,60}(employee|contractor|intern)\b|current(ly)? (employee|contractor) of|employed by .{0,40}(currently|now|today)|(ever|previously|formerly) been (an? )?(employee|contractor|intern|employed)", ["No","no"]),   # not a current or former employee of the hiring company
 (r"experience with (aws|gcp|azure|the cloud|cloud (platforms|infrastructure)|kubernetes|terraform)|describe your (level of )?experience (with|in)", ["Both hands-on","Both","Hands-on experience operating","Hands-on","Expert","Advanced","Extensive","Very experienced","10+ years","5+ years"]),   # hands-on and led teams
 (r"\bFINRA\b|series (7|24|27|63|65|66|99)\b|securities licen[sc]e", ["No","no"]),
 (r"citizen", ["Yes","U.S. Citizen","US Citizen"]),
 (r"^(?!.*(indicate|select|provide|enter|choose|which|what)\b.{0,25}\bstate\b).*(reside|live|based|located|living) in the (united states|u\.?s\.?a?\b|usa)", ["Yes","yes"]),
 (r"(?=.*(san francisco|bay area|california|santa clara|san jose|palo alto|silicon valley|united states|\bu\.?s\.?a?\b))(currently |are you |do you )?(located|based|residing|reside|live|living) (in|within|near)", ["Yes","yes","I currently live","I live in"]),   # the applicant lives in Santa Clara, CA
 (r"(?!.*(san francisco|bay area|california|santa clara|san jose|palo alto|silicon valley|united states|\bu\.?s\.?a?\b))(currently |are you |do you )?(located|based|residing|reside|live|living) (in|within|near) ", ["No","no"]),   # any other named place (NYC, Chicago, Taipei, ...): the applicant is in Santa Clara, CA
 (r"currently live (in|or)|live (in|near) (this |the )?(job|role|position)|live or (are you )?willing to relocate", ["I currently live in this job's location","I currently live","I live in","Yes, I live","I am willing to relocate","Willing to relocate","Yes"]),
 (r"relocat", ["Yes","yes"]),
 (r"remote|hybrid|on-?site|in[- ]office|work from|commut", ["Yes","yes","Hybrid","Remote"]),
 (r"pronoun", ["He / Him","He/Him","He/him","He, him","He"]),
 (r"have you (ever )?used|are you a (current )?(user|customer)|used (our|the) (product|app|platform)", ["Yes","yes"]),
 (r"FHIR|HL7|CCDA|HIPAA|\bPHI\b|\bEHR\b|EMR\b|clinical|healthcare partner|medical device|\bFDA\b|GxP|pharma|ICD-?10|CPT codes|claims data|payer", ["No","no"]),   # not in the applicant's background: answer honestly
 (r"previously,? (applied|worked|employed)|currently,? (or have you|work|employed)|currently employed by|worked (for|at) .* before|have you (ever )?worked (at|for)|worked at .*(employee|contractor|consultant)|former .{0,30}employee|current .{0,30}employee|current or former|former or current|ever (worked|been employed)|(previously|ever) been employed|been employed (at|by|with)",["No","no","I have not previously been employed","I have not been employed","I have not worked","have not worked","have not been","Never worked","Never","None of the above","Not applicable","N/A"]),
 (r"^(?!.*(veteran|military|armed forces))(have you (ever )?(worked|built|owned|operated|led|designed|managed|shipped|deployed|architected|scaled|mentored|hired|delivered|run|written)|.*experience (with|in|building|leading|managing|designing)|.*are you (comfortable|experienced|familiar|proficient)|.*do you have (hands-on )?experience|.*have you (previously )?(held|been in|served as))", ["Yes","yes"]),
 (r"transgender", ["No","no","I don't wish to answer","Decline"]),
 (r"sexual orientation|lgbtq", ["I don't wish to answer","Decline To Self Identify","Decline","Prefer not to say","Prefer not to answer","Heterosexual","Straight"]),
 (r"first.generation", ["I don't wish to answer","Decline","Prefer not","No","no"]),
 (r"gender|sex\b|\bmale\b|female|\bman\b|woman", ["Male","Man","Cisgender man","Cis man","Cis-gender man"]),
 (r"programming language|language\(s\)|which language|coding language", ["Either","Both","Python","Go"]),
 (r"start (date )?month|^from month", ["January"]),
 (r"end (date )?month|^to month", ["September"]),
 (r"start (date )?year|^from year", ["2023"]),
 (r"end (date )?year|^to year", ["2026"]),
 (r"metropolitan area|metro area|closest to your (city|residence|home)|nearest (city|metro)|city of residence", ["San Jose, California","San Jose, CA","San Jose","Santa Clara","San Francisco, California","San Francisco, CA","San Francisco","Sunnyvale","Oakland"]),
 (r"cities .{0,30}available|available to work in|which (cities|locations)|what cities|preferred cit", ["San Francisco","New York","Remote","Any","Open to any"]),
 (r"languages? (you|do you) (speak|are proficient)|select all the languages|languages? .{0,20}proficient|spoken languages?|fluent in", ["English","Python","Go"]),
 (r"office location|preferred (office|location|hub)|which office|office (would|do|will) you|closest office|nearest office",["Menlo Park","San Francisco","Santa Clara","Sunnyvale","Mountain View","Palo Alto","San Jose","Bay Area","California","Remote","New York"]),
 (r"hispanic|latino", ["No","I am not Hispanic or Latino","Not Hispanic or Latino"]),
 (r"\brace\b|racial|ethnic|hispanic|asian|caucasian|african", ["I don't wish to answer","Decline To Self Identify","Decline to self identify","Decline to self-identify","Decline","Prefer not to say","Prefer not to answer","I do not wish to answer","I don't wish"]),
 (r"golden record|master data management|\bMDM\b|data governance (lead|owner)|chief data officer", ["No","no"]),   # not in the applicant's background: answer honestly
 (r"support of .{0,40} to maintain (that |your )?(work )?authori[sz]ation|maintain (that |your )?(work )?authori[sz]ation|visa support|immigration support", ["No","no"]),
 (r"how much notice|notice period|notice do you (require|need)", ["No notice needed","No notice","None","Immediately","Available immediately","0 weeks","Less than 2 weeks","2 weeks"]),
 (r"compensation is standardi[sz]ed|comfortable with the (salary|compensation|pay)|salary (range |band )?(is )?non-negotiable|salary being offered|within (the|this) (salary|compensation|pay) range|acceptable to you", ["Yes","yes","I understand","Yes, I understand"]),   # applicant: salary is not a filter
 (r"(directly |previously |ever )?managed (a |an )?(team|engineers|people|direct reports|software)|people manag|managed (software|ml|ai) engineers|have you (been|served as) (a |an )?(engineering |people )?manager", ["Yes","yes"]),
 (r"(willing|able|open|available)[^.?]*travel|travel (twice|once|up to|\d+ ?%|a quarter|per (month|quarter|year))|travel requirement", ["Yes","yes"]),
 (r"export control|u\.?s\.? person|ITAR|EAR", ["U.S. Citizen","US Citizen","U.S. citizen or national","I am a U.S. person","Yes","A"]),   # US citizen: option A on lettered export-control lists
 (r"veteran|military", ["I am not a protected veteran","Not a protected veteran","I am not a veteran","No military service","I have not served","No","Decline To Self Identify","I don't wish to answer","Prefer not to say"]),
 (r"disabilit", ["No, I do not have a disability","No, I don't have a disability","No","I do not have a disability","I don't wish to answer"]),
 (r"18\+|18 (years|or older)|age of 18|over 18|at least 18", ["Yes","yes"]),
 (r"subject to (any )?(employment|non-?compete|restrictive|post)|post-?employment restriction|restrictive covenant|non-?solicit|bound by (a|any) (non-?compete|agreement)", ["No","no","None"]),
 (r"\bsms\b|whatsapp|text message|receive (communications|updates|marketing|alerts)|marketing communications|newsletter|opt.in|stay up to date|keep me (updated|informed)|job alerts|similar jobs|careers content", ["No","no"]),
 (r"background check|drug|non-?compete|agreement|acknowledge|certify|consent|privacy|terms|policy|subscribe|agree|gdpr|disclosure|notice",["Yes","I agree","I acknowledge","I consent","Consent","Confirmed","Confirm","I have read","Acknowledge","Agree","Accept","yes"]),
 (r"how did you (first |initially )?(hear|learn|find out)|hear about|learn about|find out about|source", ["Company Website","Company website","Company Careers","Careers Site","Careers Website","Other","Job Board","Other/Not Listed","Google Search","Search engine","Careers page","Career Page"]),
 (r"school|university|college", ["University of Madras","Other","University"]),
 (r"discipline|major|field of study", ["Computer Science","Computer Engineering","Engineering","Other"]),
 (r"degree|education|highest level", ["Bachelor's Degree","Undergraduate/Bachelor's degree","Bachelor's","Bachelors","Bachelor"]),
 (r"outside business|advisory|consulting|consultanc|freelance|board (role|membership)|side business|other business|own, operate|provide services to|conflict of interest|moonlight", ["No","no","None"]),
 (r"family member|relative|personal relationship|related to (anyone|any employee|an employee)|know anyone|referred by|were you referred|referred to this", ["No","no","None"]),
 (r"been employed by|employed by .* in the past|in the past", ["No","no","Never"]),
 (r"security clearance|clearance", ["No","None","no"]),
 (r"visa", ["No","no"]),
 (r"sanction|embargo|belarus|\bcuba\b|\biran\b|north korea|\bsyria\b|\brussia\b|following countries or regions|restricted (countr|region)", ["No","no"]),
 (r"country", ["United States","United States of America","USA"]),
 (r"state|province", ["California","CA","Another State in the US","Another state","Other US","Other"]),
 (r"experience with|familiar|proficien|years|how much (\w+ ){0,4}experience", ["25+ years","20+ years","15+ years","10+ years","10+","More than 10 years","10 or more","Over 10","8+ years","7+ years","6+ years","5+ years","5+","More than 5 years","5 or more","5-10 years","5 - 10 years","Expert","Yes"]),
]
def pick(label,rules):
    l=label.lower()
    for pat,val in rules:
        if re.search(pat,l,re.I): return val   # patterns may carry capitals (EST, FINRA, QPS): match case-insensitively
    return None
LABEL_JS=r"""
(el)=>{let t='';
 const byId=(id)=>{const l=document.querySelector('label[for="'+CSS.escape(id)+'"]'); return l? l.innerText:'';};
 const byLabelledBy=(e)=>{const a=e.getAttribute('aria-labelledby'); if(!a) return ''; return a.split(/\s+/).map(i=>{const x=document.getElementById(i); return x? x.innerText:'';}).join(' ');};
 if(el.id) t=byId(el.id);
 if(!t){const l=el.closest('label'); if(l) t=l.innerText;}
 if(!t && el.getAttribute('aria-label')) t=el.getAttribute('aria-label');
 if(!t) t=byLabelledBy(el);
 if(!t){const inp=el.querySelector('input[aria-labelledby], input[id], select[id]'); if(inp){ t=byLabelledBy(inp) || (inp.id? byId(inp.id):''); }}
 if(!t){const fs=el.closest('fieldset'); if(fs){const lg=fs.querySelector('legend'); if(lg) t=lg.innerText;}}
 if(!t){let p=el.parentElement; for(let i=0;i<6&&p;i++){
    let lab=null; for(const c of p.querySelectorAll('label, legend')){ if(!c.contains(el) && !el.contains(c) && c.innerText.trim()){lab=c; break;} }
    if(!lab){ for(const c of p.querySelectorAll('.application-label, [class*="label"], [class*="Label"], h3, h4, .field-label, .question')){ if(c!==el && !c.contains(el) && !el.contains(c) && c.innerText.trim() && !/^select\.\.\.$/i.test(c.innerText.trim())){lab=c; break;} } }
    if(lab){t=lab.innerText; break;} p=p.parentElement;}}
 if(!t){let p=el; for(let i=0;i<4&&p;i++){const prev=p.previousElementSibling; if(prev){const s=(prev.innerText||'').trim(); if(s.length>3&&s.length<220&&!/^(select|-|—)/i.test(s)){t=s; break;}} p=p.parentElement;}}
 return (t||'').trim().replace(/\s+/g,' ').replace(/[✱*]/g,'').trim();}
"""
STILL_VISIBLE_JS=r"""(lab)=>{lab=lab.toLowerCase().replace(/\s+/g,' ').slice(0,45); if(lab.length<4) return true;
 for(const e of document.querySelectorAll('label,legend,div,span,p,h3,h4')){ const t=(e.innerText||'').toLowerCase().replace(/\s+/g,' '); if(t.length>400||!t.startsWith(lab)) continue; const r=e.getBoundingClientRect(); if(r.width>0&&r.height>0) return true; }
 return false;}"""
async def label_of(h): return await h.evaluate(LABEL_JS)
async def is_required(h):
    return await h.evaluate("(el)=>el.required||el.getAttribute('aria-required')==='true'||/\\*|✱|required/i.test((el.closest('label,fieldset,div')||{}).innerText||'')")
async def fill_text(page,h,val):
    try:
        await h.scroll_into_view_if_needed(timeout=3000)
        await h.click(timeout=3000); await h.fill(val)
        await h.dispatch_event("input"); await h.dispatch_event("change"); await h.press("Tab"); return True
    except Exception:
        try: await h.click(timeout=3000); await h.type(val,delay=10); await h.press("Tab"); return True
        except Exception: return False
async def autocomplete_fill(page,h,text,prefer):
    """Type into an autocomplete box and pick the first matching suggestion."""
    try:
        await h.scroll_into_view_if_needed(timeout=3000); await h.click(timeout=3000); await h.fill("")
        await h.type(text,delay=40); await page.wait_for_timeout(1800)
        opts=page.locator('[role="option"]:visible:not(.iti__country), [role="listbox"] li:visible, [class*="dropdown"] li:visible, [class*="option"]:visible, [class*="Option"]:visible, [class*="suggestion"]:visible')
        n=await opts.count()
        for i in range(min(n,30)):
            o=opts.nth(i)
            try:
                if await o.is_visible() and re.search(prefer,await o.inner_text(),re.I): await o.click(timeout=3000); await page.wait_for_timeout(500); return "picked"
            except Exception: pass
        for i in range(min(n,30)):
            o=opts.nth(i)
            try:
                if await o.is_visible(): await o.click(timeout=3000); await page.wait_for_timeout(500); return "picked-first"
            except Exception: pass
        if n: await h.press("ArrowDown"); await h.press("Enter"); await page.wait_for_timeout(500); return "enter"
        await dismiss_menu(page,h); return None   # no suggestions: Enter here would submit the form
    except Exception: return None
async def choose_select(page,h,options_pref):
    opts=await h.evaluate("(s)=>[...s.options].map(o=>o.text.trim())")
    for pref in options_pref:
        for o in opts:
            if o and (o.lower()==pref.lower() or pref.lower() in o.lower()):
                try:
                    if await h.is_visible(): await h.select_option(label=o)
                    else: raise RuntimeError("hidden")
                    return o
                except Exception:
                    try:
                        await h.evaluate("(s,label)=>{for(const op of s.options){if(op.text.trim()===label){s.value=op.value; op.selected=true;}} s.dispatchEvent(new Event('input',{bubbles:true})); s.dispatchEvent(new Event('change',{bubbles:true})); if(window.jQuery){try{window.jQuery(s).trigger('change');}catch(e){}}}",o)
                        return o
                    except Exception: pass
    return None
def set_email(em):
    """Switch the applicant email for the next application (profile value + the e-mail text rule)."""
    P["email"]=em
    for i,(pat,val) in enumerate(TEXT_RULES):
        if pat==r"e-?mail": TEXT_RULES[i]=(pat,em)
CUR_ATS=None   # set per job by run_one: some behaviours depend on the host site
# work environments the applicant has managed in (startups Hyperion AI/Motocho/Ankr, product companies Yahoo Finance/Bloomberg, banks JPMC/Morgan Stanley/Barclays, Cadence)
ENV_TRUE=r"start-?up|scale-?up|product-led|ambiguous|evolving|roadmap|enterprise|established processes|remote|distributed|hybrid|cross-functional|global|regulated|fintech|financ|b2b|saas|platform|\bai\b|\bml\b|cloud|high-growth|fast-moving|early-stage|growth-stage|public company|series [a-f]"
# option statements that are true for the applicant (Santa Clara, CA; hybrid in SF Bay Area fine; open to relocation elsewhere)
OPTION_TRUE=r"(currently )?(live|based|located|reside) in (the )?(sf |san francisco |greater )?bay area|santa clara|(live|based|located|reside) in (the )?(san francisco|silicon valley|california)|comfortable with a hybrid position commuting to the (san francisco|sf) office"
async def dismiss_menu(page,inp=None):
    """Close an open dropdown/autocomplete menu. Blur first: on Wellfound the Escape key closes the whole apply modal."""
    try:
        if inp is not None: await inp.evaluate("el=>el.blur()")
    except Exception: pass
    await page.wait_for_timeout(250)
    if CUR_ATS!="wellfound":
        try: await page.keyboard.press("Escape")
        except Exception: pass
async def tick(h):
    """Check a checkbox/radio; custom-styled inputs are hidden, so fall back to clicking their label or setting the state directly."""
    try: await h.check(timeout=3000); return True
    except Exception:
        await h.evaluate("(el)=>{const l=el.id&&document.querySelector('label[for=\"'+CSS.escape(el.id)+'\"]'); if(l) l.click(); else {el.click();} if(!el.checked){el.checked=true; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true}));}}")
        return True
async def body_text(page):
    """document.body.innerText, tolerant of a navigation landing mid-call (e.g. Greenhouse jumping to /confirmation)."""
    for i in range(3):
        try: return await page.evaluate("()=>document.body.innerText")
        except Exception:
            if i==2: raise
            await page.wait_for_timeout(2500)
OPT_SEL='[role="option"]:visible:not(.iti__country), [class*="select__option"]:visible, [class*="Select__option"]:visible'
async def visible_options(page):
    o=page.locator(OPT_SEL); n=await o.count(); t=[]
    for i in range(min(n,60)):
        try: t.append((await o.nth(i).inner_text()).strip())
        except Exception: t.append("")
    return o,t
def _match(t,pref,strict=False):
    """Option text t satisfies preference pref: equal, or pref is a leading/whole-word phrase of t ('Male' never matches 'Female'). strict: equal/leading only."""
    tl,pl=t.lower().strip(),pref.lower().strip()
    if not tl or not pl: return False
    if tl==pl or re.match(re.escape(pl)+r"($|[\s,./:;()\-'])",tl): return True
    if strict: return False
    return len(pl)>=3 and re.search(r"(^|[^a-z0-9])"+re.escape(pl)+r"($|[^a-z0-9])",tl) is not None
def best_index(texts,pref):
    """Index of the option best matching pref: an exact/leading match beats a whole-word one ('San Francisco Bay Area' over 'Other - willing to relocate to the San Francisco Bay Area')."""
    for strict in (True,False):
        for i,t in enumerate(texts):
            if t and _match(t,pref,strict): return i
    return None
async def open_menu(control,inp):
    """Focus a react-select: click its input, or the control when the placeholder overlays the input (Wellfound)."""
    try: await inp.click(timeout=2000)
    except Exception:
        try: await control.click(timeout=3000)
        except Exception: await inp.focus()
async def choose_react_select(page,control,options_pref,label):
    """react-select: type the preferred answer into the inner input, pick the visible matching option (or Enter), verify."""
    if options_pref==["__ASK__"]: return None
    inp=control.locator('input[role="combobox"], input.select__input, input').first
    if not await inp.count(): return None
    async def current():
        try: return (await control.inner_text()).strip()
        except Exception: return ""
    try:
        for pref in options_pref[:4]:
            await inp.scroll_into_view_if_needed(timeout=3000); await open_menu(control,inp)
            await inp.press("Control+A"); await inp.press("Backspace"); await page.wait_for_timeout(200)
            await inp.type(pref[:30],delay=25); await page.wait_for_timeout(900)
            opts,texts=await visible_options(page)
            hit=best_index(texts,pref)
            if hit is None and texts:
                # no textual match: maybe options are unfiltered (async search); pick none
                pass
            if hit is None:   # never press Enter here: with no menu match it submits the whole form
                await inp.press("Control+A"); await inp.press("Backspace"); await dismiss_menu(page,inp); continue
            await opts.nth(hit).click(timeout=3000)
            await page.wait_for_timeout(500)
            cur=await current()
            if cur and cur.lower()!="select..." and (pref.lower()[:6] in cur.lower() or (hit is not None)): return cur[:80]
            # not selected: clear and try next preference
            await inp.press("Control+A"); await inp.press("Backspace"); await dismiss_menu(page,inp)
        # fallback: open the whole menu and scan every option against every preference (handles long option texts)
        await open_menu(control,inp); await page.wait_for_timeout(700)
        opts,texts=await visible_options(page)
        if not texts:
            await inp.press("ArrowDown"); await page.wait_for_timeout(700); opts,texts=await visible_options(page)
        LAST_OPTIONS[label[:160]]=[t for t in texts if t][:25]
        for pref in options_pref:
            i=best_index(texts,pref)
            if i is not None:
                await opts.nth(i).click(timeout=3000); await page.wait_for_timeout(500)
                cur=await current()
                if cur and cur.lower()!="select...": return cur[:80]
        real=[i for i,t in enumerate(texts) if t and not re.search(r"^no options",t,re.I)]
        if len(real)==1:   # a single-option dropdown ("I agree", "Confirmed", ...) is an acknowledgment: take it
            await opts.nth(real[0]).click(timeout=3000); await page.wait_for_timeout(500)
            cur=await current()
            if cur and cur.lower()!="select...": return cur[:80]
        await dismiss_menu(page,inp)
    except Exception:
        try: await dismiss_menu(page,inp)
        except Exception: pass
    return None
def fetch_email_code(max_wait=150):
    """Return the latest 8-character verification code from the inbox configured in wf_creds.json {"imap":{"host","user","password"}}
    (Gmail: imap.gmail.com + an app password). Falls back to a terminal prompt when running interactively."""
    creds_path=os.path.join(JOBS_DIR,"wf_creds.json")
    cfg=(json.load(open(creds_path)).get("imap") if os.path.exists(creds_path) else None)
    if cfg:
        import imaplib, email, datetime
        deadline=time.time()+max_wait
        while time.time()<deadline:
            try:
                M=imaplib.IMAP4_SSL(cfg.get("host","imap.gmail.com")); M.login(cfg["user"],cfg["password"]); M.select("INBOX")
                since=(datetime.datetime.utcnow()-datetime.timedelta(days=1)).strftime("%d-%b-%Y")
                typ,data=M.search(None,f'(SINCE {since})'); ids=data[0].split()[-15:]
                best=None
                for i in reversed(ids):
                    typ,msg=M.fetch(i,"(RFC822)"); m=email.message_from_bytes(msg[0][1])
                    subj=str(m.get("Subject","")); body=""
                    for part in (m.walk() if m.is_multipart() else [m]):
                        if part.get_content_type() in ("text/plain","text/html"):
                            try: body+=part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8","ignore")
                            except Exception: pass
                    txt=re.sub(r"<[^>]+>"," ",subj+" "+body)
                    if re.search(r"verification code|security code|confirm you.re a human|application code",txt,re.I):
                        d=email.utils.parsedate_to_datetime(m.get("Date")) if m.get("Date") else None
                        if d and (datetime.datetime.now(d.tzinfo)-d).total_seconds()>900: continue   # older than 15 min
                        c=re.search(r"\b([A-Z0-9]{8})\b",txt)
                        if c: best=c.group(1); break
                M.logout()
                if best: return best
            except Exception as e: print("imap:",str(e)[:120])
            time.sleep(10)
        return None
    if sys.stdin.isatty():
        try: return input("Enter the 8-character verification code emailed to you (blank to skip): ").strip() or None
        except Exception: return None
    return None
BROWSER=None; OUTLOOK={"page":None}
def outlook_cfg():
    p=os.path.join(JOBS_DIR,"wf_creds.json")
    if not os.path.exists(p): return None
    c=json.load(open(p)).get("outlook")
    return c if c and c.get("email") and c.get("password") else None
CODE_RE=re.compile(r"\b([A-Z0-9]{8})\b")
def _codes_in(text):
    out=[]
    for m in re.finditer(r"code[^A-Za-z0-9]{0,120}([A-Za-z0-9]{8})\b",text,re.I|re.S): out.append(m.group(1))
    for m in CODE_RE.finditer(text): out.append(m.group(1))
    return [c for c in out if re.search(r"\d",c)] or out
async def outlook_page():
    """Open (once) a logged-in Outlook.com tab in its own browser context; reuse it for every code lookup."""
    if OUTLOOK["page"] and not OUTLOOK["page"].is_closed(): return OUTLOOK["page"]
    cfg=outlook_cfg()
    if not cfg or BROWSER is None: return None
    state=os.path.join(JOBS_DIR,"outlook_state.json")
    ctx=await BROWSER.new_context(ignore_https_errors=True,user_agent=UA,viewport={"width":1280,"height":900},storage_state=state if os.path.exists(state) else None)
    ctx.set_default_timeout(8000); page=await ctx.new_page()
    await page.goto("https://outlook.live.com/mail/0/",wait_until="domcontentloaded",timeout=60000); await page.wait_for_timeout(5000)
    for _ in range(6):
        if "outlook.live.com/mail" in page.url and await page.locator('[role="main"], #app, [aria-label="Search"]').count(): break
        try:
            e=page.locator('input[name="loginfmt"], input[type="email"]').first
            if await e.count() and await e.is_visible(): await e.fill(cfg["email"]); await page.locator('#idSIButton9, button[type="submit"]').first.click(timeout=4000); await page.wait_for_timeout(3000)
            for sel in ['button:has-text("Use your password")','a:has-text("Use your password")','a:has-text("Other ways to sign in")']:
                el=page.locator(sel).first
                if await el.count() and await el.is_visible(): await el.click(timeout=3000); await page.wait_for_timeout(2000)
            pw=page.locator('input[name="passwd"], input[type="password"]').first
            if await pw.count() and await pw.is_visible(): await pw.fill(cfg["password"]); await page.locator('#idSIButton9, button[type="submit"]').first.click(timeout=4000); await page.wait_for_timeout(5000)
            for sel in ['#idSIButton9','button:has-text("Yes")','button:has-text("Skip for now")','a:has-text("Skip for now")','button:has-text("Not now")','#iCancel','button:has-text("Cancel")','#iNext','button:has-text("Maybe later")']:
                el=page.locator(sel).first
                if await el.count() and await el.is_visible(): await el.click(timeout=3000); await page.wait_for_timeout(3000)
        except Exception: pass
        await page.wait_for_timeout(2000)
    if "outlook.live.com/mail" not in page.url:
        print("outlook: login did not complete (2-step verification or a sign-in challenge?); falling back to manual code entry")
        await page.screenshot(path=f"{OUT}/outlook_login_problem.png"); return None
    try: await ctx.storage_state(path=state)
    except Exception: pass
    OUTLOOK["page"]=page; return page
async def outlook_codes(page,query="verification code"):
    """Codes found in the newest few messages matching the search, newest first."""
    found=[]
    try:
        sb=page.locator('input[aria-label="Search"], #topSearchInput, input[placeholder*="Search"]').first
        await sb.click(timeout=5000); await sb.fill(""); await sb.type(query,delay=20); await sb.press("Enter"); await page.wait_for_timeout(4500)
        items=page.locator('[role="listbox"] [role="option"], div[data-convid]'); n=await items.count()
        for i in range(min(n,4)):
            try:
                await items.nth(i).click(timeout=4000); await page.wait_for_timeout(2500)
                body=await page.evaluate("()=>{const r=document.querySelector('[aria-label=\"Message body\"], #UniqueMessageBody, [role=\"document\"], .allowTextSelection'); return (r? r.innerText : document.body.innerText).slice(0,6000)}")
                found+=_codes_in(body)
            except Exception: pass
    except Exception as e: print("outlook search:",str(e)[:100])
    return found
async def code_from_file(report,max_wait=None):
    """Hand-off for whoever can read the mailbox (the applicant, or Claude with the Gmail connector): write
    out/<tag>_code_request.json, then poll out/<tag>_code.txt for the 8-character code."""
    tag=report["tag"]; req=f"{OUT}/{tag}_code_request.json"; ans=f"{OUT}/{tag}_code.txt"
    if os.path.exists(ans): os.remove(ans)
    json.dump({"tag":tag,"email":P["email"],"url":report.get("url"),"ts":time.time()},open(req,"w"))
    print(f"CODE REQUEST {tag}",flush=True)
    deadline=time.time()+(max_wait or CODE_WAIT)
    while time.time()<deadline:
        if os.path.exists(ans):
            c=re.sub(r"[^A-Za-z0-9]","",open(ans).read())   # Greenhouse codes are mixed-case: keep them exactly as sent
            if len(c)>=6: report["code_source"]="file"; return c
        await asyncio.sleep(3)
    return None
async def enter_email_code(page,report,baseline=()):
    boxes=page.locator('input[autocomplete="one-time-code"], input[name*="security_code"], input[id*="security_code"], input[name*="verification"], [class*="security-code"] input, [class*="securityCode"] input, [class*="otp"] input')
    n=await boxes.count()
    if not n:   # Greenhouse job-boards: eight single-character boxes right after the "Security code" label
        boxes=page.locator('input[maxlength="1"]:visible'); n=await boxes.count()
    if not n:
        boxes=page.locator('xpath=//*[contains(normalize-space(text()),"ecurity code")]/following::input[not(@type="hidden") and not(@type="file") and not(@type="checkbox")][position()<=8]'); n=await boxes.count()
    if not n:
        try: report["security_code_html"]=await page.evaluate("()=>{const e=[...document.querySelectorAll('label,div,span,p,legend')].find(x=>/security code/i.test(x.innerText||'')&&x.innerText.length<60); return e? (e.parentElement||e).outerHTML.slice(0,1500):''}")
        except Exception: pass
        return False
    code=None; report["code_required"]=True
    op=await outlook_page()
    if op:
        deadline=time.time()+180
        while time.time()<deadline and not code:
            for c in await outlook_codes(op):
                if c not in baseline: code=c; break
            if not code: await asyncio.sleep(12)
        report["code_source"]="outlook"
    if not code: code=await asyncio.get_event_loop().run_in_executor(None,fetch_email_code)
    if not code: code=await code_from_file(report)
    if not code: report.setdefault("errors",[]).append("email verification code required (configure imap in wf_creds.json, run interactively, or write it to out/<tag>_code.txt)"); return False
    try:
        if n>=8:
            for i,ch in enumerate(code[:n]): await boxes.nth(i).fill(ch)
        else: await boxes.first.fill(code)
        report["code_entered"]=True; return True
    except Exception as e: report.setdefault("errors",[]).append(f"code entry failed: {e}"); return False
GENERIC_TOKENS={"the","ai","san","new","open","one","first","next","big","blue","red","green","smart","data","cloud","tech","labs","lab","inc","co","company","team","global","digital","alpha","beta","meta","x","a","an","of","and"}
def company_keys(tag,company=None):
    toks=[t for t in (tag or "").split("_") if t]
    ks=set()
    if company: ks.add(re.sub(r"[^a-z0-9]","",str(company).lower()))
    if toks and len(toks[0])>=5 and toks[0] not in GENERIC_TOKENS: ks.add(toks[0])
    if len(toks)>1: ks.add(toks[0]+toks[1])
    return {k for k in ks if len(k)>=4}
def applied_elsewhere(tag,company=None,days=45):
    """Return the tag of an earlier submitted application at the same company (any ATS, last `days` days), else None."""
    import glob as _glob
    ks=company_keys(tag,company)
    if not ks: return None
    cutoff=time.time()-days*86400
    for f in _glob.glob(f"{OUT}/*_report.json"):
        if os.path.basename(f)==f"{tag}_report.json" or os.path.getmtime(f)<cutoff: continue
        try: r=json.load(open(f))
        except Exception: continue
        if not r.get("submitted") or "ALREADY APPLIED" in (r.get("result") or ""): continue
        ks2=company_keys(r.get("tag"),r.get("company"))
        if ks & ks2: return r.get("tag")
        # 'doordashusa' vs 'doordash', 'acmeinc' vs 'acme': a key that is a prefix of the other (6+ chars) is the same company
        if any(a.startswith(b) or b.startswith(a) for a in ks for b in ks2 if min(len(a),len(b))>=6): return r.get("tag")
    return None
async def run():
    async with async_playwright() as p:
        launch_kw=dict(headless=not HEADED,args=["--no-sandbox","--ignore-certificate-errors"])
        if os.path.exists("/opt/pw-browsers/chromium"): launch_kw["executable_path"]="/opt/pw-browsers/chromium"   # cloud container
        b=await p.chromium.launch(**launch_kw)
        global BROWSER; BROWSER=b
        if sys.argv[1]=="outlook-test":
            op=await outlook_page()
            print("outlook login:", "ok" if op else "FAILED")
            if op:
                codes=await outlook_codes(op); print("codes found (newest first):",codes[:6])
                await op.screenshot(path=f"{OUT}/outlook_test.png")
            await b.close(); return
        jobs = JOBS if BATCH else [{"ats":ats,"url":url,"tag":tag,"answers":extra}]
        summary=[]; default_email=P["email"]
        for job in jobs:
            set_email(job.get("email") or default_email)   # a batch entry may name the applicant email to use (rotation across the applicant's addresses)
            prior=applied_elsewhere(job["tag"],job.get("company"))   # one application per company across every stream and site
            if prior:
                r={"ats":job["ats"],"url":job["url"],"tag":job["tag"],"submitted":False,"result":f"NOT SUBMITTED: ALREADY APPLIED at this company today ({prior})","unanswered":[],"errors":[]}
                json.dump(r,open(f"{OUT}/{job['tag']}_report.json","w"),indent=1)
                summary.append(r); print(json.dumps(r),flush=True); continue
            ctx=await b.new_context(ignore_https_errors=True,user_agent=UA,viewport={"width":1280,"height":2000},locale="en-US",timezone_id="America/Los_Angeles")
            ctx.set_default_timeout(8000)
            r=await run_one(ctx,job["ats"],job["url"],job["tag"],job.get("answers",{}),job.get("company"),job.get("title"))
            summary.append({k:r.get(k) for k in ("tag","ats","url","submitted","result","unanswered","captcha_present","errors","code_required","code_source")})
            print(json.dumps(summary[-1]),flush=True)
            await ctx.close()
            if PACE and job is not jobs[-1]:
                import random; gap=random.uniform(*PACE)
                if not r.get("submitted") and re.search(r"location restricted|in-office NYC|job closed|managed outside|ALREADY APPLIED",r.get("result") or ""): gap=min(gap,20)   # nothing was submitted: no need for the full human-paced gap
                print(f"PACE waiting {int(gap)}s before the next application",flush=True); await asyncio.sleep(gap)
        json.dump(summary,open(f"{OUT}/batch_summary_{int(time.time())}.json","w"),indent=1)
        await b.close()
async def run_one(ctx,ats,url,tag,extra,company=None,jtitle=None):
    global CUR_ATS
    CUR_ATS=ats
    if True:
        page=await ctx.new_page(); report={"ats":ats,"url":url,"tag":tag,"filled":{},"chosen":{},"unanswered":[],"submitted":False,"result":""}
        cl_text=""; cl_pdf=None
        try:
            if ats=="wellfound":
                C=json.load(open(os.path.join(JOBS_DIR,"wf_creds.json")))
                await page.goto("https://wellfound.com/login",wait_until="domcontentloaded",timeout=60000); await page.wait_for_timeout(2500)
                await page.fill('input[type="email"]',C["email"]); await page.fill('input[type="password"]',C["password"])
                await page.locator('button[type="submit"], input[type="submit"]').first.click(timeout=10000); await page.wait_for_timeout(5000)
                await page.goto(url,wait_until="domcontentloaded",timeout=60000); await page.wait_for_timeout(4000)
                if await page.locator('button:has-text("Applied")').count():
                    report["submitted"]=True; report["result"]="ALREADY APPLIED (Wellfound shows this job as Applied)"; report["note"]="already applied earlier"
                    json.dump(report,open(f"{OUT}/{tag}_report.json","w"),indent=1); await page.close(); return report
                pre=await body_text(page)
                if re.search(r"job listing is no longer available|no longer available|this job is closed|position has been filled|no longer accepting applications|Page not found \(404\)|Oops! Page not found",pre,re.I):
                    report["result"]="NOT SUBMITTED: job closed (listing no longer available)"
                    json.dump(report,open(f"{OUT}/{tag}_report.json","w"),indent=1); await page.close(); return report
                report["recruiter_active"]=bool(re.search(r"RECRUITER RECENTLY ACTIVE",pre))
                m=re.search(r"POSTED (TODAY|YESTERDAY|(\d+) (DAY|DAYS|WEEK|WEEKS|MONTH|MONTHS) AGO)",pre)
                if m:
                    age=0 if m.group(1)=="TODAY" else 1 if m.group(1)=="YESTERDAY" else int(m.group(2))*(1 if m.group(3).startswith("DAY") else 7 if m.group(3).startswith("WEEK") else 30)
                    report["posted_days_ago"]=age
                    if age>int(os.environ.get("WF_MAX_AGE_DAYS","30")):   # freshness first: skip stale listings
                        report["result"]=f"NOT SUBMITTED: job closed / stale listing (posted {age} days ago)"
                        json.dump(report,open(f"{OUT}/{tag}_report.json","w"),indent=1); await page.close(); return report
                await page.locator('button:has-text("Apply Now"), button:has-text("Apply now"), button:has-text("Apply")').first.click(timeout=10000); await page.wait_for_timeout(3500)
                wf_body=await body_text(page)
                if re.search(r"not accepting applications from your current location|no longer accepting applications|this job is closed|position has been filled",wf_body,re.I):
                    report["result"]="NOT SUBMITTED: "+("location restricted by employer" if "current location" in wf_body else "job closed")
                    json.dump(report,open(f"{OUT}/{tag}_report.json","w"),indent=1); await page.close(); return report
                # work-mode rule: remote anywhere in the US and Bay Area hybrid are fine; NYC only hybrid; no Chicago on-site
                pol=re.search(r"Remote work policy\s*\|?\s*(In office|Onsite or remote|Remote only|Hybrid)",wf_body,re.I)
                locm=re.search(r"\nLocation\s*\n\s*([^\n]+)",wf_body)
                locs=((locm.group(1) if locm else "")+" "+(jtitle or ""))
                report["work_policy"]=pol.group(1) if pol else None; report["listing_location"]=locm.group(1)[:80] if locm else None
                if not os.environ.get("WF_ALLOW_ONSITE") and pol and pol.group(1).lower()=="in office" and re.search(r"New York|NYC|Brooklyn|Manhattan|Chicago",locs,re.I) and not re.search(r"San Francisco|Bay Area|Palo Alto|Menlo Park|Mountain View|Sunnyvale|San Jose|Santa Clara|Redwood City|San Mateo|Oakland|Berkeley",locs,re.I) and not re.search(r"hybrid",wf_body,re.I):
                    report["result"]="NOT SUBMITTED: in-office NYC/Chicago listing (no hybrid mentioned)"; report["skipped"]="work-mode rule"
                    json.dump(report,open(f"{OUT}/{tag}_report.json","w"),indent=1); await page.close(); return report
                ta=page.locator('textarea:not([disabled])').first   # a disabled conditional-question box can come first
                if await ta.count():
                    note=extra.get("note") or ANS.get("why_us","")
                    first=None
                    try:   # the note is the message the hiring contact (often the founder) receives with the application: address them by name
                        hc=re.search(r"Your hiring contact is ([A-Z][\w.'-]+(?: [A-Z][\w.'-]+){0,3})",await body_text(page))
                        first=hc.group(1).split()[0] if hc else None
                    except Exception: pass
                    if jtitle and company: note=(f"Hi {first}, " if first else "Hi, ")+f"I'm applying for the {jtitle} role at {company}. "+note
                    await ta.fill(note,timeout=15000); report["filled"]["note"]="ok"; report["hiring_contact"]=first
                if not await page.locator('button:has-text("Send application")').count():
                    ext=page.locator('a:has-text("Apply on website"), a:has-text("Apply on company website")').first
                    href=(await ext.get_attribute("href")) if await ext.count() else None
                    if not href:   # Wellfound renders it as a button that opens the company's ATS in a new tab (or redirects this one)
                        btn=page.locator('button:has-text("Apply on website"), button:has-text("Apply on company website")').first
                        if await btn.count():
                            try:
                                async with page.context.expect_page(timeout=15000) as pinfo: await btn.click(timeout=5000)
                                newp=await pinfo.value
                                try: await newp.wait_for_load_state("domcontentloaded",timeout=20000)
                                except Exception: pass
                                href=newp.url; await newp.close()
                            except Exception:
                                await page.wait_for_timeout(5000)
                                others=[pp for pp in page.context.pages if pp is not page and "wellfound.com" not in pp.url]
                                if others: href=others[0].url; [await pp.close() for pp in others]
                                elif "wellfound.com" not in page.url: href=page.url
                            if href and "wellfound.com" in href: href=None
                    if href and re.search(r"greenhouse\.io|gh_jid=",href):
                        # Wellfound hands off to the company's Greenhouse form: apply there (same code flow as any Greenhouse job)
                        report["external"]=href; ats="greenhouse"; url=href; report["ats"]="greenhouse (via Wellfound)"
                    else:
                        report["result"]=f"NOT SUBMITTED: managed outside Wellfound ({href or 'no apply form'})"; report["external"]=href
                        await page.screenshot(path=f"{OUT}/{tag}_error.png",full_page=True); json.dump(report,open(f"{OUT}/{tag}_report.json","w"),indent=1); await page.close(); return report
                # the modal often carries the employer's own required questions: fall through to the generic filler below
            if ats=="greenhouse":
                m=re.search(r"greenhouse\.io/([^/]+)/jobs/(\d+)",url)
                if m: url=f"https://job-boards.greenhouse.io/embed/job_app?for={m.group(1)}&token={m.group(2)}"
                elif re.search(r"gh_jid=(\d+)",url) and company:   # company site hosting a Greenhouse job (nuro.ai/careersitem?gh_jid=...): the board is the company slug
                    board=re.sub(r"[^a-z0-9]","",company.lower()); token=re.search(r"gh_jid=(\d+)",url).group(1)
                    url=f"https://job-boards.greenhouse.io/embed/job_app?for={board}&token={token}"
            if ats!="wellfound":
                for attempt in range(3):   # transient proxy/network errors ("upstream request failed", 502/503): reload after a pause
                    await page.goto(url,wait_until="domcontentloaded",timeout=60000); await page.wait_for_timeout(3500)
                    if not re.search(r"^\s*upstream request failed|Error\s+50[234]\b|50[234]\s+(Bad Gateway|Service|Gateway)|lost in the weeds|ERR_|This site can.t be reached",await body_text(page),re.I): break
                    await page.wait_for_timeout(8000)
            for sel in ['button:has-text("Accept All")','button:has-text("Accept all")','button:has-text("Accept")','button:has-text("I agree")','button:has-text("Got it")','button:has-text("Decline All")']:
                try:
                    el=page.locator(sel).first
                    if await el.count() and await el.is_visible(): await el.click(timeout=2000); await page.wait_for_timeout(500); break
                except Exception: pass
            if ats=="ashby" and "/application" not in page.url:
                for sel in ['a:has-text("Apply for this Job")','a:has-text("Apply")','button:has-text("Apply")']:
                    try:
                        el=page.locator(sel).first
                        if await el.count(): await el.click(timeout=4000); await page.wait_for_timeout(3000); break
                    except Exception: pass
            if ats=="greenhouse":
                for sel in ['a:has-text("Apply")','button:has-text("Apply")','#apply_button']:
                    try:
                        el=page.locator(sel).first
                        if await el.count() and not await page.locator('input[type="file"]').count(): await el.click(timeout=4000); await page.wait_for_timeout(2500); break
                    except Exception: pass
            # cover letter: the applicant's own PDF (profile.json "cover_letter") when present, else a per-posting one
            if CL_OWN and P.get("cover_letter") and os.path.exists(P["cover_letter"]):
                cl_text=CL_OWN; cl_pdf=P["cover_letter"]; report["cover_source"]="applicant"
            else:
                try:
                    ptitle=jtitle or re.sub(r"\s*[|@\-–].*$","",await page.title())
                    pdesc=await page.evaluate("()=>document.body.innerText.slice(0,6000)")
                    comp=company or re.sub(r"[-_]"," ",url.split("/")[3]).title()
                    cl_text=cover.text(comp,ptitle,pdesc,P); cl_pdf=cover.pdf(f"{OUT}/{tag}_cover.pdf",cl_text); report["cover_category"]=cover.category(ptitle,pdesc)
                except Exception as e: report["cover_err"]=str(e)[:100]; cl_pdf=P.get("cover_letter")
            # resume upload first (autofill may follow), then the cover letter
            async def file_labels():
                fl=page.locator('input[type="file"]'); out=[]
                for i in range(await fl.count()):
                    try: out.append((await label_of(fl.nth(i))).lower())
                    except Exception: out.append("")
                return fl,out
            files,labs=await file_labels()
            ri=next((i for i,l in enumerate(labs) if re.search(r"resume|cv",l)),0 if labs else None)
            if ri is not None:
                try: await files.nth(ri).set_input_files(P["resume"],timeout=15000); report["filled"]["resume"]="uploaded"
                except Exception as e: report["filled"]["resume"]=f"ERR {e.__class__.__name__}"
            await page.wait_for_timeout(5000)
            for _ in range(25):
                if not await page.locator('text=/Analyzing resume|Uploading|Parsing/i').count(): break
                await page.wait_for_timeout(1000)
            cl_file=cl_pdf or P.get("cover_letter")
            if cl_file and os.path.exists(cl_file):
                files,labs=await file_labels()   # re-query: the form re-renders after the resume is parsed
                ci=next((i for i,l in enumerate(labs) if re.search(r"cover",l)),None)
                if ci is None and len(labs)>=2: ci=1 if ri!=1 else 0
                got=False
                if ci is not None:
                    try: await files.nth(ci).set_input_files(cl_file,timeout=15000); got=True
                    except Exception as e: report["filled"]["cover_letter"]=f"ERR {e.__class__.__name__}"
                if not got:
                    # Greenhouse job-boards: the "Attach" button under the "Cover Letter" heading opens a file chooser
                    try:
                        btn=page.locator('xpath=//*[normalize-space(text())="Cover Letter" or normalize-space(text())="Cover letter"]/following::button[contains(.,"Attach")][1]').first
                        if await btn.count():
                            async with page.expect_file_chooser(timeout=6000) as fc:
                                await btn.click(timeout=4000)
                            await (await fc.value).set_files(cl_file); got=True
                    except Exception as e: report["filled"]["cover_letter"]=f"ERR chooser {e.__class__.__name__}"
                if got: report["filled"]["cover_letter"]="uploaded"; await page.wait_for_timeout(2500)
            # text inputs / textareas
            ctrls=page.locator('input[type="text"], input[type="email"], input[type="tel"], input[type="url"], input[type="number"], input:not([type]), textarea')
            n=await ctrls.count()
            for i in range(n):
                h=ctrls.nth(i)
                try:
                    if not await h.is_visible(): continue
                    name=await h.get_attribute("name") or ""; lab=await label_of(h)
                    if re.search(r"captcha|search",name+lab,re.I): continue
                    ph=(await h.get_attribute("placeholder") or "")
                    if lab.strip().lower() in ("select...","select") or re.search(r"select2",(await h.get_attribute("class")) or ""): continue
                    if await h.evaluate("(el)=>el.getAttribute('aria-autocomplete')==='list'||el.getAttribute('role')==='combobox'||/select__input|react-select|requiredInput/i.test(el.className+' '+el.id)||!!el.closest('[class*=select__control],[class*=Select__control]')||!!(el.parentElement&&el.parentElement.querySelector('[class*=select__control],[class*=Select__control]'))"): continue   # dropdowns are handled below
                    if re.search(r"^(current |your )?location( \(city\))?$|^city$|^where are you (based|located)",lab,re.I) or (ats=="lever" and name=="location") or (re.search(r"start typing",ph,re.I) and re.search(r"location|city",lab,re.I)):
                        if not (await h.input_value()).strip():
                            got=await autocomplete_fill(page,h,"Santa Clara, California",r"santa clara")
                            report["filled"][lab[:60] or name]=f"autocomplete:{got}"
                        continue
                    if re.search(r"ai policy|use of ai|ai assistance|ai tools? (in|during)|without (the use of )?ai",lab,re.I): report["unanswered"].append({"type":"text","label":lab[:160],"name":name,"note":"AI-use question left for user"}); continue
                    key=lab or name
                    val=None
                    for k,v in extra.items():
                        if k.lower() in (name+" "+lab).lower(): val=v; break
                    if val is None: val=pick(key,TEXT_RULES)
                    if val=="Company careers page" and "wellfound" in (ats or "").lower(): val="Wellfound"   # applying through Wellfound: say so
                    if re.search(r"cover letter",lab,re.I) and cl_text: val=cl_text
                    if ats=="lever" and re.search(r"^location$",name): val=P["location"]
                    if val is None and (await h.get_attribute("placeholder") or ""): val=pick(await h.get_attribute("placeholder"),TEXT_RULES)
                    cur=await h.input_value()
                    if cur.strip() and await h.evaluate("(el)=>el.tagName==='TEXTAREA'") and not re.search(r"cover letter",lab,re.I): continue   # keep a note already written (e.g. Wellfound)
                    if val:
                        if cur.strip()!=val: await fill_text(page,h,val)
                        report["filled"][key[:60]]=val[:40]
                    elif not cur.strip() and await is_required(h): report["unanswered"].append({"type":"text","label":key[:160],"name":name})
                except Exception as e: pass
            # native selects
            sels=page.locator('select'); n=await sels.count()
            for i in range(n):
                h=sels.nth(i)
                try:
                    vis=await h.is_visible()
                    if not vis and not await h.evaluate("(s)=>!!(s.id||s.name)"): continue
                    lab=await label_of(h); name=await h.get_attribute("name") or ""
                    if not lab and not vis: continue
                    pref=None
                    for k,v in extra.items():
                        if k.lower() in (name+" "+lab).lower(): pref=[v]; break
                    pref=pref or pick(lab,CHOICE_RULES)
                    if pref==["__ASK__"]: pref=None
                    if pref:
                        got=await choose_select(page,h,pref); report["chosen"][lab[:60]]=got
                        if not got and await is_required(h): report["unanswered"].append({"type":"select","label":lab[:160],"options":(await h.evaluate("(s)=>[...s.options].map(o=>o.text.trim())"))[:12]})
                    elif await is_required(h): report["unanswered"].append({"type":"select","label":lab[:160],"options":(await h.evaluate("(s)=>[...s.options].map(o=>o.text.trim())"))[:12]})
                except Exception: pass
            # react-select style comboboxes (Greenhouse/Ashby)
            combos=page.locator('[class*="select__control"], [role="combobox"]:not(input), div[class*="Select"] [class*="control"], button[aria-haspopup="listbox"], input[id^="react-select-"][id$="-input"]:not([class*="select__input"])')
            n=await combos.count()
            for i in range(n):
                h=combos.nth(i)
                try:
                    if not await h.is_visible(): continue
                    if await h.evaluate("(el)=>el.tagName==='INPUT'"): h=h.locator('xpath=ancestor::div[3]')   # unstyled react-select (Wellfound): use the control container
                    lab=await label_of(h)
                    if not lab: continue
                    cur=(await h.inner_text()).strip()
                    if cur and cur not in ("-","–","—") and not re.search(r"^select|^choose|^please (select|choose)|--",cur,re.I): continue
                    pref=None
                    for k,v in extra.items():
                        if k.lower() in lab.lower(): pref=[v]; break
                    pref=pref or pick(lab,CHOICE_RULES)
                    if pref==["__ASK__"]:
                        report["unanswered"].append({"type":"combo","label":lab[:160],"note":"AI-use question left for user"}); continue
                    if pref and company and re.search(r"hear|learn about|find out|source",lab,re.I):
                        cn=re.sub(r"(usa|inc|llc|corp)$","",company,flags=re.I).strip()   # the company's own careers page first, if listed
                        pref=[f"{cn} careers",f"{cn} website",f"{cn}.com",f"{cn} job",cn]+pref
                        if "wellfound" in report["ats"].lower(): pref=["Wellfound","AngelList","Wellfound (AngelList)","Job board","Job Board","Online job board","Job posting"]+pref   # applying through Wellfound: say so
                    if not pref:
                        # unknown question: accept a decline/acknowledge option if the menu offers one, otherwise leave it for the user
                        pref=["I don't wish to answer","Decline To Self Identify","Decline","Prefer not to say","Prefer not to answer","I acknowledge","I agree","I have read","Acknowledge","Agree"]
                    got=await choose_react_select(page,h,pref,lab); report["chosen"][lab[:60]]=got
                    if not got: report["unanswered"].append({"type":"combo","label":lab[:160],"options":LAST_OPTIONS.get(lab[:160],[])[:12]})
                except Exception: pass
            # radios & checkboxes grouped by name
            radios=page.locator('input[type="radio"]'); n=await radios.count(); groups={}
            for i in range(n):
                h=radios.nth(i)
                try:
                    name=await h.get_attribute("name") or f"r{i}"; groups.setdefault(name,[]).append(h)
                except Exception: pass
            for name,hs in groups.items():
                try:
                    if any([await x.is_checked() for x in hs]): continue
                    qlab=await hs[0].evaluate("(el)=>{const fs=el.closest('fieldset'); if(fs){const lg=fs.querySelector('legend'); if(lg) return lg.innerText;} let p=el.parentElement; for(let i=0;i<7&&p;i++){const q=p.querySelector('.application-label, legend, [class*=question], [class*=label], h3, h4'); if(q&&q.innerText.trim().length>3) return q.innerText; p=p.parentElement;} return '';}")
                    qlab=re.sub(r"\s+"," ",qlab).replace("✱","").strip()
                    opts=[]
                    for x in hs: opts.append(((await x.get_attribute("value")) or "", await label_of(x)))
                    # the nearest preceding text is usually the question; prefer it over a distant heading when it reads like one
                    qlab2=await hs[0].evaluate("(el)=>{let p=el.parentElement; for(let i=0;i<9&&p;i++){const prev=p.previousElementSibling; if(prev&&prev.innerText&&prev.innerText.trim().length>3&&prev.innerText.trim().length<420) return prev.innerText; p=p.parentElement;} return '';}")
                    qlab2=re.sub(r"\s+"," ",qlab2).replace("✱","").strip(); optl=[o[1].lower() for o in opts]
                    if qlab2 and qlab2.lower() not in optl and (not qlab or qlab.lower() in optl or (qlab2.rstrip("* ").endswith("?") and not qlab.rstrip("* ").endswith("?")) or (len(qlab.split())<=3 and len(qlab2)>len(qlab)+10)): qlab=qlab2   # a 1-3 word heading (often the company name) is not the question
                    cands=[]
                    for k,v in extra.items():
                        if k.lower() in qlab.lower(): cands.append([v]); break
                    p1=pick(qlab,CHOICE_RULES); p2=pick(" ".join(o[1] for o in opts),CHOICE_RULES)
                    if p1 and p1!=["__ASK__"]: cands.append(p1)
                    if p2 and p2!=["__ASK__"] and p2 not in cands: cands.append(p2)
                    done=None
                    if p1==["__ASK__"]: cands=[]
                    for pref in cands:
                        for pv in pref:
                          for strict in (True,False):   # exact/leading option first, then whole-word
                            for x,(v,l) in zip(hs,opts):
                                if not done and (_match(l,pv,strict) or v.lower()==pv.lower()):
                                    try: await x.check(timeout=3000)
                                    except Exception:   # custom-styled radio (input hidden): click its label, else set it directly
                                        try: await x.evaluate("(el)=>{const l=el.id&&document.querySelector('label[for=\"'+CSS.escape(el.id)+'\"]'); if(l) l.click(); else {el.click();} if(!el.checked){el.checked=true; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true}));}}")
                                        except Exception: continue
                                    done=l or v; break
                            if done: break
                        if done: break
                    if not done:   # statement-style options ("I currently live in the SF Bay Area and can work hybrid"): pick the one that is true for the applicant
                        for x,(v,l) in zip(hs,opts):
                            if l and re.search(OPTION_TRUE,l,re.I) and not re.search(r"\b(not|unable|outside|don't|do not)\b",l,re.I):
                                try: await x.check(timeout=3000)
                                except Exception:
                                    try: await x.evaluate("(el)=>{const l=el.id&&document.querySelector('label[for=\"'+CSS.escape(el.id)+'\"]'); if(l) l.click(); else {el.click();} if(!el.checked){el.checked=true; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true}));}}")
                                    except Exception: continue
                                done=l; break
                    report["chosen"][qlab[:60] or name]=done
                    if not done: report["unanswered"].append({"type":"radio","label":qlab[:160],"options":[o[1] or o[0] for o in opts][:10]})
                except Exception: pass
            # segmented Yes/No button groups and ARIA radios (Ashby)
            try:
                groups=await page.evaluate(r"""()=>{
                  const out=[]; const seen=new Set();
                  const els=[...document.querySelectorAll('button, [role="radio"]:not(input), [role="option"]')].filter(e=>e.offsetParent!==null);
                  for(const e of els){
                    const t=(e.innerText||'').trim(); if(!/^(yes|no|male|female|true|false|i am not a protected veteran|i don't wish to answer|decline)/i.test(t)) continue;
                    const par=e.parentElement; if(!par||seen.has(par)) continue; seen.add(par);
                    const btns=[...par.children].filter(c=>c.tagName==='BUTTON'||c.getAttribute('role')==='radio').map(c=>(c.innerText||'').trim());
                    if(btns.length<2) continue;
                    let q=''; let p=par;
                    for(let i=0;i<6&&p;i++){ const prev=p.previousElementSibling; if(prev&&prev.innerText&&prev.innerText.trim().length>5){q=prev.innerText.trim(); break;} const lab=p.querySelector('label,legend'); if(lab&&lab.innerText.trim().length>5){q=lab.innerText.trim(); break;} p=p.parentElement; }
                    const pressed=[...par.children].some(c=>c.getAttribute('aria-pressed')==='true'||c.getAttribute('aria-checked')==='true'||/selected|active|checked/.test(c.className));
                    par.setAttribute('data-applyq', String(out.length));
                    out.push({q:q.replace(/\s+/g,' ').replace(/[✱*]/g,'').trim(), opts:btns, pressed});
                  }
                  return out; }""")
                for gi,g in enumerate(groups):
                    if g["pressed"]: continue
                    pref=None
                    for k,v in extra.items():
                        if k.lower() in g["q"].lower(): pref=[v]; break
                    pref=pref or pick(g["q"],CHOICE_RULES)
                    if pref==["__ASK__"] or not pref:
                        if g["q"]: report["unanswered"].append({"type":"buttons","label":g["q"][:160],"options":g["opts"][:8]})
                        continue
                    done=None
                    for pv in pref:
                        for o in g["opts"]:
                            if _match(o,pv):
                                await page.locator(f'[data-applyq="{gi}"] > *:has-text("{o}")').first.click(timeout=3000); done=o; break
                        if done: break
                    report["chosen"][g["q"][:60]]=done
                    if not done: report["unanswered"].append({"type":"buttons","label":g["q"][:160],"options":g["opts"][:8]})
            except Exception as e: report["chosen"]["_buttons_err"]=str(e)[:120]
            cbs=page.locator('input[type="checkbox"]'); n=await cbs.count()
            boxes=[]   # (handle, label, group key, question) for every visible, unchecked box
            for i in range(n):
                h=cbs.nth(i)
                try:
                    if await h.is_checked(): continue
                    lab=await label_of(h)
                    if not await h.is_visible() and not lab: continue   # hidden custom-styled boxes (Wellfound) are fine when they carry a label
                    if re.search(r"pronoun|newsletter|marketing|updates|subscribe|text message|sms",lab,re.I): continue
                    grp=await h.evaluate(r"""(el)=>{const fs=el.closest('fieldset,[role=group]'); let n=(el.getAttribute('name')||'').replace(/\[\d+\]$/,'');
                        if(!fs&&!n&&el.id){n='id:'+el.id.replace(/(--|-|_)\d+$/,'').replace(/\[\d+\]$/,'');}   // Wellfound: options share an id prefix, no name/fieldset
                        let q=''; if(fs){const l=fs.querySelector('legend,.application-label,[class*=label]'); q=l?l.innerText:'';}
                        if(!q){let p=el.parentElement; for(let i=0;i<9&&p;i++){const prev=p.previousElementSibling; if(prev&&prev.innerText){const t=prev.innerText.trim(); if(t.length>3&&t.length<300&&/\?|select|choose|which|apply|[*✱]$|pronoun|gender|ethnic|race|veteran|disab|hear about|source/i.test(t)){q=t;break;}} p=p.parentElement;}}
                        return [fs?('fs:'+(fs.id||q||n)):n, q.replace(/\s+/g,' ').replace(/[✱*]/g,'').trim()];}""")
                    boxes.append((h,lab,grp[0] or f"cb{i}",grp[1]))
                except Exception: pass
            done_groups=set()
            for h,lab,gk,q in boxes:
                try:
                    members=[b for b in boxes if b[2]==gk]
                    if re.search(r"agree|acknowledge|consent|certify|confirm|privacy|terms|policy|accurate|true|currently work|current (role|position|job)|i still work|to present",lab,re.I):
                        await tick(h); report["chosen"][lab[:60]]="checked"; continue
                    if len(members)>1:
                        # a pick-list rendered as checkboxes (e.g. "How did you hear about us?"): tick exactly one option
                        if gk in done_groups: continue
                        done_groups.add(gk)
                        if not q and any(re.search(r"he/him|she/her|they/them",b[1],re.I) for b in members): q="Preferred pronouns"   # pronoun pick-list without a captured heading
                        want=pick(q or lab,CHOICE_RULES) or ["Company Website","Careers page","Job Board","Other","Greenhouse"]
                        if want==["__ASK__"]: continue
                        if "wellfound" in report["ats"].lower() and re.search(r"hear|learn about|find out|source",q or lab,re.I): want=["Wellfound","AngelList","Wellfound (AngelList)","Other","Job board"]+want   # applying through Wellfound: say so, else Other
                        if re.search(r"hear|learn about|find out|source",q or lab,re.I): members=[b for b in members if not re.search(r"linkedin",b[1],re.I)] or members   # never claim LinkedIn as the source
                        if re.search(r"select all that apply|environments|best describes?",q,re.I) and not re.search(r"hear|learn|source|ethnic|race|gender|disab|veteran|pronoun",q,re.I):
                            # "which environments describe your experience (select all that apply)": tick every option true for the applicant's history
                            ticked=[]
                            for b in members:
                                if re.search(ENV_TRUE,b[1],re.I) and not re.search(r"none of the above|not applicable|n/a|prefer not|other",b[1],re.I):
                                    try: await tick(b[0]); ticked.append(b[1][:40])
                                    except Exception: pass
                            if ticked: report["chosen"][(q or lab)[:60]]=", ".join(ticked); continue
                        choice=None
                        for pv in want:
                            for b in members:
                                if _match(b[1],pv): choice=b; break
                            if choice: break
                        if not choice and (await is_required(members[0][0]) or re.search(r"hear about|source",q+" "+lab,re.I)):
                            choice=next((b for b in members if re.search(r"other",b[1],re.I)),members[0])
                        if choice: await tick(choice[0]); report["chosen"][(q or lab)[:60]]=choice[1][:60]
                    elif await is_required(h): await tick(h); report["chosen"][lab[:60]]="checked"
                except Exception: pass
            answered={k.lower()[:40] for k,v in report["chosen"].items() if v} | {k.lower()[:40] for k in report["filled"].keys()}
            seen=set(); uu=[]
            for u in report["unanswered"]:
                if u["label"] in seen or u["label"].lower()[:40] in answered: continue
                seen.add(u["label"])
                try:   # a conditional question may have disappeared after another answer (e.g. race after "decline" on Hispanic)
                    if not await page.evaluate(STILL_VISIBLE_JS,u["label"]): continue
                except Exception: pass
                uu.append(u)
            report["unanswered"]=uu
            await page.wait_for_timeout(800)
            await page.screenshot(path=f"{OUT}/{tag}_filled.png",full_page=True)
            cap=await page.evaluate("()=>!!document.querySelector('iframe[src*=hcaptcha], iframe[src*=recaptcha], [data-sitekey]')")
            report["captcha_present"]=cap
            if submit and not report["unanswered"]:
                cands=page.locator('button:has-text("Send application"), button#btn-submit, button[type="submit"], input[type="submit"], button:has-text("Submit application"), button:has-text("Submit Application"), button:has-text("Submit")')
                btn=None
                for i in range(await cands.count()):
                    c=cands.nth(i)
                    try:
                        if await c.is_visible() and re.search(r"submit|apply|send",(await c.inner_text()) or (await c.get_attribute("value")) or "submit",re.I): btn=c; break
                    except Exception: pass
                if btn is None:
                    if re.search(r"job board you were viewing is no longer active|Page not found|job (you are looking for )?(is )?no longer (open|available)|position (has been )?(filled|closed)",await body_text(page),re.I):
                        report["result"]="NOT SUBMITTED: job closed (board or posting no longer active)"
                        json.dump(report,open(f"{OUT}/{tag}_report.json","w"),indent=1); await page.close(); return report
                    raise RuntimeError("no visible submit button")
                baseline=()
                if ats=="greenhouse" and outlook_cfg():
                    op=await outlook_page()
                    if op: baseline=tuple(await outlook_codes(op))   # codes already in the inbox before this submission
                CODE_BOXES='input[autocomplete="one-time-code"]:visible, [class*="security-code"] input:visible, [class*="securityCode"] input:visible, input[name*="security_code"]:visible'
                for attempt in range(2):
                    await btn.scroll_into_view_if_needed()
                    try: await btn.click(timeout=10000)
                    except Exception:
                        # a disabled submit button usually means the form was already sent and the code prompt is up
                        body0=await body_text(page)
                        if not re.search(r"verification code|security code",body0,re.I): await btn.click(timeout=10000,force=True)
                    for _w in range(15):   # let the submission settle (Greenhouse shows a spinner): stop when a code prompt, confirmation, success text or error appears
                        await page.wait_for_timeout(3000)
                        body=await body_text(page)
                        if re.search(r"verification code|security code|confirm you.re a human|thank you for|thanks for|application (has been |was |is )?(submitted|received|sent|in\b)|good news|/confirmation",body+" "+page.url,re.I) or await page.locator(CODE_BOXES).count() or await page.locator('[class*=error]:visible, [role=alert]:visible, [aria-invalid=true]').count(): break
                    body=await body_text(page)
                    if re.search(r"verification code|security code|confirm you.re a human",body,re.I) or await page.locator(CODE_BOXES).count():
                        if await enter_email_code(page,report,baseline):
                            await page.wait_for_timeout(800)
                            try: await btn.click(timeout=10000)
                            except Exception:
                                b2=page.locator('button[type="submit"]:visible, button:has-text("Submit application"):visible').first; await b2.click(timeout=10000)
                            await page.wait_for_timeout(9000)
                            body=await body_text(page)
                            if re.search(r"security code|verification code",body,re.I) and re.search(r"invalid|incorrect|expired|doesn.t match|try again",body,re.I): report.setdefault("errors",[]).append("verification code rejected")
                    # Greenhouse's uploader occasionally drops the file ("Cannot read properties of undefined (reading 'uploadFile')"): re-attach and submit once more
                    errs0=await page.evaluate("()=>[...document.querySelectorAll('[class*=error], [role=alert]')].map(e=>e.innerText.trim()).filter(Boolean).slice(0,8)")
                    if attempt==0 and any(re.search(r"uploadFile|Resume/CV is required",e) for e in errs0):
                        try:
                            await page.locator('input[type="file"]').first.set_input_files(P["resume"],timeout=15000); await page.wait_for_timeout(6000)
                            report.setdefault("notes",[]).append("resume re-attached after uploader error"); continue
                        except Exception: pass
                    break
                sm=re.search(r"thank you for (applying|your application|submitting|your interest|sharing)|thanks for applying|application (has been |was |is )?(submitted|received|sent|in\b|complete)|we('ve| have) received your application|successfully submitted|you're all set|task complete|good news",body,re.I)
                if not sm and re.search(r"/confirmation\b",page.url): sm=re.search(r"\S.{0,60}",body)   # Greenhouse confirmation page URL
                if ats=="wellfound":   # success = the apply modal is gone (or says sent) and no question is still flagged required
                    modal_gone=(await page.locator('button:has-text("Send application")').count())==0
                    sm=(re.search(r"application (has been )?sent|Applied",body,re.I) or re.search(r"\S.{0,60}",body)) if (modal_gone or re.search(r"application (has been )?sent",body,re.I)) and not re.search(r"This question is required",body) else None
                errs=await page.evaluate("()=>[...document.querySelectorAll('[class*=error], [role=alert], .invalid-feedback, [aria-invalid=true], [class*=correction]')].map(e=>e.innerText.trim()).filter(Boolean).slice(0,8)")
                m=re.findall(r"Missing entry for required field:\s*([^\n]+)",body)
                if m: errs=errs+[f"missing: {x.strip()}" for x in m]
                still_code=await page.locator(CODE_BOXES).count()
                ok=bool(sm) and not still_code and not any(re.search(r"required|invalid|correct|missing",e,re.I) for e in errs)
                if still_code and not ok: errs.append("still on the security-code step")
                report["submitted"]=ok; report["result"]=((sm.group(0)+" … ") if sm else "")+body[-450:].replace("\n"," | "); report["errors"]=errs; report["final_url"]=page.url
                await page.screenshot(path=f"{OUT}/{tag}_after.png",full_page=True)
            elif submit: report["result"]="NOT SUBMITTED: unanswered required questions"
        except Exception as e:
            report["result"]=f"ERROR {type(e).__name__}: {str(e)[:300]}"
            try: await page.screenshot(path=f"{OUT}/{tag}_error.png",full_page=True)
            except Exception: pass
        json.dump(report,open(f"{OUT}/{tag}_report.json","w"),indent=1)
        await page.close()
        return report
asyncio.run(run())
