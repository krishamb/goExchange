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
HERE_REPO=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repository root (job-search/tools/apply.py)
JOBS_DIR=os.path.expanduser(JOBS_DIR)
P=json.load(open(os.path.join(JOBS_DIR,"profile.json")))
for _k in ("resume","cover_letter"):
    if P.get(_k): P[_k]=os.path.expanduser(P[_k])
EXEC_RESUME=os.path.join(JOBS_DIR,"Ambarish_Krishnamurthy_Executive_Resume.pdf")
def resume_for(title):
    """Executive resume (CTO / VP / Head / Director / Engineering Manager) for leadership roles; the Distinguished Architect
    resume for principal, staff, architect and engineer roles. Falls back to the architect resume if the executive file is absent."""
    if title and os.path.exists(EXEC_RESUME) and re.search(r"\b(CTO|Chief (Technology|AI|Executive|Product|Information)|VP|SVP|EVP|Vice President|Head of|Director|Manager|TLM)\b",title,re.I) and not re.search(r"\bArchitect",title,re.I):
        return EXEC_RESUME
    return P["resume"]
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
# --assist: visible browser; the filler fills the form and the applicant reviews it and clicks Submit themselves
ASSIST="--assist" in sys.argv
ASSIST_WAIT=int(os.environ.get("ASSIST_WAIT","600"))
HEADED=("--headed" in sys.argv) or ASSIST
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
 (r"typ(e|ing) (in )?(my |your )?initials\b.{0,120}(signature|sign|agree|acknowledg|consent|nda|non-?disclosure)|by typing (my|your) initials|initials? (to|and) (sign|agree|acknowledg|indicate)|enter your initials", first[0].upper()+last[0].upper()),   # type-to-sign acknowledgement that asks for INITIALS (e.g. applicant NDA)
 (r"name of the entity for which you will be performing the outside activity|outside (business )?activity.{0,80}(name of the entity|description)", "N/A (no outside business activities)"),
 (r"^(?!.*e-?mail)(.*\b(street|residential|home|permanent|mailing|physical|current) (residence )?(street )?address\b|^address$|^what is your (home |current )?address)", P.get("street","")+", Santa Clara, CA "+P.get("zip","95054") if P.get("street") else P["location"]),
 (r"^(street )?address( line)? ?1$|^street( address)?$|^address line one$", P.get("street") or "Santa Clara, California, United States"),
 (r"reasons? for leaving (your )?(last|previous|past) (three|3|two|2|few)? ?(positions|jobs|roles|employers)|why did you leave (your )?(last|previous) (positions|jobs|roles)", "Hyperion AI (2023-present): my current role as CTO and co-founder; I would leave to lead engineering at larger scale. Yahoo Finance: left in 2023 to co-found Hyperion AI and build an agentic AI and digital-asset platform. Earlier roles (JPMorgan Chase and other financial-services firms): each move was for broader scope and ownership of larger platforms, never for performance reasons."),
 (r"(one thing|something|a project|what) (that )?you (have )?worked on recently|recent(ly)? (work|project|accomplishment).{0,40}proud|proud of .{0,30}recent", "Most recently, as CTO and co-founder of Hyperion AI, I built our digital-asset and agentic AI platform end to end. On the financial side: Rust (Tokio), C++17 and Go/gRPC services for chain and RPC ingestion, DEX routing, wallet analytics and custody-sensitive reconciliation, designed so every balance can be recomputed from an append-only journal and replayed. On the AI side: MCP clients and servers, a multi-agent plan-validate-dispatch-replan loop, open-weight model serving through vLLM and llama.cpp, and a reproducible benchmarking platform with evaluation gates in front of every release. I am proudest that correctness was built in from day one: idempotent operations, reconciliation that catches drift automatically, and replay tests that let a very small team ship quickly without losing track of money."),
 (r"examples of your work in the area of emphasis|work in the area (of emphasis )?you selected", "At JPMorgan Chase I designed the journal and replay data layer for multi-asset trading: append-only event streams as the source of truth, with materialized state rebuilt deterministically for recovery, audit and testing, and explicit schemas between producers and consumers. At Yahoo Finance, as Chief Architect, I led the data platform behind quotes, charts, portfolios and screeners for about 40M daily users through the bare-metal-to-AWS migration, including datastore selection, partitioning, caching tiers and the cutover and rollback plan. At Hyperion AI I designed the Postgres-backed state and reconciliation store for our digital-asset systems, fed by Rust and Go ingestion pipelines. Across all three I set the data model and storage design for the whole platform and worked with teams to keep schemas, migrations and query paths consistent."),
 (r"full (legal )?name,? (exactly )?as (it )?appears|legal name (exactly )?as (it )?appears|name as (it )?appears on (your )?(government|passport|id)", P["name"]),
 (r"(list|any) (of )?(professional |securities |finra )?licen[cs]es (that )?you (currently )?(hold|have)|licen[cs]es you (currently )?hold or (have )?previously held", "None"),   # never FINRA-registered; no professional licenses
 (r"(work|company|business|corporate|former|previous|prior) e-?mail|e-?mail .{0,30}(while|when) (you )?(work|were employed)|what was your .{0,20}e-?mail", "N/A"),   # never his personal email as a former-employer work address
 (r"if applying to (a )?remote (us )?location,? what state", "California"),
 (r"student or temporary visa|temporary visa|(visa|opt|cpt) (type|expir|end date)|f-?1 opt|(if|are) you (are )?(currently )?on a non-?immigrant visa", "N/A (I am a US citizen)"),
 (r"where (are )?you (are )?currently employed|(name of )?your current employer|which company (are you|do you) (currently )?work", "Hyperion AI"),
 (r"title of your current (position|role|job)|your current (job )?title", "CTO & Technical Co-Founder / Principal Architect"),
 (r"tangible factors .{0,40}(important|matter)|what (factors|things) (are|matter) most (important )?(to you )?in (your|a) (next|new) (role|job|position)", "Scope and ownership: leading the architecture and engineering of a core platform with real users; a strong, high-trust team with high standards for correctness and reliability; clear business impact I can measure; flexibility to work hybrid or remote from the SF Bay Area; and competitive compensation (base around $250,000+ plus equity)."),
 (r"(built|made|created|shipped) (with|using) (ai|llms?|gen ?ai)|(proud|proudest) .{0,60}(with|using) (ai|llms?)|ai (project|system|product) you.{0,20}(proud|built)", 'At Hyperion AI I built our agentic benchmarking platform end to end: a multi-agent plan-validate-dispatch-replan loop, MCP tooling (three servers, nine tools with role-based allowlists, schema validation and execution budgets), open-weight model serving through llama.cpp and vLLM, and a 121-measure scorecard that compares models and agents on accuracy, latency and cost. What I am proudest of is that a very small team kept it correct: every change, including AI-written code, has to pass replay and golden-output checks before release, so results stayed reproducible as the system grew.'),
 (r"what about .{1,50} makes (it|them|us|this)? ?(an? )?(appealing|attractive|compelling|exciting|great|interesting|good)|makes .{0,40}(an appealing|a compelling|an attractive|a great|an exciting) (place|company|next step|opportunity)", ANS.get("why_us","")),   # tailored per company at run time (JOB_WHY)
 (r"^if (yes|so),? (what|which) (technologies|tools|stack|tech stack) did you use|(what|which) (technologies|tools|tech stack) did you use", 'Event streaming with Kafka and Redpanda (schema-versioned Protobuf/Avro events, with an append-only journal and deterministic replay at JPMorgan Chase); services in Go, Rust (Tokio), Java, Python and C++ over gRPC and REST; Postgres and Redis for state; Kubernetes and Terraform on AWS, GCP and Azure; OpenTelemetry, Prometheus and Grafana for observability; and for AI work, vLLM and llama.cpp model serving, MCP tools and RAG pipelines.'),
 (r"outside business activit|possibility of conflict of interest|disclose any (potential |possible )?conflicts? of interest", "None. I have no outside business activities that would present a conflict of interest."),
 (r"why .{0,40}(interested|want) .{0,40}code for america", "I want to put the platform and AI engineering I have built over 25 years to work where reliability and fairness matter most: for people who depend on government services. At Yahoo Finance and JPMorgan Chase I built systems that millions of people relied on and where mistakes were costly, and at Hyperion AI I build agentic AI with evaluation gates and human review for high-stakes outputs. Code for America's work to make safety-net programs simple, accessible and dignified is the kind of problem where careful engineering has direct human impact, and its data challenges (messy multi-agency data, privacy, auditability, measuring outcomes honestly) are ones I know well. I would like the next chapter of my career to serve that mission."),
 (r"(architecture|data[- ]model(l)?ing) (or (a )?(data[- ]model(l)?ing|architecture) )?decision you (owned|made|drove)|data[- ]model(l)?ing decision", 'At JPMorgan Chase I owned the decision to model multi-asset order flow as an append-only journal of immutable events rather than mutable order records. The tradeoffs were storage and read complexity (every current state becomes a projection) against deterministic replay for recovery, audit and testing, plus latency on the critical path, which we handled by journaling asynchronously with bounded in-memory buffers. I made the decision through a written design review with the trading desks, risk and operations, with explicit rollback criteria, and communicated it through a reference implementation other teams could adopt. We assessed the outcome by recovery time after incidents, our ability to reproduce production issues exactly in test, and audit-request turnaround, all of which improved.'),
 (r"(caught|found|spotted|identified) (a|an) (problem|bug|issue|defect) in (ai|llm|copilot|claude)[- ]?(generated|written) code|problem in ai-generated code", 'At Hyperion AI, a Claude Code refactor of our benchmark scoring code passed every unit test but silently changed how ties were ranked, because it replaced a stable sort with an unstable one. Our replay suite caught it before release: re-running a stored set of real benchmark runs produced different rankings on a handful of tasks and failed the golden-output comparison. I traced it to the generated diff and fixed it. We then made the full replay suite a required CI gate for every AI-written change, not just unit tests, and added property-based tests for ordering and determinism in the scoring code, and that class of silent behavior change has not reached production since.'),
 (r"title (you )?(held|hold)|title (held )?at (your )?(most recent|current|last|previous) (employer|company|job)|(most recent|current|last) employer.{0,20}title|position (held|title) at", "CTO & Technical Co-Founder / Principal Architect"),   # a title field, never the company name
 (r"(significant|an?|your) azure (solution|project|architecture|system|platform)|azure solution you|describe .{0,60}\bazure\b", 'A representative example is a C#/.NET data and API platform on Azure. Architecture: ASP.NET Core APIs on Azure App Services, event-driven processing in Azure Functions, Cosmos DB for operational data and Azure Storage for documents and archives, secrets in Key Vault with managed identities, CI/CD in Azure DevOps with staged slot deployments, and Azure Monitor for SLOs, alerting and cost tracking. My responsibilities were the architecture, the service and data contracts, the security model (managed identities, least-privilege RBAC, Key Vault), the CI/CD and rollout design, and hands-on code in the critical paths. For scale, the largest platform I have led was at Yahoo Finance, where as Chief Architect I moved the quotes, charts, portfolios and research platform (about 40M daily and 150M monthly users) from bare metal to the cloud with phased cutovers and rollback plans; I bring the same discipline to Azure.'),
 (r"microservices? architecture you (designed|delivered|built|led)|describe .{0,40}microservices", 'At Yahoo Finance, as Chief Architect, I led the re-architecture of the quotes, charts, portfolios, screeners and research platform (about 40M daily and 150M monthly users) into independently deployable services during its bare-metal-to-AWS migration, across a 75+ engineer organization. The main challenges: scalability under market-open spikes, handled with horizontal scaling, caching of hot quote data and back-pressure; reliability during the migration, handled with phased cutovers, dual-running and a rollback plan for every step; integration across many teams, handled with explicit, versioned service and API contracts and a shared reference architecture; and service communication, where we standardized timeouts, retry budgets, circuit breakers and end-to-end tracing so failures stayed contained. At JPMorgan Chase I applied the same principles to multi-asset execution services, adding journaling and deterministic replay for recovery and testing.'),
 (r"integrat\w* security into|security into (the |your )?(application|development|software)|devsecops|shift(ed|ing)?[- ]left .{0,20}security|security .{0,40}ci/?cd .{0,60}(infrastructure|lifecycle)", 'I build security in from the design stage rather than adding it later. In design reviews we threat-model each service and define its trust boundaries, data classification and auth model up front. In code: secure-coding standards, mandatory peer review, input validation at every API boundary, and no secrets in code. In CI/CD: dependency and container-image scanning, static analysis and secret scanning as gating checks, signed build artifacts, and protected branches with auditable, staged releases. In cloud infrastructure: everything defined as code (Terraform) with policy checks, least-privilege IAM and managed identities, secrets in a vault (Azure Key Vault or AWS Secrets Manager), encryption in transit and at rest, private networking, and centralized audit logging. At JPMorgan Chase, Morgan Stanley and Bank of America/Merrill this ran under strict regulatory change control; at Hyperion AI it covered custody-sensitive reconciliation and key handling for digital-asset systems.'),
 (r"claude certification|anthropic (partner|certification)", "I don't hold a Claude certification yet. I use Claude Code daily at Hyperion AI for code analysis, debugging, test generation and parallel subsystem reviews."),
 (r"contract(ual)? (obligation|agreement|commitment)s?|obligations? (to|with) (your|a) (current|former|previous) employer|restrictive covenant|non-?compete|non-?solicit", "None. I have no non-compete, non-solicitation or other contractual obligation to my current employer that would restrict this role."),
 (r"password", "N/A"),   # never put a link or anything else in a password box
 (r"(how many )?years (have you|of|in) (directly |people |engineering )?(managed|managing|management|led|leading|supervis\\w+)|how many years .{0,40}(managed|managing|led|leading|supervis\\w+) (software |engineering |technical )?(engineer|team|people|staff|report)|years of (people|engineering|team) management", "10"),   # applicant: 10+ years leading engineers (25+ years engineering overall)
 (r"name one (production )?(agent|agentic workflow)|production agent or agentic workflow you.ve built|first symptom that told you something was wrong", "Hyperion AI's agent orchestration platform (2024): a multi-agent plan-validate-dispatch-replan workflow over MCP tools (3 servers, 9 tools), with open-weight models served through vLLM and llama.cpp. The first symptom was a rise in step-budget exhaustion on a subset of benchmark tasks: runs that should have finished in a few steps kept re-planning until they hit the limit. Replaying a failing run step by step showed the root cause was an interaction, not a bug in any one component: an MCP tool silently truncated its JSON payload past a size limit, the validator scored the truncated result as a failed step, and the planner re-issued the identical call. We fixed it with pagination in the tool and a validator check that tells truncation apart from failure, and added the run to the replay regression suite."),
 (r"earliest (you can|you could|possible|date).{0,25}start|when (can|could|would) you (be able to )?start|earliest start|notice (would|do) you need to give", "Immediately (available to start right away)"),
 (r"employment gaps?|gaps? in your (work|employment) history", "My complete work history, with dates, is on my resume."),
 (r"why are you (looking|searching|seeking) (for )?(a )?(new )?(opportunit|role|job|change)|why (are you|do you want to) (leave|leaving|move on|make a (move|change))|reason for (leaving|looking|change)", "I'm looking for a role where I can apply my mix of hands-on architecture and engineering leadership at larger scale, on AI, fintech and data-intensive products with real users and a strong engineering team. Hyperion AI gave me end-to-end experience building an agentic platform from zero; the next step is bringing that to a company with an established product and customers."),
 (r"^(?!.*(this application|this form)).*(do you use|have you used|are you (a |an )?(user|customer) of) (our|the|this) (product|app|platform|service)", "Yes, I use it regularly."),
 (r"(expect\w* to earn|earn per year|salary|compensation|pay).{0,160}(numerical|numeric|number only|digits only|numbers only)|(numerical|numeric) value.{0,80}(salary|earn|compensation|pay)", "250000"),
 (r"expect\w* to (earn|make)|earn per (year|annum)|annual earnings expectation", "$220,000 - $350,000 depending on scope"),
 (r"desired pay|pay expectations?|expected pay|what (pay|rate) are you (looking|seeking)", "$220,000 - $350,000"),
 (r"langsmith|(tracing|trace|debugging) session .{0,60}(bug|fix)|trace .{0,40}(used|helped) .{0,20}fix", 'At Hyperion AI our multi-agent loop (plan, validate, dispatch, replan) kept re-planning on a subset of benchmark tasks and burning its step budget, although every component looked correct in the code. I opened the full trace of one failing run in our tracing and replay harness (the equivalent of a LangSmith trace: every model call, tool call, input, output and latency as one tree). It showed that an MCP tool returned a truncated JSON payload once results passed a size limit, the validator scored the truncated result as a failed step, and the planner re-issued the identical call. Each part behaved correctly on its own; only the step-by-step trace exposed the interaction. The fix was pagination in the tool plus a validator check that tells truncation apart from failure, and that trace became a regression case in the replay suite.'),
 (r"^what are your (career plans|career goals|long[- ]term (career )?goals)|where do you see (your career|yourself) in", "To keep leading AI and platform engineering where architecture and hands-on delivery meet: owning the technical direction of a product platform, building and growing strong engineering teams, and staying close to the code on the critical path, in AI, fintech and data-intensive products."),
 (r"^(?!.*(this application|this form|to apply|applying|cover letter)).*(used ai coding (agents|tools|assistants)|ai-native building|built something (meaningful )?(with|using) ai|coding agents?/tools)", "Yes. At Hyperion AI I built our benchmarking and agent-evaluation platform with Claude Code as a daily tool: parallel reviews of the platform's subsystems, generating its test and replay harnesses, debugging, and code analysis, with every AI-written change going through the same evaluation gates and code review as hand-written code. That let a very small team build and keep correct a 121-measure scorecard with 13 comparability checks. I also run open-weight models (Qwen, gpt-oss, Llama) through llama.cpp and vLLM for agent work, and use RAG for research."),   # the applicant's reviewed AI-usage answer, as a build example
 (r"^if other or (employee )?referral|^if (you selected )?(other|referral).{0,40}(describe|specify|name)", "N/A"),   # not referred; the source question is answered with the company's careers page
 (r"experience with (bitcoin|lightning|crypto|blockchain|web3|digital assets|defi|stablecoins?)|(bitcoin|crypto|blockchain|web3|digital asset|defi) experience", "At Hyperion AI (2023-present) I built digital-asset systems in Rust (Tokio), C++17 and Go/gRPC: chain and RPC ingestion, DEX routing, wallet analytics and custody-sensitive reconciliation, plus an Intel SGX-based exchange architecture. Earlier I built low-latency trading systems at JPMorgan Chase and Morgan Stanley. I have not built directly on the Lightning Network, but the ingestion, reconciliation and latency discipline carry over directly."),
 (r"(engineering|technical|coding|architecture|architectural) (standards|patterns|principles|guidelines|best practices)|architectural patterns|standards across (a|the|your) (team|organi[sz]ation)", "At Yahoo Finance, as Chief Architect for a 75+ engineer organization, I defined and drove adoption of the platform's architecture standards through the bare-metal-to-AWS migration: service and API contracts, a reference architecture for the quotes, charts and portfolio services, observability and SLO standards, and design-review and cutover/rollback playbooks. Adoption came through architecture reviews and pairing with each team's tech lead rather than by mandate. At JPMorgan Chase I set the latency and correctness standards for multi-asset execution paths (journaling, replay and deterministic testing) across a 50+ person organization in the US, UK and India. At Hyperion AI I established the engineering standards for the agentic platform: evaluation gates, replay harnesses, code review and observability requirements before anything reaches production."),
 (r"(rank|list|name|what are) (the |your )?(top \d+ )?skills?( sets?)? (that )?you('d| would) like to (further )?(develop|grow|build|learn)|skills? (do )?you (want|hope|would like) to (further )?(develop|grow|learn)", "1) Production AI agents over large data platforms: evaluation, reliability and cost control at scale. 2) Cloud and data-infrastructure cost engineering (FinOps) for data-heavy systems. 3) Growing engineering leaders and teams as the organization scales."),   # consistent with the applicant's CTO / architect direction
 (r"^i (hereby )?certify that (the |all |my )?(answers|information|statements)|^i (hereby )?certify that .{0,120}(true|correct|complete|accurate)", "Yes, I certify that my answers are true, correct and complete."),   # applicant: certification Yes (a free-text box, not a country)
 (r"\breferred by\b|\bwho referred\b|\breferr(ed|al)\b.{0,80}\bname\b|\bname of (the |your )?(referring )?(employee|referrer)\b", "N/A"),   # not referred: never the applicant's own name
 (r"(require|need) any (special )?accommodations?|accommodations? (during|for) (the )?interview", "No."),
 (r"(currently|presently) (based|located|living|residing) (in|near|around) (nyc|new york|manhattan|brooklyn)|are you (based|located|living) (in|near) (nyc|new york)|(live|living) (near|within commut\w+ distance of) (nyc|new york|the (nyc|new york) office)", "Not yet: I live in Santa Clara, California, and I am willing to relocate to New York City and commute to the office as the role requires."),
 (r"(what|which) do you think (are|is) (our|the) (most complex|biggest|hardest) (technical )?challenges?", "From the outside, I would expect the hardest problems to be: keeping the core transaction path fast and available under load; guaranteeing correctness of money and state movement through retries, reversals and partial failures (idempotency, ledgers, reconciliation); and scaling the platform and the team without losing auditability. I have worked on each: sub-250-microsecond execution paths in electronic trading, journal and replay systems at JPMorgan Chase for deterministic recovery and reconciliation, and custody-sensitive reconciliation at Hyperion AI. I would want to learn where your current bottlenecks actually are before prioritizing."),
 (r"geometric processing|3d/cad|\bcad\b|computational geometry|mesh processing", None),
 (r"(what|which) (programming )?languages are you (most )?(comfortable|proficient|experienced|strongest)|languages are you most comfortable coding in", "Python, Go, Rust (Tokio), C++, C#/.NET and Java; also TypeScript/JavaScript (including Node.js and React.js), Solidity, SQL and shell scripting"),
 (r"how (quickly|soon) are you looking to (start|begin|make a move)|how quickly (can|could|would) you (start|join)", "About two weeks after an offer: I am currently CTO at Hyperion AI and would give two weeks' notice."),
 (r"address line 2|apartment|\bapt\b|suite|\bunit\b|\(brazil only\)|\bcep\b", None),
 (r"(home |mailing |current )?address[ ,-]*city|^city\*?$", "Santa Clara"),
 (r"(home |mailing |current )?address[ ,-]*(state|province)|^state( ?/ ?province)?\*?$", "California"),
 (r"(home |mailing |current )?address[ ,-]*country", "United States"),
 (r"today'?s date( of application)?", __import__("datetime").date.today().strftime("%m/%d/%y")),
 (r"if you answered (extensively|yes) or (moderately|no)? ?.{0,40}(ai|above question)|if you answered extensively", "Daily: Claude Code for code analysis, debugging, test generation and parallel subsystem reviews; open-weight models (Qwen, gpt-oss, Llama) through llama.cpp and vLLM for agent work; and RAG for research. At Hyperion AI I also build production agentic systems (MCP servers, multi-agent orchestration, evaluation harnesses)."),
 (r"finra licen[sc]e|securities licen[sc]es? (do you|you) (currently )?hold", "None"),
 (r"(what|which) (other )?languages (do you|can you) (speak|communicate|read|write)|languages? (spoken|you speak)|spoken languages|languages of fluency|list all languages", "English (full professional proficiency), Tamil and Hindi."),
 (r"graduation (year|date)|year (of|you) graduat|when did you graduate", "1995"),
 (r"(share|provide|give) (some )?detail(s)? on your experience with python|describe your (experience|background) (with|in) python|your python experience", "Python is one of my core languages. At Hyperion AI I built a Python/llama.cpp model-and-agent evaluation platform (endpoint management, interactive chat, benchmark jobs, saved-run comparison) and Go and FastAPI backend services for exchange connectivity and market data. Earlier, in electronic trading, I built FPGA-facing test, replay and regression infrastructure in C++ and Python, and automated trading-lifecycle operations with Python, Perl and Shell."),
 (r"experience with java or go(lang)?|experience with go(lang)? or java|java or golang", "Yes, both. Go: at Hyperion AI I built Rust, C++ and Go/gRPC services for chain and RPC ingestion, WebSocket streams and wallet analytics, plus Go and FastAPI backend services on Kubernetes for exchange connectivity and market data; earlier I designed a cryptocurrency-exchange architecture on Go/gRPC microservices with Intel SGX enclaves, Kubernetes, Redis and AWS Lambda. Java: in electronic trading I architected execution paths in C++ and Java at sub-250-microsecond latency, and built C++/Java replay and backtesting engines for journal parsing and OMS integration."),
 (r"building products (vs\.?|versus|or|and) systems|products (vs\.?|versus) (platforms|systems|infrastructure)", "Mostly systems, with end-to-end product ownership on top. On the systems side: as Chief Architect at Yahoo Finance I moved the Finance platform (quotes, charts, portfolios, screeners, research; about 40M daily and 150M monthly users) from bare metal to AWS; in trading I architected execution paths in C++ and Java at sub-250-microsecond latency; and at JPMorgan Chase I built journal and replay streams that other engineers built on. On the product side: as CTO and co-founder of Hyperion AI I owned the product from the agentic platform and benchmark scorecard through to what we shipped to institutional partners. I am strongest where the two meet: platforms whose users are other engineers or demanding customers, where reliability and performance are the product."),
 (r"(describe|tell us about) your agentic ai experience|agentic ai experience|experience (with|building) (ai )?agents|where have you used agentic", "At Hyperion AI, as CTO and Technical Co-Founder, I built our agentic platform end to end: MCP clients and servers (3 servers, 9 tools), a multi-agent plan-validate-dispatch-replan loop, open-weight model serving (Qwen, Llama 3.3-70B, gpt-oss) through llama.cpp and vLLM, and a reproducible 121-measure benchmarking scorecard informed by MLPerf Inference and BFCL, running in production with correctness gates, replay harnesses and OpenTelemetry/Prometheus observability. Before that, at Yahoo Finance, I architected RAG-based research assistants on top of the Finance platform."),
 (r"^if (yes|so),?.{0,80}(while (working|employed)|when you (worked|were employed)|employee (id|number)|dates of (employment|service)|former (manager|supervisor)|your role (there|at))", "N/A"),
 (r"(describe|tell us about) a time you used ai to improve your (work|productivity|team)|used ai to improve your work", "At Hyperion AI I used Claude Code for parallel reviews of our benchmark platform's subsystems and to generate its test and replay harnesses. What worked: a very small team built, and kept correct, a 121-measure scorecard with 13 comparability checks, because every AI-generated change went through the same evaluation and review gates as hand-written code. What I would change: start each subsystem with a short written spec and a handful of hand-written, spec-level test cases, then let AI generate the rest, so generated tests check intended behaviour rather than mirroring the code as written; and track the time saved more formally so the gains are measured, not anecdotal."),
 (r"where did you (complete|earn|get|receive|obtain|do) your (undergraduate |bachelor'?s? |university |college )?(degree|studies|education)|where did you (go to|attend|study at) (college|school|university)|which (university|college|school) did you attend", "University of Madras (Bachelor of Engineering, Computer Science and Engineering)"),
 (r"if you (will )?require relocation|relocation.{0,60}(timeline|self-funded|without employer assistance)", "No relocation is needed for a Bay Area role: I live in Santa Clara, California. For a New York role I am willing to relocate to New York City within about three months of an offer."),
 (r"personally (completed|filled|prepared|written|wrote) (out )?(this|the|my) (application|form)|completed (this|the) application (myself|personally|on my own)|(filled|written) (out )?(this|the) application (myself|personally)|(completed|submitted) by (me|the candidate) (personally|alone)", None),
 (r"^(?!.*\b(agent|project|workflow|system|product|tool|company|school|reference|referr)).*(first and last name|legal name|full legal name|^(full )?name\b(?!\s+(one|a|an|the|two|three|some|any|your|of)\b)|^your name|_systemfield_name)", P["name"]),
 (r"first ?name", first),(r"last ?name|surname|family name", last),
 (r"preferred name", first),(r"e-?mail", P["email"]),(r"phone|mobile|contact number|^tel\b|^telephone", P["phone"]),
 (r"zip|postal|post ?code", P.get("zip","95054")),
 (r"(what|which) (types?|kinds?) of (roles?|positions?|jobs?) (are|would) you (be )?interested in|roles? (are you|you are) (most )?interested in", "Engineering leadership and senior technical roles in AI/ML: CTO, VP / Head / Director of Engineering or AI, Engineering Manager for AI teams, and Principal / Staff / Distinguished Engineer or AI Architect roles building LLM, data-platform and distributed systems."),
 (r"(list|describe|what are) your (relevant )?(technical )?skills( and competencies)?|relevant technical skills|technical competencies", "AI/ML and LLM systems (RAG, agentic workflows, evaluation, inference optimization); Python, Go, Rust and C++; distributed and low-latency streaming systems (Kafka); cloud and infrastructure (AWS, Kubernetes, Terraform); data platforms (Spark, Postgres/MySQL, vector databases); and leading engineering organizations as CTO and co-founder of Hyperion AI and at Yahoo (75+ engineers) and JPMorgan (50+ engineers)."),
 (r"country( of residence| you (live|reside) in)?$|^country\b|which country|country of residence", "United States"),
 (r"sponsorship needs?|require (employer |visa |company )?sponsorship|sponsorship to work|need sponsorship", "None. I am a US citizen and need no sponsorship or visa transfer."),
 (r"where do you (currently )?(reside|live)|city,? state|current city|city and state|city of residence|what city do you live", "Santa Clara, CA"),
 (r"^nationality$|your nationality|nationality\b.{0,20}(:|\*|$)", "United States (U.S. citizen)"),
 (r"age (range|bracket|group)|what is your age|select your age", ["40-49","40 - 49","40 to 49","45-49","40-44"]),   # applicant (2026-10-04)
 (r"most interesting (paper|blog|article|documentation|post)|paper, blog post, or documentation", "Anthropic's 'Building effective agents' post - it matches what we learned building Hyperion AI the hard way: simple composable patterns (routing, tool use, evaluator loops) beat heavyweight agent frameworks in production, and the discipline of keeping a human-verifiable boundary around each agent step is what makes the system debuggable. I pair it with the MCP spec docs, which turned our one-off tool integrations into a clean contract."),
 (r"(more than |over )?(three|3)\+? years .{0,30}(deploying|delivering|implementing) .{0,30}(solutions|products)? ?(at|with|for) (customer|client)", ["Yes","YES","yes"]),
 (r"held a u\.?s\.? security clearance|security clearance in the past|(hold|have|held) .{0,25}security clearance", "N/A - I have never held a U.S. security clearance."),   # applicant is a US citizen but has never held a clearance; never answered otherwise
 (r"(able|willing) to (work|be|commute) (from|in|into) (the |our )?office [123] days?|office [123] days? (a |per )?week|work (from|in) the office (up to )?[123] days?|in[\s-]*office [123] days?", ["Yes","YES","yes"]),   # applicant (2026-10-04): yes to office presence up to 3 days/week (4- and 5-day asks stay excluded/flagged)
 (r"u\.?s\.? person\b|citizen, legal permanent resident", ["Yes","YES","yes"]),
 (r"where have you most recently worked|most recent place of (work|employment)", P["org"]),
 (r"llm (feature|capability|product) you (shipped|built|launched)|feature you shipped.{0,60}(measure|metric|impact)", "At Hyperion AI I shipped an agentic retrieval-and-planning feature: an LLM-driven multi-step planner with RAG over customer data, exposed as a production API. We measured task success rate against a replay suite of real workflows (61% to 88%), p95 end-to-end latency (14s down to 6s via caching and parallel tool calls), and step-budget burn per task; the evals run nightly as regression gates."),
 (r"involvement with the codebase|how (hands.?on|involved) (are|were) you .{0,40}(code|codebase|technical)", "Deeply hands-on: I write and review production code daily (Python, Go, TypeScript), own architecture end to end, and built core services of Hyperion AI's agentic platform myself while leading the engineering team."),
 (r"what does .{0,5}ai.?first.{0,5} mean (to you|in your)", "AI-first means every workflow starts from the question of what the model should do and what the human should verify: I design systems where agents draft, retrieve and act with tool access, humans own the quality gates, and nightly evals keep regressions out. It is also how I work personally - Claude for coding and design, GPT for testing, Cursor for general coding, Perplexity for research - every day."),
 (r"countries .{0,30}(right|authori[sz]ed|eligible) to work|(right|eligib\w+) to work|which countr|what countr", "United States"),
 (r"compensation expectations?|salary expectations?|(desired|expected|target) (annual )?(salary|compensation|comp\b|base)", "$220,000 - $350,000 (negotiable, depending on scope)"),   # applicant (2026-10-03): broad $220-350K; must outrank the employer-name rules below
 (r"(generative )?ai tools?.{0,80}(involved|used|assist\w*).{0,60}(application|applying|candidacy)|platforms and techniques.{0,60}ai|ai.{0,30}(involved|used) in (your|this) application", "AI tools are part of my daily engineering workflow: Claude for coding and design, GPT for testing, Cursor for general coding, Lovable for prototyping, and Perplexity for research. For this application I used AI-assisted tooling to help prepare and fill the form from my own resume and background, and I reviewed and stand behind every answer."),   # applicant (2026-10-02): honest AI-in-application disclosure
 (r"use of ai tools?|which ai tools|ai tools (do you use|in your (work|workflow|day))|how (do|often do) you use ai|experience (with|using) ai tools", "Daily. Claude for coding and design, GPT for testing, Cursor for general coding, Lovable for prototyping, and Perplexity for research - alongside the agentic AI platform I build at Hyperion AI."),   # applicant (2026-10-02): daily AI stack
 (r"^company name|^(most recent |current )?(company|employer)( name)?$|name of your .{0,30}(company|employer)|(current|most recent|last) .{0,20}(company|employer)", P["org"]),
 (r"start (date )?year|^from year|start \(year\)", "2023"),
 (r"end (date )?year|^to year|end \(year\)", "2026"),
 (r"if (you answered|yes,? please|applicable)|not applicable|type 'n/a'|government entity|please (list|specify|explain).*(if|when) (yes|applicable)", "N/A"),
 (r"^(street |home |mailing )?address", P["location"]),
 (r"linkedin|linkedln", P["linkedin"]),(r"github|git (repo|repository|profile)|url to your git", P["github"]),(r"portfolio|website|personal site", P["github"]),
 (r"current (company|employer)|most recent (company|employer)|^company$|^employer$", P["org"]),
 (r"^(?!.*\b(how|describe|explain|tell us|ways?)\b).*(current (title|role)|job title|^title$)", "CTO & Technical Co-Founder / Principal Architect"),
 (r"^(current |your |home )?location\b|^city\b|where (are you|do you) (based|live|located)", P["location"]),
 (r"salary|compensation|pay expectation|desired (base|comp)|expected (base|salary|comp)", "$220,000 - $350,000"),   # applicant (2026-10-03): broad $220-350K
 (r"today'?s date|date of application|application date|date \(mm/dd/yy", time.strftime("%m/%d/%y")),
 (r"^(?!.*\b(how|describe|explain|tell us|ways?)\b).*current (occupation|job title|title|role|position)|^occupation|your occupation|what do you (currently )?do for work", "CTO"),   # applicant's answer
 (r"earliest .{0,50}start|when .{0,40}(start|join|begin)|start date|available to start|availability", "Immediately (available to start right away)"),   # applicant: current role at Hyperion AI, two weeks' notice
 (r"(what is |what's )?your current location|current location|where (are|do) you (currently )?(located|based|live|living|reside)|city,? state", "Santa Clara, California"),   # applicant's answer
 (r"sponsor", "No sponsorship required. I am a US citizen."),   # applicant's answer
 (r"citizenship|citizen", "US Citizen"),
 (r"dog or a ghost|ghost or a dog", "Dog. Loyal to the team, curious about everything, and always shows up with energy."),   # applicant's choice (Miter)
 (r"what city|which city|city (do|are) you (currently )?(live|living|based|located)", "Santa Clara, CA"),
 (r"where in the (united states|us|u\.s\.) will you (be )?work|desired (work )?location|preferred (work )?location|work location|where will you (be )?work(ing)? from", "Santa Clara, California"),   # applicant's answer   # applicant's answer
 (r"physical technology|invented in the last \d+ years|invention (do you|you) (most )?admire|technology .{0,30}(most )?admire", "The railroad, together with the electrical switch and the light bulb. Railroads turned distance into a schedule, switches made control programmable, and the light bulb turned time into something we design around; the same systems thinking is what I bring to software."),   # applicant's picks
 (r"customer feedback .{0,60}(feature|roadmap|product)|feedback .{0,40}translated? .{0,40}(feature|roadmap)", "At JPMorgan Chase and Morgan Stanley I led technical leads and architects delivering trading and application platforms directly with client and trading-desk teams, so their feedback on latency, reliability and workflow went straight into the roadmap: we prioritised the execution-path and tooling changes they asked for and shipped them in phased releases with the desks validating each step. Later, at Cadence and Ankr, I was the architect embedded with customer-facing engineering, turning recurring customer requests into platform features, and at Hyperion AI I work directly with early users to decide what the agentic platform builds next."),   # based on the applicant's resume
 (r"shipped in the last|thing you shipped|something you (recently )?shipped|what did you personally own|recent project where you served as a technical leader|drove architectural direction|production ai or llm[- ]based system you personally|ai or llm[- ]based system you (personally )?(designed|built|shipped)", 'Most recently, as CTO and Technical Co-Founder at Hyperion AI, I built our agentic platform end to end: MCP clients and servers (3 servers, 9 tools), a multi-agent plan-validate-dispatch-replan loop, open-weight model serving (Qwen, Llama 3.3-70B, gpt-oss) through llama.cpp and vLLM paths, and a reproducible 121-measure benchmarking scorecard informed by MLPerf Inference and BFCL, running in production with correctness gates, replay harnesses and OpenTelemetry/Prometheus observability.'),
 (r"anything unusual in your background|unusual (about|in) your background|what sets you apart|unique about your background", 'My background spans three worlds that rarely meet in one person: sub-millisecond trading systems at JPMorgan Chase and Morgan Stanley, a consumer platform at Yahoo Finance serving about 40M daily and 150M monthly users, and hands-on agentic AI as CTO and Technical Co-Founder of Hyperion AI. I still write critical-path Python, Rust, C++ and Go, so I can lead the architecture and build the hardest parts myself.'),
 (r"excited to apply|why .{0,20}excited|excites you about (this|the) (role|company|position)", ANS.get("why_us","")),
 (r"example of (outstanding|exceptional|your best) work|outstanding work|proof of excellence|evidence of excellence", ANS.get("impact","")),
 (r"right hire|right (person|fit|candidate) for (this|the) (role|position)|why should we hire you|why (are you|you're) a (great|good|strong) fit", ANS.get("why_us","")),
 (r"(most recent )?team you('re| are) (currently )?managing|team you manage|project you('re| are) involved in", "At Hyperion AI I lead a small founding engineering team as CTO and Technical Co-Founder. Our current project is the agentic platform: multi-agent orchestration (plan, validate, dispatch, replan), MCP servers and tools, open-weight model serving through vLLM and llama.cpp, and an evaluation scorecard that gates every release. Technically I own the architecture and write the critical-path orchestration and serving code myself; before this, at Yahoo Finance, I directed 75+ engineers and partners through the platform's bare-metal-to-AWS modernization."),
 (r"staying technically hands[- ]on|stay(ing)? hands[- ]on|how (do you|are you) stay(ing)? technical", 'I still write critical-path code every week in Python, Rust, C++ and Go: at Hyperion AI I built the agent orchestration loop, the MCP servers and the model-serving paths myself, and I run our benchmarking and evaluation harness. I review designs line by line and keep a personal lab for open-weight models (vLLM, llama.cpp) so my architecture calls stay grounded in what actually runs.'),
 (r"complex(est)? .{0,40}(infra|infrastructure) tooling|built with (infra|infrastructure) tooling|terraform, kubernetes|with terraform|kubernetes, pulumi", "The largest was Yahoo Finance's bare-metal-to-AWS modernization, which I architected as Chief Architect: a platform serving about 40M daily and 150M monthly users moved in phases with infrastructure as code (Terraform), containerised services on Kubernetes, and CI/CD pipelines, with cutover and rollback plans so no market-hours outage was possible. The hard part was not the tooling but sequencing 75+ engineers and partners through dual-running, data migration and traffic shifting safely."),
 (r"city from which you plan|city you plan (on|to) work|plan on working from", 'Santa Clara, CA'),
 (r"most complex enterprise cloud|enterprise cloud deployment|cloud (deployment|platform) you('ve| have) been responsible|most complex distributed or cloud|most complex (distributed|cloud-based|backend) (or cloud-based )?(backend )?system", 'As Chief Architect at Yahoo Finance I was responsible for moving the Finance platform (quotes, charts, portfolios, screeners, research; about 40M daily and 150M monthly users) from bare metal to AWS: architecture, phased migration, cutover and rollback planning, and 24x7 operation, directing 75+ engineers and partners. Earlier at JPMorgan Chase I architected multi-asset execution platforms designed for the 100K-500K TPS range.'),
 (r"ideal start-?date|start-date|when would you like to start", 'Immediately'),
 (r"in-?person 5x a week|5x a week|five days a week|5 days a week", 'I am based in the SF Bay Area (Santa Clara) and can work hybrid in San Francisco; I am not looking for a five-days-a-week in-office role.'),
 (r"fastest .{0,20}measurable outcome|measurable outcome you (initiated|delivered)|most measurable (impact|outcome)", 'In the past 12 months at Hyperion AI I initiated and delivered a reproducible 121-measure benchmarking scorecard for our agentic platform (informed by MLPerf Inference and BFCL). Within weeks it became the gate every model and release had to pass, which let us swap open-weight models and serving paths with evidence instead of guesswork.'),
 (r"client-?facing experience|customer-?facing experience", 'Extensive: at JPMorgan Chase and Morgan Stanley I delivered trading platforms directly with client and trading-desk teams, at Cadence and Ankr I was the architect embedded with customer-facing engineering, and at Hyperion AI I work directly with early users.'),
 (r"resource[- ]constrained|scoped an? solution|limited (resources|budget)|constrained (setting|environment)", "At Hyperion AI we had a startup's budget but needed production-grade agent reliability. Instead of paying for the largest hosted models on every call, I scoped the problem around what users actually asked: I built a small benchmarking scorecard first, then served open-weight models (Qwen, Llama 3.3-70B, gpt-oss) through llama.cpp and vLLM on hardware we controlled, routed only the hard planning steps to larger models, and added validation and replay so cheaper models could be trusted. It made sense because the constraint was cost and latency, not capability, and the scorecard let us prove each trade-off before shipping it."),
 (r"(explain|describe) .{0,40}data engineering .{0,40}non-technical|data engineering to a non-technical", "Data engineering is the plumbing and quality control behind every number and AI answer a company relies on. Data arrives from many places (apps, sensors, partners) in messy, inconsistent forms. Data engineers build the pipelines that collect it, clean and standardise it, check it for errors, and store it so analysts, dashboards and AI models can use it with confidence. The process is: capture the data, move it reliably, transform it into a consistent shape, validate it, and serve it to the people and systems that need it, while monitoring every step so problems are caught before they reach a decision."),
 (r"describe how you use ai tools|how you would apply ai to improve the role|use ai tools in your work today|^(?!.*(this application|this form|to apply|applying|cover letter|resume)).*how (you have|have you|do you|you) (used?|leverag\w+) (ai|llm|generative ai)(-assisted| assisted)?( engineering| coding| development| software)? tools", "Every day. I use Claude Code for code analysis, debugging, test generation and parallel subsystem reviews, open-weight models (Qwen, gpt-oss, Llama) through llama.cpp and vLLM for agent work, and RAG for research. A specific example: at Hyperion AI I used Claude Code for parallel reviews of the benchmark platform's subsystems and to generate its test and replay harnesses, which let a very small team build and keep correct a 121-measure scorecard with 13 comparability checks. In this role I would apply the same discipline: AI-assisted development behind evaluation and review gates, and model features measured offline on versioned datasets before they reach users."),
 (r"platform or foundational service|foundational (service|platform|system) you (designed|built)|other engineers built on top", "At JPMorgan Chase I led the low-latency multi-asset trading infrastructure and extended its lock-free journal protocol so execution events were also published as real-time JSON/XML streams. The problem: risk analytics, regulatory reporting, post-trade reconciliation and settlement all needed the same trade events, reliably and in order. The trade-off was that the journal sat on a sub-250-microsecond execution path, so publishing could never slow execution: I kept it off the hot path with ring buffers, zero-copy hand-off and bounded queues, made the journal the source of truth that consumers could replay from, and versioned the message formats. Other teams then built their risk, reporting and reconciliation flows on those streams, and the same journals drove our replay and backtesting engines for recovery and incident reconstruction."),
 (r"multi-tenant .{0,80}single-tenant|single-tenant .{0,60}(government|gov)[- ]?cloud|hardest platform (problems|challenges)", "The hardest problems: 1) One codebase and release train across many isolated deployments: per-deployment configuration instead of forks, automated provisioning (Terraform/Kubernetes), and upgrades rolled out with canaries and per-deployment rollback. 2) Tenancy assumptions hidden in the data layer (tenant filters, shared caches, background jobs, search indexes, analytics) that must still hold when the deployment itself is the boundary. 3) Government-cloud constraints: no calls out to shared SaaS services (LLM APIs, telemetry, email), FIPS-validated cryptography, customer-managed keys, and restricted operator access. 4) Observability and support without direct access: telemetry that can leave the boundary, and runbooks the customer's operators can follow. 5) AI features whose models must run inside the boundary. I have built comparable isolation before: entitlement infrastructure at Cadence (over 2 million daily license checkouts) and multi-tenant white-label onboarding with isolated ledger-backed audit trails at Hyperion AI."),
 (r"faster or cheaper at scale|(faster|cheaper) .{0,30}not just correct", "At Hyperion AI we served open-weight models (Qwen, gpt-oss, Llama 3.3-70B) for our agents, and multi-step tasks were too slow and too costly per task. The trade-off was answer quality against latency and cost per task. I profiled prefill and decode throughput, time to first token, time per output token, memory and serving slots, and separated model, tool and orchestration time. Then I changed what the data pointed to: mixture-of-experts models (35B total, 3B active) for most agent roles, per-role model endpoints so only the hard steps went to the large model, bounded reasoning and output budgets, and llama.cpp serving-slot and CPU-allocation tuning. A 121-measure scorecard with 13 comparability checks guarded quality, so faster never quietly meant worse."),
 (r"ambiguous problem|no clear spec|without a (clear )?spec|scoping something yourself", "At Hyperion AI the question was simply which open models we could run for our agents, with no spec. I decided what to build by first writing down the decisions it had to support (which model for each agent role, on what hardware, at what latency and cost), then built the smallest thing that could answer them: a reproducible benchmark harness with run manifests and JSONL traces, before any UI. The first comparisons showed that results were not comparable across runs, so I scoped the 121-measure scorecard and 13 comparability checks next. The UI, saved-run comparisons and live agent timelines came last, once people were using it for engineering reviews."),
 (r"built inside a customer'?s environment|inside (a|the) (customer|client)'?s? (environment|infrastructure)", "At Hyperion AI I built white-label KYC/AML onboarding for institutional partners: Canton/Daml issuer, holder and verifier contracts, DID credentials, Plaid verification and isolated ledger-backed audit trails. It was harder than building in our own stack because the partner's rules came first: their identity, network and key-management requirements; security review before every change; and debugging through their logs and their people rather than ours. I designed for that from the start: configuration instead of forks, a separate audit trail per partner, and replayable evidence so we could reproduce issues outside their environment."),
 (r"(worked on|built) that you were proud of|something you('re| are) proud of|favou?rite projects?", ANS.get("impact","")),
 (r"infrastructure that supported ai agents|autonomous workflows|dynamically generated and executed tasks", "Yes. At Hyperion AI I built the infrastructure our agents ran on: an MCP client and 3 MCP servers exposing 9 tools; plan-validate-dispatch-observe-replan loops with reasoner and verifier roles and per-role model endpoints; and a coordinator-controlled action boundary with role-based allowlists, JSON-schema validation, execution budgets and approval-gated actions, so tasks the agents generated were validated before they ran and every tool outcome was traceable. I also built the evaluation platform with live agent timelines and replayable traces."),
 (r"earliest month|month you('d| would) be able to (join|start)", "October 2026 (two weeks' notice)"),
 (r"what type of visa|visa are you currently on", "Not applicable. I am a US citizen and need no visa or sponsorship."),
 (r"current or most recent (role|job|position) title|most recent (job )?title|current \(?or most recent\)? ?(job |role |position )?title|^current (job )?title", "CTO & Technical Co-Founder, Hyperion AI"),
 (r"where are you physically (based|located)|where are you based\??$", "Santa Clara, California"),
 (r"employee is selected .{0,40}employee name|provide the employee('s)? name", "N/A"),
 (r"open to relocat(e|ion)( for this role)?\??$|willing to relocate( for this role)?\??$", "Yes. I live in Santa Clara, California (SF Bay Area) and I am willing to relocate to New York City; in the Bay Area I can work on-site or hybrid in San Francisco and the South Bay."),   # applicant: will move to NYC
 (r"complex customer or operational problem .{0,40}(production|technical) solution|turned into a production (technical )?solution", "At Cadence Design Systems, high-value software was being accessed without reliable entitlement checks, an operational and revenue problem for the business and its enterprise customers. I architected and delivered an asymmetric-encryption license-validation platform in C++17: cryptographic identity, REST authentication, secure token flows, MariaDB/Cassandra storage and Kubernetes automation. It went into production supporting more than 2 million daily enterprise license checkouts, with auditability and operational recovery built in, so customers kept working through failures while access stayed protected."),
 (r"caught your attention|made you want to join|drew you to (us|apply)", ANS.get("why_us","")),
 (r"incorporating ai into your (day|daily|work)|how (are )?you (are )?(incorporating|using) ai (in|into) your", "I use Claude Code every day for code analysis, debugging, test generation and parallel subsystem reviews, with every change still going through review and tests. I run open-weight models (Qwen, gpt-oss, Llama) through llama.cpp and vLLM to build and evaluate agents, and use RAG for research. I measure all of it against a scorecard, so AI speeds up the work without lowering the bar."),
 (r"senior mle and a principal mle|senior (ml|machine learning) engineer and a principal", "- Scope: a senior MLE fixes the failing model (retrains, patches features, adds an alert); a principal MLE asks why this class of failure was possible and fixes it for every model on the platform with data contracts, drift monitoring and shared evaluation gates.\n- Evidence: a senior MLE validates the fix on the incident's data; a principal MLE defines the reliability metrics, SLOs and regression suites that decide when any model may ship or must roll back.\n- Leverage: a senior MLE owns the resolution; a principal MLE aligns product, data and infrastructure owners on the cost, latency and accuracy trade-offs, records the decision, and leaves tooling that others use to prevent recurrence."),
 (r"system from your resume you know best|give us the real numbers", "Yahoo Finance's quotes, charts and research platform, where I was Chief Architect for the bare-metal-to-AWS modernization: about 40M daily and 150M monthly active users, and tick-to-quote streaming latency as low as about 5 ms. I cannot quote Yahoo's internal cost figures; the design leaned on aggregation and caching in the market-data path to keep peak-hour load efficient. For the AI research assistants built on it (OpenAI/LangChain RAG over news, filings and fundamentals) I tracked answer quality with LLM observability and drift detection (OpenTelemetry, Prometheus, Grafana), with PII masking and bias audits as release gates. At Hyperion AI I tracked model quality with a 121-measure scorecard and 13 comparability checks alongside time to first token and time per output token."),
 (r"used agentcore|agentcore", "Not in production. My agent work at Hyperion AI used my own MCP client and servers (3 servers, 9 tools) with a coordinator-controlled plan-validate-dispatch-replan loop, and I evaluated LangGraph, CrewAI and AutoGen integration paths. I have not shipped a project on Bedrock AgentCore, but its runtime, memory, gateway and identity pieces map directly onto what I built, and I would be productive on it quickly."),
 (r"^years of (industry |professional |relevant |total |work |software |engineering )?experience\??$|how many years of (industry |professional |relevant |total |work )?experience", "25"),   # applicant: 25 years
 (r"(visa|immigration|citizenship|work authori[sz]ation|employment authori[sz]ation) status", "US citizen. I do not need a visa or any sponsorship, now or in the future."),   # applicant: no sponsorship needed
 (r"^(twitter|x)( ?/ ?(x|twitter))?( account| handle| profile| url)?\??$", "N/A"),
 (r"(know|related to) anyone .{0,40}(works|working) (at|for)|relatives? (who )?work(s)? (at|for)", "No."),
 (r"signed a non-?compete|non-?compete agreement", "No. I have no non-compete agreement that would restrict me from working for your company."),
 (r"size of the (engineering )?(organi[sz]ation|org|team) (for which|that|you)|(largest|biggest) (engineering )?(organi[sz]ation|org|team) you('ve| have) (led|managed)|how (large|big) (an? |of an? )?(engineering )?(organi[sz]ation|org|team) have you (led|managed)", "75+ engineers, managers and partners at Yahoo Finance, which I directed as Chief Architect; before that a 50+ organization at JPMorgan Chase across the U.S., U.K. and India, and today a founding team of 15+ as CTO of Hyperion AI."),
 (r"do you have direct reports|how many direct reports|number of direct reports", "Yes. As CTO of Hyperion AI I lead a founding team of 15+; at Yahoo Finance I directed 75+ engineers, managers and partners, and at JPMorgan Chase a 50+ organization across the U.S., U.K. and India."),
 (r"relocate to (singapore|hong ?kong|london|europe|india|asia|canada|toronto|dubai)", "No. I am based in the San Francisco Bay Area and am looking for roles in the US: the Bay Area, New York, or remote."),
 (r"devops problem you solved using an ai|(devops|infrastructure|ci/?cd|operations) problem .{0,40}(ai|ml|machine learning) (tool|technique)", "At Hyperion AI our benchmark and agent services needed reliable CI and fast triage when runs regressed. Tools: Claude Code, plus open-weight models served through llama.cpp. What I built myself: Claude Code prompts and parallel subsystem reviews wired into our debugging and test workflow, the test and replay harnesses it helped generate, and a comparability gate (13 checks over a 121-measure scorecard, with run manifests and JSONL traces) that fails a run when model, workload or measurement settings drift. Outcome: regressions were caught at the gate, with the trace that explained them, instead of surfacing in engineering reviews, and a very small team kept the platform correct as it grew."),
 (r"what is your (current )?location|your location\??( \(city)?|location \(city(,| &| and) state\)|city (,|&|and) state", "Santa Clara, California"),
 (r"(architectural )?bottleneck you.{0,4}(ve|have) resolved|most complex .{0,30}bottleneck", "At Yahoo Finance, quotes for web and mobile (about 40M daily users) had to stay fresh at the market open, when load spikes. The bottleneck was the read path: client requests fanned out to per-symbol lookups behind the market-data services. I re-architected it as tick ingestion, normalization and aggregation feeding a cache tier that streams updates to clients, so reads were served from memory rather than recomputed per request. The result was tick-to-quote latency as low as about 5 ms, and the design carried peak hours through the move from bare metal to AWS."),
 (r"preferred (technology )?stack for|technology stack .{0,40}scalable (cloud )?backend", "Go or Rust (Tokio) for latency-critical services, Python/FastAPI for AI and orchestration, gRPC between services with REST and WebSockets at the edge, Kafka or Redpanda for events, Postgres plus Redis, and Kubernetes with Terraform on AWS or GCP, observed through OpenTelemetry, Prometheus and Grafana. Why: predictable latency and memory where it matters, fast iteration where it does not, explicit API and event contracts, replayable events for recovery, and infrastructure defined as code."),
 (r"integrated (large language models|llms?)|llms? or agentic workflows into", "Yes. At Hyperion AI I built a browser-based model-and-agent evaluation platform (Python backend, llama.cpp and vLLM model endpoints) with interactive chat, benchmark jobs and live agent timelines; its agents use an MCP client and 3 MCP servers (9 tools) with plan-validate-dispatch-replan loops. At Yahoo Finance I architected OpenAI/LangChain RAG research assistants (filing explainers, earnings summaries, stock comparisons) over news, SEC filings and fundamentals, with Pinecone and RedisVector for retrieval."),
 (r"have you founded a company|founding/early engineer|taken a product from inception", "Yes. I co-founded Hyperion AI (CTO & Technical Co-Founder, 2023-2026) and built its AI-powered digital-asset platform from inception with a 15+ founding team, through to institutional partners; before that I co-founded Motocho (2021-2022) and built its smart order routing platform."),
 (r"which ai/?llm/?agent tools have you used|ai/llm usage|ai tools have you used in the last", "Claude Code - daily: code analysis, debugging, test generation and parallel subsystem reviews. Open-weight models (Qwen, gpt-oss, Llama) through llama.cpp and vLLM - daily: building and benchmarking agents. MCP (my own client and 3 servers) - daily: tool access for agents. Hugging Face - weekly: sourcing and validating GGUF model artifacts. LangChain / LangGraph - weekly: RAG and agent-framework evaluation. CrewAI, AutoGen and OpenClaw - occasional: interoperability evaluation."),
 (r"ai/llm impact|two specific examples where ai improved", "1) Speed and quality of engineering: at Hyperion AI I used Claude Code for parallel reviews of the benchmark platform's subsystems and to generate its test and replay harnesses. I was trying to keep a fast-growing evaluation platform correct with a very small team; the result was that regressions were caught by tests and the comparability gate before they reached engineering reviews. 2) Decision-making: when choosing models for our agents I used the platform itself (open-weight models, a 121-measure scorecard and 13 comparability checks) to compare candidates on the same workloads. That replaced opinion with evidence and led us to mixture-of-experts models with per-role endpoints and bounded reasoning budgets, chosen on measured quality, latency and memory rather than headline model size."),
 (r"(which|what) (location and )?time ?zone will you (be )?work|location and time ?zone|time ?zone will you be working from", "Santa Clara, California (Pacific Time); comfortable overlapping with Eastern Time hours."),
 (r"(pipeline|automation|system) you built that you.{0,6}d design differently|design differently today|what (specifically )?changed your mind", "The first version of the model-benchmark pipeline I built at Hyperion AI logged flat metrics per run. When we started comparing models the numbers were not comparable: runs differed in model build, quantization, serving slots, prompt and output budgets, and even in what the timer included. What changed my mind was seeing two supposedly identical runs disagree for reasons the data could not explain. Today I would start where we ended: a run manifest that pins model identity, workload and settings; JSONL task and trace records; explicit measurement boundaries (model versus tool versus orchestration time); and comparability checks that reject a comparison before anyone reads a chart. It is the same lesson I learned earlier in trading systems with journals and deterministic replay: capture enough context to reproduce the result, not just the result."),
 (r"data platform you owned end to end|owned end to end .{0,40}(ingestion|etl)", "At Yahoo Finance I was Chief Architect of the financial data platform behind quotes, charts, portfolios, screeners and research: tick ingestion, normalization and aggregation, caching and streaming (tick-to-quote as low as about 5 ms), plus the research data (news, SEC filings, fundamentals and historical prices) that fed screeners, portfolio analytics and the natural-language research tools editorial and product teams used every day. My specific role was setting the service boundaries, data contracts and the bare-metal-to-AWS migration plan, and staying hands-on in the critical paths. Technologies: AWS, Kubernetes and Terraform; event streaming, Redis and Cassandra for serving; Spark/Flink-style batch and stream processing; TensorFlow/TFX for the analytics models; OpenTelemetry, Prometheus and Grafana for observability."),
 (r"explain an architecture trade-?off to non-technical leadership|trade-?off to (non-technical|business) (leaders|leadership|stakeholders)", "At Yahoo Finance the question was how to move the Finance platform from bare metal to AWS: one large cutover or a phased migration by product area. The trade-off was speed against risk to a platform used by about 40 million people a day during market hours. For product and business leaders I framed it in their terms: what a failed market open would cost in users and trust, against a somewhat longer timeline, and I showed a phased plan with a rollback path at every step and evidence from dry runs. That is how we ran it: a phased migration with explicit cutover and rollback plans and 24x7 operation, aligned with product, legal, security and compliance."),
 (r"have you managed direct reports|managed direct reports\? if so", "Yes. As CTO of Hyperion AI (2023-2026) I led a founding team of 15+; at Yahoo Finance (2022-2023) I directed 75+ engineers, managers and partners; and at JPMorgan Chase (2014-2016) I led a 50+ organization across the U.S., U.K. and India."),
 (r"what is your (current )?age|^your age$|^age$|current age|how old are you", "50"),   # applicant: age 50
 (r"(other|different) teams (started|began) using|teams .{0,20}(adopted|picked up|started using) .{0,20}on their own|something you built that (other|different) (teams|people|groups)", "At Yahoo Finance I built natural-language research workflows (RAG over financial news, company fundamentals and historical data). They were built for editorial work, and product teams took them up for their own research as well. I think they did because the tools answered questions people already asked every day, in seconds, from data they already trusted, showed their sources, and needed nothing to install or learn."),
 (r"what kind of teams have you managed|teams you('ve| have) managed|size and type of teams", "Engineering organisations and platform teams: at Yahoo Finance I directed 75+ engineers and partners (backend, data, SRE and front-end) through the platform's AWS modernisation; at JPMorgan Chase and Morgan Stanley I led technical leads and architects building trading and application platforms; at Hyperion AI I lead a small founding engineering team building agentic AI."),
 (r"something you('re| are) learning|what are you learning|currently learning", 'Post-training and inference efficiency for open-weight models: fine-tuning and evaluation workflows, and serving optimisations in vLLM and llama.cpp, so I can run agent workloads with smaller models without losing quality.'),
 (r"past experiences? or projects? (are )?most relevant|most relevant (experience|project)|relevant to the work you will do", ANS.get("impact","")),
 (r"interface or workflow you('ve| have) built that integrated ai|integrated ai capabilities|workflow .{0,30}advanced automation", 'At Yahoo Finance I architected the OpenAI/LangChain RAG research assistants that sit inside the Finance experience, and at Hyperion AI I built the agentic platform (plan-validate-dispatch-replan agents calling MCP tools). The main challenge in both was trust: answers had to be grounded in the right data and fail safely. I solved it with retrieval over curated sources, validation steps before any action, replay harnesses, and an evaluation scorecard that gated every release.'),
 (r"ux or design decision|more intuitive for non-technical users|intuitive for non-technical", 'For the Yahoo Finance research assistants the key decision was to put the assistant inside the pages investors already used, grounded in the same market data they were looking at, instead of a separate chat tool. People could ask plain-language questions in context, and the answers stayed tied to the data on the page, which made the tool feel familiar and trustworthy to non-technical users.'),
 (r"most challenging project|hardest project|most difficult project", ANS.get("impact","")),
 (r"background or future goals align|how does your background align|align with (our|the) (mission|company)", ANS.get("why_us","")),
 (r"llm inference ecosystem|vllm, sglang|experience with (vllm|sglang|llm serving|inference serving)", 'Hands-on: at Hyperion AI I serve open-weight models (Qwen, Llama 3.3-70B, gpt-oss) through vLLM and llama.cpp paths in production, and I built a reproducible 121-measure benchmarking scorecard informed by MLPerf Inference and BFCL to compare models, quantisations and serving configurations on latency, throughput and task quality before each release.'),
 (r"any deadlines|deadlines we should be aware", 'No hard deadlines. I am actively interviewing and can move quickly.'),
 (r"specific information on how you heard|what job board did you use|where was the job ad posted", "I found it on the company's Ashby job board while searching for senior engineering roles at AI and infrastructure startups."),
 (r"lead you to apply|led you to apply|made you apply|why did you apply", ANS.get("why_us","")),
 (r"how have you used ai in the last|used ai (recently|lately)|how do you use ai (day to day|daily|in your work)|how do you use (artificial intelligence|ai|ai tools) in your (everyday|daily|day-to-day) (work|life)", 'Daily: building and evaluating agents at Hyperion AI, running open-weight models locally through vLLM and llama.cpp, and using coding assistants for refactors and test generation, always with review and evaluation gates.'),
 (r"ai-powered (product )?feature you.{0,4}(ve|have) (recently )?shipped|recently shipped .{0,30}ai", 'Most recently, as CTO and Technical Co-Founder at Hyperion AI, I built our agentic platform end to end: MCP clients and servers (3 servers, 9 tools), a multi-agent plan-validate-dispatch-replan loop, open-weight model serving (Qwen, Llama 3.3-70B, gpt-oss) through llama.cpp and vLLM paths, and a reproducible 121-measure benchmarking scorecard informed by MLPerf Inference and BFCL, running in production with correctness gates, replay harnesses and OpenTelemetry/Prometheus observability.'),
 (r"2-3 sentences .{0,30}interest|describing your interest in|your interest in (the company|us)", ANS.get("why_us","")),
 (r"legal full name|full legal name|^legal name|(enter|type) your full name|^your full name|^full name|^(please )?(enter|type|provide) your name\b", P["name"]),
 (r"authori[sz]ed to (lawfully )?work in the (united states|us|u\.s\.)|work authori[sz]ation status", "Yes. I am a US citizen and need no sponsorship."),
 (r"^middle (name|initial)|middle name", "N/A"),
 (r"(served|serve|service|served in|been in) (in )?(the )?(military|armed forces|u\.?s\.? military)|military (service|experience|background)", "No, I have not served in the military."),
 (r"snack|favou?rite (food|coffee|drink|song|movie|book|meal)|fun fact|hobby|hobbies|for fun|outside of work|guilty pleasure|spirit animal|superpower", "Whatever is on the table: the ideas come from the problem, not the snack. Outside of work I read widely and tinker with open-weight models on my own hardware."),
 (r"able to travel|willing to travel|travel (for|requirements?|expectations?)|percentage of travel|% travel|days of travel|involve .{0,40}travel|travel (each|per|a) (month|week|quarter)|comfortable with .{0,20}travel", "Yes, I am comfortable with that and can travel as needed for the role."),
 (r"timeline for (starting|a new)|when (can|could|would) you (be able to )?(start|join)|how soon (can|could) you", "About two weeks after an offer: I am currently CTO at Hyperion AI and would give two weeks' notice."),
 (r"located near our offices?|(relocate|willing to relocate) or commute|able to commute|commut(e|ing) to (our|the) office", "Yes. I am based in Santa Clara, CA (SF Bay Area) and can commute to the office; open to relocating for the right role."),
 (r"know anyone (who works|at|employed)|anyone you know (works|at)|friends or family (at|who work)", "No"),
 (r"(average |typical |largest )?size of (the )?teams? (you've|you have|you) (managed|led)|how many (people|engineers|direct reports|reports) (have you|do you|did you) (managed|manage|lead|led)|team size|number of direct reports", "It varies by role: as Chief Architect at Yahoo Finance I directed 75+ engineers and partners across the platform modernization program; as CTO and Technical Co-Founder at Hyperion AI I led a small founding engineering team hands-on."),
 (r"start date|available to start|availability|notice period", "Immediately (available to start right away)"),
 (r"years? of (relevant |professional |total )?experience|how many years", "25"),
 (r"when (can|could|would|are you able to) you (realistically |potentially |ideally )?start|start date|earliest (start|availability)|available to start|notice period|availability to start|how soon", "Immediately (available to start right away)"),
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
 (r"through other (technical )?leaders|developing (tech lead managers|managers|leaders)|manag(e|ing|ed) managers|lead(ing)? leaders|leaders of leaders|multi-?level (org|organi[sz]ation)", "At Yahoo Finance, as Chief Architect, I led a 75+ person organization of engineers and partners through tech leads and managers during the bare-metal-to-AWS modernization: I set the architecture and technical direction across sub-teams, grew engineers into tech leads, and held the leads accountable for delivery while staying hands-on in design reviews, critical-path code and production readiness. As CTO and Technical Co-Founder at Hyperion AI I built the founding team, set direction for model serving, agent orchestration and evaluation, and still write critical-path code in Python, Rust, C++ and Go."),
 (r"largest[- ]scale|biggest (system|scale)|scale (of|at which) .{0,40}(system|built|operated)|requests/sec|requests per second|\bQPS\b|\bTPS\b|\bTPM\b|\bDAU\b|data volume|highest[- ]scale|scale you.ve (built|operated|worked)", "Largest scale: at Yahoo Finance I was Chief Architect for a platform serving roughly 40M daily and 150M monthly active users (quotes, charts, portfolios, screeners, research), leading its bare-metal-to-AWS modernization with 75+ engineers and 24x7 operation. Earlier at JPMorgan Chase I architected sub-250-microsecond multi-asset execution paths designed for the 100K-500K TPS range. Most recently at Hyperion AI I built the agentic platform end to end (multi-agent orchestration, open-weight model serving via vLLM and llama.cpp, evaluation and observability) with production correctness gates."),
 (r"career summary|professional summary|summary of (your )?(career|experience|background)|brief (bio|background|summary)|short bio|about you$|tell us about your background", 'Engineering leader and hands-on architect with 25+ years building production systems and 10+ years leading engineers, architects and solutions teams. CTO and Technical Co-Founder at Hyperion AI: built the agentic AI platform end to end (multi-agent orchestration, MCP servers and tools, open-weight model serving through vLLM and llama.cpp, evaluation and observability). Chief Architect at Yahoo Finance: led the bare-metal-to-AWS modernization of a platform serving about 40M daily and 150M monthly users, directing 75+ engineers and partners, and built the first LLM/RAG research assistants. Earlier VP / Lead Architect at JPMorgan Chase (sub-250-microsecond multi-asset execution paths) and Technical Lead at Morgan Stanley. Writes Python, Go, Rust and C++; US citizen based in Santa Clara, CA.'),
 (r"most recent (production )?(software )?project|recent project you (worked|built|shipped)|describe (a|the) (recent|technical|significant) project|project you.re (most )?proud|proudest (technical )?(work|project|achievement)", "Most recently I built Hyperion AI's agentic platform end to end: MCP clients and servers (3 servers, 9 tools), a multi-agent plan-validate-dispatch-replan loop, open-weight model serving (Qwen, Llama 3.3-70B, gpt-oss) through llama.cpp and vLLM integration paths, fine-tuning and evaluation workflows, and a reproducible 121-measure benchmarking scorecard informed by MLPerf Inference and BFCL. It runs in production with correctness gates, replay harnesses and observability (OpenTelemetry, Prometheus/Grafana)."),
 (r"^(?!.*(employment gap|gaps? in|incident|outage|\bgpu\b|camunda|bitcoin|lightning|referral|^if (yes|other|so)\b|if you are not sure))(?:.*)(experience (managing|leading|building|running|owning|with|in).*(explain|describe|elaborate|tell us)|please (explain|describe|elaborate)|describe your (experience|background|leadership)|tell us about your (experience|background|leadership)|walk us through|what is your experience (leading|managing|with|in|building|running|owning)|share (an example|your experience))", "As CTO & Technical Co-Founder at Hyperion AI (2023-2026) I built and led the engineering team and owned customer-facing deployments end to end, from architecture through production rollouts with customers. Earlier, as VP / Lead Architect at JP Morgan Chase and VP / Technical Lead at Morgan Stanley, I led technical leads and architects delivering trading and application platforms directly with client and trading-desk teams, and at Cadence and Ankr I was the architect embedded with customer-facing engineering. In total 25+ years of hands-on engineering and 10+ years leading engineers, architects, and solutions-oriented teams."),
 (r"greatest (impact|achievement)|proudest|accomplishment|most exceptional|exceptional thing|most impressive (thing|work|project)|biggest (achievement|win)|achieved or built|what have you built that|most proud", ANS.get("impact","")),
 (r"work environment|thrive|attributes", ANS.get("environment","")),
 (r"pronoun", "He/him"),
 (r"gender identity|^gender$|\bgender\b", "Male"),
 (r"university|school|college|alma mater", "University of Madras"),
 (r"degree|field of study|major", "Bachelor of Engineering, Computer Science and Engineering"),
]
CHOICE_RULES=[
 (r"experience (using|with) ai[- ]assisted (development |dev |coding )?tools|github copilot|\bcursor\b|ai[- ]assisted (coding|development|dev)|ai (coding|development|dev|pair[- ]?programming) tools|use ai[- ]assisted (development|coding) tools", ["Yes","yes"]),   # applicant uses agentic engineering / AI dev tools daily (CTO building AI)
 (r"would you like to receive (mobile )?text|(text message|sms|mobile text).{0,40}(opt-?in|opt-?out|updates|consent|recruiting)|opt-?in below", ["Opt-Out from receiving text messages from Walmart","Opt-Out from receiving text messages","Opt-Out","Opt Out","Decline","No","Do not opt-in"]),   # applicant declines SMS/text recruiting messages
 (r"(select|what is) your age category|^age category|please select your age", ["18 years of age and Over","18 years or older","18 and over","18 or older","Over 18","18+","Yes"]),   # applicant is over 18 (age-eligibility, not a demographic band)
 (r"associate status\s*/?\s*affiliation|(walmart )?associate status|associate affiliation|employee status\s*/?\s*affiliation", ["Have never been an employee of Walmart Inc or any of its subsidiaries","Have never been an employee","Never been an employee","Have never been","I have never","None of the above","No"]),   # never worked at Walmart
 (r"(already )?left active duty|leave active duty|active duty.{0,30}(near future|recently|soon)", ["Not Applicable","Do Not Wish to Provide","No","N/A"]),   # applicant is not and was not a service member
 (r"experience (in|within|with|working in) (the )?(staffing|recruit(ing|ment)|recruitment|staffing[ /]recruit\w*|agency) (industry|sector|space|field|business)|worked (in|within) (the )?(staffing|recruit\w*) (industry|sector|field)|(staffing|recruit\w*) (industry|sector) experience", ["No","no","No, I do not","I do not have"]),   # applicant has no staffing/recruitment-industry experience (fintech/AI background); honest No
 (r"how soon .{0,20}available to start|when (can|could|are) you (available|able) to start|availability to start|earliest (start|available) date|notice period", ["Immediately","Immediate","As soon as possible","ASAP","Right away","Within the next 30 days","Within 30 days","2 weeks","Two weeks"]),   # applicant gives ~2 weeks' notice (current CTO)
 (r"privacy notice|privacy (policy|statement) (to|for) (applicants|candidates)", ["Acknowledged","I acknowledge","Acknowledge","Yes","I agree","I have read","I consent","Consent","Confirmed","Confirm"]),
 (r"talent community|(receive|get) (information|communications|updates|emails) about (future |other )?(job )?(opportunities|positions|openings|roles)", ["Yes, I would like to receive communications","Yes","yes","I agree","I consent","Consent"]),   # same answer as the future-positions question elsewhere
 (r"citizen or (a )?permanent resident of (one of )?(these|the following|any of the following) (nations|countries|regions)|(citizen|national|resident) of (cuba|iran|north korea|syria).{0,80}\?", ["Does Not Apply","Does not apply","None of the above","None of these","None","No","Not applicable","N/A"]),   # US citizen; export-control country list
 (r"how familiar are you with (distributed systems|asynchronous|microservices|event[- ]driven|test automation|automated testing|cloud|kubernetes|kafka|system design|ci/cd|observability)", ["I have used it in production systems","Used it in production","Production","Expert","Very familiar","I have led complex"]),   # resume: JPMorgan, Yahoo Finance, Hyperion AI (all in production)
 (r"involvement (with|in) architecture (discussions|decisions)|best describes your (involvement|experience) (with|in) architecture", ["I have led complex architecture decisions","I have led architecture discussions","Led"]),   # Chief Architect, Yahoo Finance; CTO, Hyperion AI
 (r"which work arrangement|work arrangement (are you|you('re| are)) (looking for|seeking|interested in)|preferred work (arrangement|model|setup|location type)|what (type of )?work (arrangement|model|setup) (are you|do you|would you)", ["Fully remote","Remote","Remote (US)","Hybrid"]),   # applicant (2026-10-01): remote, or Bay Area / NYC hybrid; never 5 days in person
 (r"(experience|background) (building|with|in) (ai|llm|ai/llm|ai or llm)[^?]{0,60}(production|systems)|what best describes your experience (building|with) (ai|llm)", ["I have built and shipped","built and shipped","I have built","Production"]),   # Hyperion AI: agentic platform built end to end and shipped
 (r"level of ownership.{0,60}(0\s*(→|->|to)\s*1|zero to one|ambiguous)|ownership .{0,30}0\s*(→|->|to)\s*1", ["I’ve led or been a primary driver","I've led or been a primary driver","I have led","Led"]),   # CTO and co-founder of Hyperion AI, co-founder of Motocho
 (r"personally participate in (each|every|all|any) interview|will not use another person to interview|interview on my behalf|not use ai tools .{0,120}(during|in) (any|the|my|each) interview", ["Yes, I agree","I agree","Yes","yes","Agree"]),   # interview-integrity pledge about his own future interviews (not the application); "criminal" in the fine print must not trip the No rule
 (r"engage with .{0,40}employees to negotiate|negotiate, influence and/or sign .{0,40}contracts", ["No","no"]),
 (r"employee of a government (office|agency|entity)|government (office|agency) .{0,40}oversight", ["No","no"]),
 (r"registered .{0,60}securities industry|securities industry .{0,40}registered|attempted to become .{0,30}registered|finra (registration|licen[cs]e)|series (7|24|63|65|66|79|99) (licen|registr|exam)", ["No","no"]),   # applicant: never registered (FINRA)
 (r"of legal age to work|legally permitted to work", ["Yes","yes"]),
 (r"\b(age|are you) (18|eighteen)( years)?( of age| old)? or (over|older)|\bat least (18|eighteen)( years)?( of age| old)?\??\s*$", ["Yes","yes"]),
 (r"do you meet the (preferred|basic|minimum|required) qualifications", ["Yes","yes"]),
 (r"(use|work on) the workday system", ["No, I do not use the Workday system","No, I do not","No"]),   # Hyperion AI does not run on Workday
 (r"(currently )?(live in|located in|based in) or (are you )?(able|willing) to relocate to the (location|city|area)", ["Yes","yes"]),   # queued roles are all in his locations (Bay Area / NYC hybrid / remote), and he will relocate
 (r"(commit to|able to) (coming|come|commute|report) (into|in|to) the office|(come|coming) into the office as advertised", ["Yes","yes"]),   # in-office as advertised: queued roles are Bay Area (any mode) or NYC hybrid
 (r"i (attest|confirm|certify)\S* that i have no post-government|no post-government employment restrictions", ["Yes","yes","I attest","I confirm","I agree","Agree"]),   # an attestation of having no restrictions: Yes
 (r"(been )?an employee of a u\.?s\.? (federal|state|local)|federal, state,? or local government|government employment", ["No","no"]),
 (r"regarding future (positions|openings|opportunities)|future openings|communications about .{0,40}future", ["Yes, I would like to receive communications","Yes, I would like","Yes","Opt in","Opt-in"]),
 (r"^(?!.*\b(yahoo|jp ?morgan|chase|morgan stanley|bloomberg|cadence|ankr|bank of america|merrill|barclays|hyperion)\b).*(ever been issued|been issued|ever had) (a |an )?.{0,30}(employee id|email address|badge)", ["No","no"]),   # never worked at the company he applies to
 (r"(25|10)% or more .{0,40}ownership interest|ownership interest in,? or plan to have such an ownership", ["No","no"]),   # applicant (2026-10-01): owns under 25% of any business
 (r"position of control with a for-profit|serve,? service,? or plan to serve in any position of control", ["No","no"]),   # applicant (2026-10-01): no position of control
 (r"disciplined by an administrative agency|subject of an administrative order", ["No","no"]),
 (r"fiduciary appointments?|executor, personal representative, administrator, guardian, trustee", ["No","no"]),
 (r"(position|role) on a political campaign|political campaign", ["No","no"]),
 (r"senior executive of a customer, potential customer or third[- ]party vendor .{0,20}refer you|did a senior executive .{0,80}refer you", ["No","no"]),
 (r"family relationship .{0,200}(close personal contact|employees, contingent resources|senior executive)", ["No","no"]),
 (r"(currently have,? or plan to have,? any employment or other work that you intend to continue|employment or other work .{0,40}continue if you accept)", ["No","no"]),
 (r"^(?!.*\b(yahoo|jp ?morgan|chase|morgan stanley|bloomberg|cadence|ankr|bank of america|merrill|barclays|mantara|hold brothers|compunnel|motocho|hyperion)\b).*\b(worked|been employed) (previously|before|ever|in the past) (as|for|at|with) .{0,40}\b(associate|employee|team member|staff member)", ["No","no"]),   # never worked for the company he applies to (past employers exempt)
 (r"professional (state[- ]issued )?licen[cs]e in the (legal|banking|financial|insurance)|state[- ]issued licen[cs]e", ["No","no"]),   # no professional licenses (never FINRA-registered)
 (r"offer of employment .{0,120}contingent upon|contingent upon the outcome of a (consumer|background) (report|check)", ["I have read and acknowledged","I have read and acknowledge","I acknowledge","Acknowledged","Yes, I understand","Yes"]),
 (r"which state .{0,40}(reside|live) permanently|as of your .{0,30}start date,? which state", ["California","CA"]),
 (r"(posted|listed|stated|advertised) (base )?(salary|pay|compensation)( range)? .{0,30}align|align\w* with your (salary|compensation|pay) (requirements|expectations)", ["Yes","yes"]),
 (r"interested in (regular )?full[- ]time or part[- ]time|(full[- ]time|part[- ]time),? (contract|temporary)|type of employment (are you|you are) (interested|seeking|looking)", ["Regular Full-Time","Regular Full Time","Full-Time Regular","Full-Time","Full time","Regular","Permanent"]),
 (r"work (environment|model|arrangement)\(?s?\)? .{0,40}(open to|interested in|prefer)|which work (models?|arrangements?) .{0,30}open", ["100% Remote","Remote","Fully Remote","Hybrid (Combination of Office/Remote)","Hybrid"]),   # remote US anywhere; hybrid in the Bay Area / NYC
 (r"minimum (annual |base )*salary|salary desired|desired (minimum )?(annual )?salary \(in usd\)", ["300,000 to 350,000 USD","275,000 to 350,000 USD","300,000 - 350,000","$300,000 - $350,000","250,000 to 260,000 USD","250,000 to 275,000 USD","250,000 - 260,000","250,000-260,000","$250,000 - $260,000","$250,000+","250,000+ USD","250,000+","240,000 to 250,000 USD","Over $250,000","More than $250,000","220,000 to 240,000 USD","220,000 to 250,000 USD","$220,000 - $250,000","220,000 - 250,000","$220,000+","220,000+","$225,000","$220,000","200,000 to 250,000 USD","$200,000 - $250,000","200,000 - 250,000"]),
 (r"area of emphasis .{0,40}(best )?match", ["Datastore Systems Profile","Systems","Architecture","Platform"]),   # Beacon: leads design across the platform
 (r"are you a referral of (a |an )?(current |existing |potential )?(senior commercial person|scp\b|government official|senior government|merchant|third party|client|customer)", ["No","no"]),   # not referred by anyone
 (r"(engaged|involved|participat\w*) in any (outside|additional|other) (employment|activit|business)|outside (employment|activit\w*|business\w*) .{0,60}(continue|maintain|keep) .{0,30}(if|once|after) (you are )?hired", ["No","no"]),   # consistent with the outside-activities text answer ("None")
 (r"provide verification of (your )?identity|verify your identity (upon|at) hire", ["Yes","yes"]),
 (r"(member of|serving in|in) the (u\.?s\.? )?(national guard|reserves?)\b|national guard or reserves?", ["No","no"]),
 (r"automated tools such as ai .{0,240}opt-?out|prefer not to have your application processed by (these|automated|ai)", ["Opt-in","Opt in","I do not wish to opt out","I do not want to opt out","Do not opt out","No, I do not want to opt out","I consent","I agree","Accept"]),   # the employer's AI screening of applications: not opting out (never Yes/No, which would be ambiguous)
 (r"^work eligibility:?\s*\*?$|^citizenship status:?\s*\*?$", ["I am 18 years or older","U.S. Citizen","US Citizen","United States Citizen","Citizen of the United States","U.S. Citizen or National","U.S. citizen or national","Citizen"]),
 (r"\bi-?140\b", ["No","no"]),
 (r"what state\(?s?\)? (are you|can you|do you|would you) (be )?(able to |legally )?(work|live|reside)", ["California","CA"]),
 (r"^(?!.*\b(aligned?|within|in line|comfortable|okay|ok|acceptable|fits?)\b).*((realistic|expected|desired|target) (base )?(gross )?(annual )?(salary|compensation|base pay) (expectation|range|requirement)?|salary expectations?\b)", ["$300,000 - $350,000","$300,000-$350,000","$300,000+","$300K+","$275,000 - $350,000","$300,000 or more","Over $300,000","$250,000+","$250,000 +","$250,000 and above","$250,000 or more","$250,000 or higher","250,000+","$250K+","More than $250,000","Over $250,000","Above $250,000","$250,000 - $299,999","$250,000-$299,999","$250,000 - $300,000","$250,001","$250k - $300k","$250k-$300k","$240,000 - $260,000","$240,000-$260,000","$260,000 +","$260,000+","$250,000 - $260,000","$225,000+","$200,000+","$200,000 or more","Over $200,000","More than $200,000","Above $200,000","$220,000+","$220,000 - $250,000","$220,000-$250,000","$220,000 - $240,000","$200,000 - $250,000","$200,000-$250,000","$200,000 - $240,000","$200,000 - $220,000","$210,000","$220,000","$225,000","$200,000 - $300,000","$200K+","$200k - $250k","$200k-$250k"]),
 (r"how (should|would you like|do you prefer|can) (we|us to) (communicate|contact|reach) (with )?you|preferred (method|mode|channel) of (communication|contact)", ["Email","E-mail","Phone Call","Phone"]),
 (r"are you (currently )?in the (reserves|national guard)", ["No","no"]),
 (r"if this role or future roles require relocation", ["I am willing to relocate and will self relocate","I am willing to relocate","Yes"]),
 (r"work authori[sz]ation (is )?based on .{0,80}(spouse|h-?1b|h-?4|l-?2|dependent)", ["No","no"]),   # US citizen
 (r"did you answer .no. to question 1 and/or .yes. to question", ["No","no"]),
 (r"live in or (are )?able to relocate to the location (this|the) job", ["Yes","yes"]),
 (r"interviewed (for .{0,40})?(at|with) .{0,40}within the (last|past) \d+ months", ["No","no"]),
 (r"select if you were a previous .{0,30}employee", ["I have never been employed","Never employed","No","I was never employed"]),
 (r"i confirm that my answers .{0,80}(complete|accurate|true)", ["Yes","yes","I confirm","I agree"]),
 (r"tangible factors .{0,60}(important|matter)|(factors|things) (are|matter) most (important )?to you when considering", ["Compensation","Leadership","Career Growth","Culture","Company Outlook","Remote Work"]),   # multi-select (Motive)
 (r"willing to provide (the )?information .{0,120}export|provide information necessary to comply with .{0,40}export", ["Yes","yes"]),   # US citizen: willing to provide export-control information
 (r"when would you be available to relocate|available to relocate to the (san francisco )?bay area|relocate to the (san francisco )?bay area,? when", ["I already live in the Bay Area","Already in the Bay Area","Already local","N/A","Immediately","Now","October 2026","November 2026"]),   # he already lives in Santa Clara (Bay Area)
 (r"security principle .{0,60}(ai agent|agents?|external tools)|most important when giving an ai agent access", ["Least privilege","Principle of least privilege"]),   # technical quiz: least privilege
 (r"which .{0,40}office (location/?s?|locations?) (are you|would you be) (open|willing|able)|office locations? .{0,20}(open to|willing to) work(ing)? (out of|from|in)", ["San Francisco","San Francisco, CA","SF Bay Area","Bay Area","Palo Alto","Mountain View","Sunnyvale","San Jose","Santa Clara","Menlo Park","Oakland","New York","New York, NY","NYC","Remote","Neither","None of the above","None"]),   # Bay Area or NYC offices only; otherwise remote / neither
 (r"personally worked hands-on with in the last|worked hands-on with in the last \d+ years", ["AWS multi-account","Terraform or equivalent IaC","Kubernetes","Self-managed CI/CD","Ruby or Python backend","Relational databases at scale (RDS or similar)"]),   # his stack (AWS, Terraform, Kubernetes, CI/CD, Python, Postgres)
 (r"^which do you have experience with\?\s*select all that apply", ["Internal or external audit controls","Vendor negotiation and budget ownership","Healthcare or benefits","Backend systems powering mobile or consumer apps"]),   # regulated-bank audits, CTO budget, healthcare (applicant), Yahoo Finance consumer backends
 (r"willing to work (in|from|at) (our|the) (new york|nyc|ny) office|work (in|from) (our|the) (new york|nyc) office", ["Yes","yes","Hybrid","Remote"]),   # NYC roles are queued only when hybrid or remote; applicant accepts NYC hybrid and travel
 (r"with or without (a )?reasonable accommodation|able to (perform|meet|participate|complete|fulfill).{0,120}(requirements|functions|duties)", ["Yes","yes"]),   # can do the job / attend onsite; never the "do you need an accommodation" No
 (r"hands-on (management|manager|leadership|engineering manager|people manager)( role)?|player[- ]coach", ["Yes","yes"]),   # applicant is a hands-on leader
 (r"export[- ]controlled information|for export[- ]control purposes", ["I am a US Person and can provide a valid, unexpired US Passport or US birth certificate or certificate of naturalization upon request.","I am a US Person and can provide a valid, unexpired US Passport","I am a U.S. citizen","U.S. Citizen","US Citizen","Yes"]),   # US citizen
 (r"(eligible|able) (to|for) (receive|obtain|hold|get)?\s*(a |an )?public trust|public trust (clearance|eligib|position)", ["Yes","yes"]),   # US citizen; Public Trust is a background investigation
 (r"^(?!.*\b(yahoo|jp ?morgan|chase|morgan stanley|bloomberg|cadence|ankr|bank of america|merrill|barclays|mantara|hold brothers|compunnel|motocho|hyperion)\b).*(do you currently,? or have you (ever )?previously (worked|been employed)|have you (ever )?(previously )?been employed,? (or otherwise engaged,? )?(by|at|with) (?!(a|an|any) )|(currently|previously) (work|worked|employed) (for|at|by) (?!(a|an|any) ))", ["No","no","I have not previously been employed","I have not been employed","I have never worked","I have not worked","have not worked","have not been","Never worked","Never","None of the above","Not applicable","N/A"]),   # never worked for any company he applies to
 (r"difference between a pod and a container", ["A Pod is a logical grouping of one or more Containers with some shared resources."]),   # technical quiz: correct answer
 (r"load balance .{0,60}(url|path)|(url|path)[- ]based routing", ["Application Load Balancer (ALB)","Application Load Balancer","ALB"]),   # technical quiz: ALB routes on URL path (layer 7)
 (r"(three|3) (core )?pillars of observability", ["Metrics, Logs, and Traces","Metrics, Logs and Traces","Logs, Metrics, and Traces","Logs, Metrics and Traces"]),   # technical quiz
 (r"\bcamunda\b|business process management|\bbpmn?\b", ["No","no"]),   # not in his experience (the follow-up "if yes, describe" gets N/A)
 (r"did (a|an|any) (current|former)? ?[a-z'-]{0,30} refer you|has (a|an|any) [a-z' -]{0,30} referred you", ["No","no"]),   # not referred
 (r"^(?!.*(united st|\bu\.?s\.?a?\b|\bamerica)).*(authori[sz]ed|eligible|permitted|entitled|(legal )?right) to (live and )?work in (the )?(germany|deutschland|u\.?k\.?\b|united kingdom|england|britain|scotland|ireland|canada|india|israel|netherlands|france|spain|poland|portugal|singapore|australia|new zealand|japan|korea|china|hong kong|taiwan|brazil|mexico|argentina|colombia|switzerland|sweden|norway|denmark|finland|austria|belgium|italy|czechia|czech republic|romania|ukraine|eu\b|european union|europe|emea|uae|united arab emirates|dubai|saudi arabia|south africa|philippines|vietnam|indonesia|malaysia|thailand)", ["No","no","No, I am not authorized","No, I would need a work permit","No, I would require sponsorship"]),   # US citizen only: never claim non-US work rights
 (r"^(?!.*(united st|\bu\.?s\.?a?\b|\bamerica)).*relocat\w* to (the )?(germany|deutschland|u\.?k\.?\b|united kingdom|england|britain|scotland|ireland|canada|india|israel|netherlands|france|spain|poland|portugal|singapore|australia|new zealand|japan|korea|china|hong kong|taiwan|brazil|mexico|argentina|colombia|switzerland|sweden|norway|denmark|finland|austria|belgium|italy|czechia|czech republic|romania|ukraine|eu\b|european union|europe|emea|uae|united arab emirates|dubai|saudi arabia|south africa|philippines|vietnam|indonesia|malaysia|thailand)", ["No","no"]),   # not relocating abroad
 (r"^(?!.*(united st|\bu\.?s\.?a?\b|\bamerica)).*(require|need)\w* (a )?(visa|work permit|employment|immigration)?\s*(sponsorship|permit|visa)\b.{0,50}\b(in|for|to work in) (the )?(germany|deutschland|u\.?k\.?\b|united kingdom|england|britain|scotland|ireland|canada|india|israel|netherlands|france|spain|poland|portugal|singapore|australia|new zealand|japan|korea|china|hong kong|taiwan|brazil|mexico|argentina|colombia|switzerland|sweden|norway|denmark|finland|austria|belgium|italy|czechia|czech republic|romania|ukraine|eu\b|european union|europe|emea|uae|united arab emirates|dubai|saudi arabia|south africa|philippines|vietnam|indonesia|malaysia|thailand)", ["Yes","yes"]),   # he would need a permit outside the US
 (r"strong in python|python,? with (solid|strong) java", ["Yes"]),   # Python is core; Java at JPMorgan/Yahoo (on his resume)
 (r"(enterprise architecture|governance[- ]heavy)( or [a-z -]{0,30})? roles,? rather than hands-on", ["No"]),   # recent career is hands-on (CTO & Principal Architect at Hyperion AI, building the data/AI platform)
 (r"people-leadership responsibilities|people leadership (responsibilities|experience)", ["Managing engineering teams","Hiring engineers","Performance management","Mentoring engineers","Conducting performance reviews","Developing career plans","Managing team workload/priorities","Coaching technical skills"]),
 (r"types of automated testing|automated testing have you", ["Unit testing","Integration testing","API testing","Regression testing","System testing","Performance/load testing","Automated UI testing"]),
 (r"which azure services", ["Azure Functions","Azure App Services","Azure Storage","Azure DevOps","Azure Key Vault","Azure Monitor","Azure Cosmos DB"]),
 (r"which of the following technologies have you used", ["C#",".NET Core / .NET","React.js","JavaScript / TypeScript","REST APIs","Microservices","ASP.NET","Python","Go","Rust","C++","Java","TypeScript","Kubernetes","AWS","Azure","Kafka"]),
 (r"non-?compet(e|ition)|agreements? (that|which) (would|could|may|might) (preclude|restrict|limit|prevent|prohibit)|preclude or restrict", ["No","no","None","No, I am not","I am not bound"]),   # applicant: no non-compete or other restricting agreement
 (r"held h-?1b|h-?1b (status|petition|visa|cap)|(held|hold|have) (an? )?(f-?1|j-?1|l-?1|o-?1|tn|e-?3|h-?4) (status|visa)", ["No","no"]),   # applicant: US citizen
 (r"procurement|contract award", ["No","no","None","Not applicable"]),   # applicant: never a government employee or official
 (r"contract(ual)? (obligation|agreement|commitment)s?|obligations? (to|with) (your|a) (current|former|previous) employer|restrictive covenant|bound by (any )?(agreement|contract|covenant)|agreements? (that|which) (would|could|may|might) (restrict|limit|prevent|prohibit)|(prohibited|limited|restricted) in (your )?(performance|ability)|garden leave|notice.{0,20}contractual", ["No","no","None","No, I am not","I am not bound"]),   # applicant: no contract obligation with his current employer
 (r"best describes how you use ai tools|how (do|would) you (currently )?use ai tools", ["I design or automate workflows with AI tools (e.g., building agents, integrating AI into team processes).","I design or automate workflows with AI tools","I regularly use AI tools","I am an advanced AI user","I develop AI powered systems or agentic applications","I develop AI-powered systems","I build or automate workflows using AI","Expert","Advanced"]),   # applicant builds agents (Hyperion AI); not an AI-in-this-application question
 (r"experience in the creator economy", ["Meta / Instagram / Facebook","YouTube","Other"]),   # applicant: uses Facebook, YouTube, Twitch
 (r"^english language skills|english (language )?(proficiency|level)", ["Fluent (C1)","Fluent","Native (C2)","Native"]),
 (r"^(german|french|spanish|italian|dutch|japanese|korean|mandarin|chinese|portuguese|polish) language skills|(german|french|spanish|italian|dutch|japanese|korean|mandarin|chinese|portuguese|polish) (language )?(proficiency|level)", ["None (A1 / No proficiency)","None","No proficiency"]),
 (r"are you lgbtq|identify as (part of )?(the )?lgbt|lgbtq\w*\+? (community|identity)", ["Prefer not to indicate","Prefer not to say","I don't wish to answer","Decline to self-identify","Decline To Self Identify","I prefer not to answer","Prefer not to answer","I prefer not to say","Decline","Prefer not to disclose"]),
 (r"local to (nyc|new york|the tri-?state|manhattan|brooklyn)|(live|based|located) (in|near) (the )?(nyc|new york|tri-?state) (area|region)", ["No, but willing to relocate to NYC","No, but willing to relocate","No, but I am willing to relocate","Willing to relocate","No, but open to relocating"]),   # applicant: Santa Clara, CA; willing to move to New York
 (r"(meet|satisfy|have) (each of |all of |all )?the (basic|minimum|required) qualifications", ["Yes","yes"]),   # applicant: apply when he meets ~70%+ of the role
 (r"affiliate/subsidiary with which you were employed|which (affiliate|subsidiary) (were you|you were) employed", ["N/A","Not applicable","None"]),   # never employed there
 (r"(healthcare|health insurance|senior care).{0,120}another highly regulated industry", ["Yes \u2014 healthcare","Yes - healthcare","Yes, healthcare","Yes \u2014 another highly regulated industry","Yes - another highly regulated industry","Yes, another highly regulated industry"]),   # applicant: has healthcare experience (and banking, trading and payments) are highly regulated
 (r"(how many )?years (have you|of|in) (directly |people |engineering )?(managed|managing|management|led|leading|supervis\\w+)|how many years .{0,40}(managed|managing|led|leading|supervis\\w+) (software |engineering |technical )?(engineer|team|people|staff|report)|years of (people|engineering|team) management", ["10+ years","10+","More than 10 years","10 or more years","10-15 years","10\u201315 years","8-10 years","8\u201310 years","7+ years","5+ years","Yes","yes"]),   # applicant: 10+ years leading engineers
 (r"highest (level of )?(school|education|degree)|highest degree|most advanced degree", ["Bachelor of Engineering","Bachelor's Degree","Bachelor\u2019s Degree","Bachelor degree","Bachelors degree","Bachelor\u2019s degree","Bachelor's degree","Bachelors","Bachelor","Undergraduate/Bachelor's degree","4-year degree","Four-year degree"]),   # B.E., University of Madras
 (r"staff[- ]level|(principal|staff)[- ](or equivalent|equivalent)|cross-team (scope|technical leadership)|span(s|ning)? multiple teams", ["Yes","yes"]),   # CTO, Chief Architect, VP / Lead Architect roles
 (r"(currently )?(have|hold|on) (a )?temporary (work )?(authori[sz]ation|visa|permit|status)|temporary work authori[sz]ation", ["No","no"]),   # applicant: US citizen
 (r"(?<![a-z0-9])(solidity|smart contracts?|tokio|golang|rust|c\+\+)(?![a-z0-9])", ["Yes","yes","Expert","Advanced","Extensive","Hands-on","Both hands-on","Both"]),   # applicant: his stack (C++, Rust/Tokio, Go, C#/.NET, Python, scripting, Solidity, TypeScript/JS, React.js)
 (r"(?<![a-z0-9])(c#|\.net|dotnet|asp\.net|azure)(?![a-z0-9])", ["Yes","yes","Expert","Advanced","Extensive","Hands-on","Both hands-on","Both","10\u201314 years","10-14 years","10+ years","More than 10 years","15+ years"]),   # applicant: C#, .NET and Azure are his stack (React.js itself is ~13 years old, so no 15+ claim first)
 (r"describe your experience with twitch", ["Viewer - I primarily watch content with minimal chat participation","Viewer"]),   # applicant: uses Twitch
 (r"(are you|have you (ever )?been) (a |an )?(current |active |regular )?(user|customer|member|fan) of|do you (currently |regularly )?use (our|the|this) (product|app|platform|service|site)|have you (ever )?used (our|the|this) (product|app|platform|service)|do you (currently )?(have|hold) an? .{0,25}account|do you (enter|play|participate in) .{0,30}(contests|fantasy|sports|esports)|(do you (use|have|hold)|are you (a |an )?(active |regular )?(user|member) (of|on)) .{0,30}(social media|facebook|instagram|twitch|coinbase|youtube|tiktok|reddit|discord|twitter|x\.com)", ["Yes","yes","Yes, regularly","Yes - regularly","Daily","Weekly"]),   # applicant: uses FB, Twitch, Coinbase and the rest
 (r"^(?!.*(cuba|iran|north korea|syria|crimea|donetsk|luhansk|one of the follow|sanction)).*(in which country/?(region)? do you (have|hold) citizenship|country of citizenship|provide your country of citizenship)", ["United States","United States of America","USA","US"]),   # applicant: US citizen
 (r"since obtaining your most recent citizenship.{0,80}permanent resident", ["No","no"]),
 (r"considered for future (opportunities|roles|positions)|keep (me|my (application|information)) (on file|for future)", ["Yes","yes"]),
 (r"^are you open to relocation\??\s*$", ["San Francisco, CA","San Francisco","Bay Area","No, but I'm open to a remote position","Yes","yes"]),   # applicant lives in Santa Clara: the Bay Area office needs no move
 (r"languages? (do )?you speak|which languages you speak|spoken languages?|languages? (in addition to|other than|besides) english", ["Tamil (India)","Tamil","Hindi","Indian (Hindi)","English"]),   # applicant: English, Tamil, Hindi
 (r"system design and architecture fundamentals|comfort(able)? moving across (different parts of )?the stack|full[- ]stack (comfort|range)", ["Yes","yes"]),
 (r"completed an application for any other opportunities at gallup", ["No","no"]),   # no earlier Gallup application
 (r"(willing|able) to provide .{0,20}(professional )?references|provide (2|3|two|three|2-3).{0,10}references", ["Yes","yes"]),
 (r"do you live in one of the following states|which (of the following )?states? do you (currently )?(live|reside) in|(reside|live|located|based) in(,)? (or .{0,40})?(any|one) of the following states\??\s*$", ["California: SF Bay Area","California - SF Bay Area","California (SF Bay Area)","CA California","California","CA"]),   # applicant lives in Santa Clara, CA (no Yes: the list may not include California)
 (r"are you (currently )?still (employed|working) (with|at|for)", ["Yes","yes"]),   # applicant: currently CTO at Hyperion AI
 (r"(require|need) .{0,60}\b(file|sign|certify|support|participate in|sponsor)\b.{0,120}\b(immigration|work authori[sz]ation|visa|petition|green card|h-?1b)", ["No","no","No, I do not require sponsorship","I do not require sponsorship"]),   # applicant: US citizen, needs nothing now or later
 (r"(?=.*(\bca\b|california))((live|reside|located) in|move to|relocate to).{0,250}(following|these|listed|eligible) (states|locations)|(?=.*(\bca\b|california))(following|these|listed|eligible) (states|locations).{0,250}((live|reside) in|move to|relocate)|^do you (currently )?(live|reside) in (?=[^?]*\bcalifornia\b)", ["California: SF Bay Area","California - SF Bay Area","California (SF Bay Area)","California","CA","Yes","yes"]),   # a state list that includes California: the applicant lives in Santa Clara, CA
 (r"^location preference|(preferred|desired) (work )?location|work location preference|which location would you prefer", ["Santa Clara","San Jose","Sunnyvale","Mountain View","Palo Alto","Menlo Park","Redwood City","San Mateo","Burlingame","Foster City","South San Francisco","San Francisco","Bay Area","California","Remote"]),   # applicant: Santa Clara; any Bay Area office, else remote
 (r"requires? (a )?background checks?.{0,400}(disclos|conviction)|background checks? of all (new )?(employees|candidates|hires)", ["I Acknowledge","I acknowledge","Acknowledge","Yes","I consent","I understand"]),   # acknowledgment of the employer's background-check policy, not a conviction disclosure
 (r"provided any contract work for|ever (been )?(a )?contractor (for|with|at)", ["No","no"]),
 (r"geometric processing|3d/cad|\bcad\b applications|computational geometry|mesh processing", ["No","no"]),   # not on the resume
 (r"^(have|do) you (ever )?(used|run|operated|deployed|worked with|have (hands-on |professional )?experience (with|using)) (?!.*(python|golang|\bgo\b|rust|tokio|solidity|c\+\+|c#|\.net|dotnet|bash|shell|scripting|java\b|typescript|javascript|node|react|sql|kafka|kubernetes|k8s|aws|gcp|google cloud|azure|terraform|postgres|spark|docker|redis|grpc|fastapi|llm|vllm|llama|databricks|mcp|rag\b|pytorch|openai|claude|langchain|vector|linux|git|ci/cd|microservices|kinesis|s3|lambda|ec2|bigtable|cassandra|mysql|elasticsearch|prometheus|opentelemetry|grafana|airflow|flink|tensorflow|hugging ?face|agents?\b|model serving|inference))[\w .+#/-]{2,40}? in (a )?production", ["No","no","No, I have not"]),   # a tool that is not on the resume
 (r"(currently|presently) (based|located|living|residing) (in|near|around) (nyc|new york|manhattan|brooklyn)|are you (based|located|living) (in|near) (nyc|new york)|(live|living) (near|within commut\w+ distance of) (nyc|new york|the (nyc|new york) office)", ["I'm not in NYC yet, but I'm able and willing to relocate","Not yet, but willing to relocate","Willing to relocate","No, but I am willing to relocate","No"]),   # applicant lives in Santa Clara; will move to New York
 (r"(mountain view|sunnyvale|palo alto|menlo park|redwood city|san mateo|foster city|cupertino|san jose|santa clara|fremont|oakland|berkeley|south san francisco|san francisco|emeryville|burlingame|san carlos|los altos|milpitas|bay area|san ramon|pleasanton|dublin, ca|walnut creek|concord, ca|livermore|hayward|san leandro|union city|campbell|los gatos|saratoga|belmont|san bruno|millbrae|daly city|alameda|richmond, ca|emeryville|novato|san rafael|half moon bay|danville|lafayette, ca|morgan hill|gilroy|newark, ca).{0,160}(commut|relocat|able to work|on-?site|in[- ]office|in person|report to)|(commut|relocat).{0,60}(mountain view|sunnyvale|palo alto|menlo park|redwood city|san mateo|cupertino|san jose|santa clara|san francisco|bay area|san ramon|pleasanton|dublin, ca|walnut creek|concord, ca|livermore|hayward|san leandro|union city|campbell|los gatos|saratoga|belmont|san bruno|millbrae|daly city|alameda|richmond, ca|emeryville|novato|san rafael|half moon bay|danville|lafayette, ca|morgan hill|gilroy|newark, ca)", ["Yes","yes","I currently live","I live in","Bay Area","San Francisco Bay Area","San Francisco based","San Francisco"]),   # applicant lives in Santa Clara; any work mode in the Bay Area
 (r"what did you get when you cracked the code", ["42"]),   # Lithic's posting: base64 Python snippet, XOR of two bytes = "42" (applicant: solve posting puzzles)
 (r"camera on|on video|video interview", ["Yes","yes"]),   # applicant
 (r"are you aligned|whatever it takes|don'?t take .?no.? as an answer|high[- ]intensity|work (very )?hard|hustle|fast[- ]paced .{0,40}(comfortable|thrive|aligned)|in[- ]office culture|grind", ["Yes","yes"]),   # applicant: culture-fit questions Yes
 (r"^do you have (professional |hands-on )?experience (with|using|on) (aws|amazon web services|gcp|google cloud|azure|kubernetes|terraform|kafka|spark|postgres(ql)?|docker)\b", ["Yes","yes"]),
 (r"resident of the european union|reside in the (eu|european union|uk|united kingdom|eea)", ["No","no"]),
 (r"(currently or were you previously|were you previously|have you previously been) an? (?!(yahoo|jp|jpmorgan|chase|morgan|bloomberg|cadence|bank|merrill|barclays|hyperion|motocho|ankr|mantara|hold|compunnel)\b)\w+ (employee|contractor|intern)", ["No","no"]),   # none of his past employers
 (r"(current )?level of experience (using or building|with|using) (with )?ai tools|best describes your .{0,30}experience .{0,20}ai tools|best describes how you (currently )?use ai tools", ["I am an advanced AI user","I develop AI powered systems or agentic applications","I develop AI-powered systems","I build or automate workflows using AI","Expert","Advanced"]),   # Hyperion AI agentic platform
 (r"node\.?js", ["Expert (designed/architected large-scale systems)","Expert","Advanced","Yes"]),   # applicant: Node.js expert
 (r"fluent in sql and a (modern )?cloud data platform|^(?!.*(work(ed|ing)? (for|at|with)|employ|intern\b|contractor|affiliat|relative|family|applied)).*databricks", ["Yes","yes"]),   # applicant: SQL and Databricks
 (r"\breact(\.?js)?\b(?!\s+(to|quickly|when)\b)", ["Yes","yes","Expert","Advanced"]),   # applicant: professional React experience
 (r"tn visa|canadian or mexican citizens", ["No","no"]),
 (r"extent of your (use of )?ai|how (often|much) do you use ai (tools )?(in|for) your work|empowering every employee with ai", ["Extensively","Daily","Very often","Frequently"]),   # applicant uses AI tools daily in engineering work (resume)
 (r"time ?zone (are|do|will) you (currently |primarily |normally |usually )?(based|located|reside|live|in|work)|which time ?zone .{0,30}(based|located|reside|live)", ["Pacific Time (PT)","Pacific Time","Pacific","PT","US/Pacific","PST"]),
 (r"finra licen[sc]e|series (7|63|65|66|24|57)|securities licen[sc]e", ["None","N/A","No","I do not hold any FINRA licenses"]),
 (r"requires? (\d|two|three|four) days?/? ?(a |per )?week (onsite|on-site|in[- ]office|in person) in (san francisco|sf|palo alto|mountain view|san jose|the bay area|menlo park|redwood city|sunnyvale|santa clara|oakland)", ["Yes","yes"]),   # applicant: any work mode in the Bay Area
 (r"10\+ years in software engineering|10\+ years (of )?(experience )?in software", ["Yes","yes"]),
 (r"(new york|nyc|manhattan|brooklyn).{0,100}(5|five) days|(5|five) days.{0,100}(new york|nyc|manhattan|brooklyn)", ["No","no"]),   # applicant: New York only remote or hybrid
 (r"travel\w* .{0,70}\b(3[0-9]|[4-9][0-9]|100) ?%|\b(3[0-9]|[4-9][0-9]|100) ?% (of the time )?travel|travel (more than|over) 25", ["No","no"]),   # applicant: travel up to 25%
 (r"country ?/ ?(us[- ])?state|state ?/ ?country|country (and|&) state|country or (us )?state", ["United States - California","United States - CA","US - California","USA - California","California, United States","California"]),
 (r"^are you currently (employed|working)( full[- ]time)?\??\*?$|current(ly)? employment status|what is your employment status|^employment status", ["Yes","Employed","Employed full-time","Currently employed","Full-time employed","Employed, full-time"]),   # applicant: CTO at Hyperion AI (current)
 (r"when (can|could|would) you (be able to )?(start|join|begin)|earliest (possible )?start|available to start|(preferred|desired|target|earliest|expected|possible) start date|^start date\??\*?$", ["Immediately","Immediate","As soon as possible","ASAP","Right away","2 weeks","Within 2 weeks","Two weeks","Less than 2 weeks","Within 1 month"]),
 (r"if you selected .{0,10}two or more races|check all racial categories", ["Asian","Asian (Not Hispanic or Latino)"]),   # required follow-up (SoFi): the applicant's answer
 (r"graduation (year|date)|year (of|you) graduat|when did you graduate", ["1995","May 1995"]),
 (r"(hold|have) any (salesforce|servicenow|sap|workday)(\.com)? certifications?|(salesforce|servicenow|sap|workday) certifi", ["No","no","None"]),
 (r"(professional |production |hands-on )?experience (using|with|in|writing) (java|python|c\+\+|c#|\.net|golang|go|rust|tokio|solidity|typescript|javascript|node\.?js|react(\.?js)?|sql|bash|shell|scripting)\b(?! ?(ee|fx|swing))", ["Yes","yes"]),   # all on the resume (languages line; C++/Java execution paths and replay engines)
 (r"how important is the title|title/level .{0,40}(relative to|vs\.?|versus) scope|title (or|vs\.?|versus) scope", ["Scope Is Important","Scope is important","Scope","N/A"]),
 (r"more product-focused or systems-focused|product[- ]focused or systems[- ]focused", ["Systems-Focused","Systems focused","Systems"]),
 (r"do any of the following apply to you|which of the following (conflicts|disclosures|situations) apply", ["None of the above apply to me.","None of the above apply to me","None of the above","None of these apply to me","None of these","None"]),
 (r"(select|what is|which is|choose) your (current |primary )?time ?zone|^(current )?time ?zone\??:?\*?$", ["US/Pacific","Pacific Time","Pacific","PT","PST","Pacific Time (PT)","America/Los_Angeles"]),
 (r"^state\b|^state of residence|state \(if you do not live", ["California","CA","Another State in the US","Another state","Other US","Other"]),
 (r"require .{0,60}(file|submit) a petition|petition or application for employment|employment[- ]based (status|visa|immigration)", ["No","no"]),
 (r"(telephone calls?|phone calls?|text messages?|sms).{0,120}(consent|agree)|(consent|agree).{0,160}(text messages?|sms|telephone calls?)", ["Do not agree to receive recruitment notifications by call or text messages","Do not agree","I do not agree","I do not consent","No","Opt out","Opt-out","I disagree","Disagree","Decline","I decline"]),
 (r"(confirm|certify) that i (do not|don't) have (any )?relatives", ["True","Yes","I confirm","Confirmed","Confirm"]),
 (r"how (frequently|often) (have|do|did) you (personally )?(participate|participated|lead|led|conduct|conducted|review|reviewed|write|written|wrote|code|coded|contribute|contributed|design|designed|run|ran)", ["Weekly","Frequently","Very frequently","Regularly","Often","Multiple times a week","Daily","Monthly"]),
 (r"which .{0,30}hub (are )?you (are )?(currently )?based|hub you are currently based out of|which (of our )?(offices?|hubs?) (are you|do you) (currently )?(based|located|live)", ["Greater San Francisco Bay Area","San Francisco Bay Area","Bay Area","San Francisco","SF Bay Area"]),
 (r"personally (completed|filled|prepared|written|wrote) (out )?(this|the|my) (application|form)|completed (this|the) application (myself|personally|on my own)|(filled|written) (out )?(this|the) application (myself|personally)|(completed|submitted) by (me|the candidate) (personally|alone)", ["__ASK__"]),   # a certification that the applicant filled the form personally: theirs to make
 (r"king.?s ?cross|london office|(office|days a week) in (our )?(london|toronto|vancouver|dublin|berlin|paris|amsterdam|singapore|bangalore|bengaluru|tel aviv)", ["No","no"]),   # a non-US office commitment on a US role: the applicant is in the Bay Area
 (r"(authori[sz]ed|eligible|able|permitted|allowed) to (lawfully |legally )?work .{0,80}without (the )?(need (for|of) |requiring |requirement (for|of) )?(any |a |visa |employer |company )*sponsor", ["Yes","yes"]),
 (r"(require|need)\b.{0,100}\bsponsor", ["No","no","No, I do not require sponsorship","I do not require sponsorship"]),
 (r"government official|public official|politically exposed|holder of public office|civil service position", ["No, I am not a current or former Government Official","No, I am not a relative of a government official.","No, I am not","No","None of the above"]),
 (r"sanctions and export controls|please confirm whether any of the below applies to you", ["None of the above","None of these apply to me","No"]),
 (r"if you selected a response to the prior question other than", ["U.S. citizen","US citizen","U.S. Citizen","None of these apply to me"]),
 (r"perform (the |all )?(essential )?(job )?(duties|functions)|reviewed the job description|reviewing the (posted )?job description", ["Yes","I confirm","I acknowledge","I agree"]),
 (r"subject to .{0,80}background (check|screening|investigation)|comprehensive background check|(willing|able|agree) to (submit to|undergo|complete|consent to) .{0,30}background", ["Yes","I agree","I acknowledge","I understand","I consent","Consent","Confirmed"]),
 (r"require .{0,60}(participate in a government program|government program to maintain|\bopt\b|stem opt)", ["No","no"]),
 (r"which languages,? if any,? can you communicate|languages? .{0,40}professional (working )?proficiency|languages? (can|do) you (speak|communicate)|languages of fluency", ["English","Tamil","Hindi"]),   # applicant: English, Tamil, Hindi
 (r"location of your primary residence|state of (your )?(primary )?residence|primary residence.{0,20}(state|location)", ["California","CA","United States"]),
 (r"involve .{0,40}practical training|curricular practical training|optional practical training|\(cpt\)|\(opt\)|\bcpt\b.{0,10}\bopt\b", ["No","NO","no"]),   # US citizen: work authorization never involves CPT/OPT
 (r"confirm that you are legally authori[sz]ed to work in the us|verify that (you|i) (am|are) authori[sz]ed", ["I verify that I am authorized to work in the US","authorized to work in the US","Yes"]),
 (r"cuba|iran\b|north korea|dprk|syria|crimea|donetsk|luhansk|sanction|embargo|ofac|restricted (countries|country)|(one of|any of) the following countries", ["No","no"]),   # US citizen, US resident: never from or in a sanctioned country
 (r"(presently|currently|legally|lawfully) authori[sz]ed (under .{0,40})?to work|authori[sz]ed under (u\.?s\.?|united states) immigration", ["Yes","yes"]),   # US citizen
 (r"best describes your (right|eligibility|authori[sz]ation) to work|right to work in the (us|u\.s\.|united states)", ["I have permanent work rights","U.S. Citizen","US Citizen","I am a U.S. citizen","Citizen","Yes"]),   # US citizen
 (r"(authori[sz]ed|eligible|able|permitted|legally allowed) to (lawfully )?work .{0,80}without (the )?(need (for|of) |requiring |any )?(visa |employer |company |employment )?sponsorship", ["Yes","yes"]),   # "authorized ... without sponsorship" is a Yes, not a sponsorship request
 (r"(require|need)\b.{0,80}\bsponsor", ["No","no"]),   # any "will you require ... to sponsor" question, before rules that key on "employment authorization"
 (r"minimum (legal )?age|legal working age|(18|eighteen) (years of age|years old) or older|at least (18|eighteen)", ["Yes","yes"]),   # applicant: age 50
 (r"what state (will|do|would) you (currently )?(be )?(based|live|reside|work)|(which|what) state do you (currently )?(live|reside)|state (of|you) (residence|reside)|which state (will|do|are) you|in which state you (will )?(reside|live|work)", ["California","CA"]),   # Santa Clara, California
 (r"when would you be available to relocate|available to relocate", ["October 2026","November 2026","Within 1 month","Within 3 months"]),   # already lives in the Bay Area; available immediately
 (r"interview process .{0,80}(align|work) with your (availability|timeline)|timeline align with your availability", ["Yes","yes"]),
 (r"(professional|production|hands-on) (python|rust|c\+\+|go|golang|java|sql)|(python|rust|c\+\+|golang|sql|kubernetes|aws|gcp|terraform|kafka|pytorch|llm|rag) (development )?experience", ["Yes","yes"]),   # all on the resume
 (r"prior (healthcare|health care) (industry )?experience|experience in (the )?(healthcare|health care|health ?tech|digital health) (industry|space|sector)?|(healthcare|health care|health ?tech|digital health|hipaa|\bphi\b|\behr\b|\bemr\b|fhir|hl7|claims data|payer|health plan|medicare|medicaid|value-based care|senior care) (experience|background|industry|data|systems|environment|compliance)|experience (with|in|working with|handling) (healthcare|health care|hipaa|\bphi\b|protected health|\behr|\bemr|fhir|hl7|claims|payer|medicare|medicaid)", ["Yes","yes"]),   # applicant: has healthcare experience
 (r"prior (medical|clinical|pharma\w*|biotech) (industry )?experience", ["No","no"]),   # clinical / pharma / biotech: not in his background
 (r"prior start-?up experience|worked (at|in) (a|an early[- ]stage) start-?up|start-?up experience", ["Yes","yes"]),   # co-founder of Hyperion AI and Motocho; Ankr
 (r"agentic|ai-native", ["Yes","yes"]),
 (r"protected individual|1324b", ["A United States citizen or national","U.S. Citizen","US Citizen","Yes"]),   # US citizen
 (r"do you have a linkedin( profile)?", ["Yes","yes"]),   # profile link is on the resume (never used as the source)
 (r"high school diploma|\bged\b|secondary (school|education)", ["Yes","yes"]),   # B.Tech; completed secondary school
 (r"information you provide is accurate|information (provided|submitted) is (true|accurate|complete)|information i submit .{0,60}(true|accurate)|information provided .{0,40}(must be )?(accurate|truthful)|misrepresentation may result|certify that .{0,60}(true|accurate|complete)|by submitting your application you confirm", ["I confirm","Yes","I agree","I certify","Confirm"]),
 (r"staying hands-on|personally (written|shipped|built|wrote) (production )?code|shipping code and building prototypes", ["Yes","yes"]),
 (r"train/serve your own models|own models versus (using )?hosted|hosted ones|self-host(ed)? (models|llms?) (vs|versus|or)", ["Yes","yes"]),   # open-weight serving vs OpenAI APIs (Hyperion, Yahoo)
 (r"do you have a bachelor'?s|bachelor'?s degree\??$|do you hold a (bachelor|4-year|four-year)", ["Yes","yes"]),   # B.E./B.Tech
 (r"architected an ai agent or llm-powered system|llm-powered system that ran in production", ["Yes","yes"]),   # Yahoo Finance RAG research assistants (2022-2023); Hyperion AI agents
 (r"personally author(ed)? the technical design", ["Yes","yes"]),
 (r"how familiar were you with|familiar with (our company|us) before", ["I had heard of","I was already familiar","Somewhat familiar","Familiar"]),   # fintech/AI companies the applicant knows of
 (r"(previous|former|past|worked (for|at)|employed (by|at)|employee of).{0,60}\b(yahoo|jp ?morgan|chase|morgan stanley|bloomberg|cadence|ankr|bank of america|merrill|barclays|mantara|hold brothers|compunnel|motocho|hyperion)\b|\b(yahoo|jp ?morgan|morgan stanley|bloomberg|cadence|ankr|bank of america|barclays)\b.{0,40}(employee|contractor|before|previously)", ["Yes","yes"]),   # the applicant's real past employers
 (r"(been|are you) a (previous|former|past) .{0,30}(employee|contractor|intern)|previously (been )?employed (by|at)|worked (for|at) .{0,30} (before|previously)", ["No","no"]),   # none of these companies
 (r"(shipping|shipped) software for a commercial product in the data|data, database, data infrastructure, streaming", ["Yes","yes"]),   # Yahoo Finance market-data streaming; Kafka/Redpanda, KDB
 (r"best represents your strongest technical expertise|strongest (technical )?(area|expertise)", ["Distributed Systems","Stream Processing","Systems","Backend"]),
 (r"work onsite at our office in (palo alto|san francisco|mountain view|sunnyvale|san jose|santa clara|menlo park|redwood city|san mateo|oakland|berkeley|south san francisco|foster city|bay area)", ["Yes","yes"]),   # Bay Area on-site/hybrid is fine
 (r"^(current|most recent) ?(/|or)? ?(most recent )?employer\??\*?$|(who|what) is your (current|most recent) employer|^(current|present) (company|employer)\??$", ["Hyperion AI","Hyperion","Other","Not listed","None of the above","N/A"]),   # picked from a company list: Hyperion AI is not on AV-industry lists, so Other
 (r"security[- ]clearance status|best describes your .{0,30}clearance", ["I have never held a clearance but am willing","never held a clearance but am willing to undergo","None, but willing","No, but I am willing","None"]),   # US citizen, never held a clearance
 (r"years of (people|team|engineering|direct) management|years (have you )?(managed|managing|leading) (people|teams|engineers)|years of (people )?leadership", ["10+","10+ years","8+","7+","5+","5+ years","More than 5 years","5 or more"]),   # managing teams since the JPMorgan / Morgan Stanley lead roles
 (r"what country do you (currently )?(reside|live)|which country (do|are) you (currently )?(reside|live|based)|^(current )?country of residence\??\*?$|what is your (current )?country of residence", ["United States","United States of America","USA","US","U.S."]),
 (r"most influenced your decision to apply|influenced you to apply", ["*Other","Other","Company Website","Company website","Careers page"]),   # found on the company's own job board
 (r"personally built with or operated in production", ["Kafka","Spark","Kubernetes","AWS","Terraform or IaC","vector databases (Qdrant/Pinecone/Weaviate)","Postgres/MySQL at scale"]),   # all on the resume
 (r"identify as (currently )?living with the following disabilit|living with (a|the following) disabilit", ["None of the above","I do not have a disability","No disability","None","I don't wish to answer","Prefer not to answer"]),   # no disability
 (r"(communications|marketing|advertising|creative|pr) agency", ["No","no"]),
 (r"current employer have any restrictions|restrictions on your ability to (work|join)|restrict(s|ed)? (you|your ability) from (working|joining)", ["No","no"]),   # no non-compete or restriction
 (r"(able|eligible|authori[sz]ed) to (legally )?work in the (region|country|location) you are applying", ["Yes","yes"]),   # US citizen; US roles only
 (r"deemed export", ["No","no"]),   # US citizen: the deemed-export rule does not apply
 (r"which time zone would you be working|time ?zone (will|would) you (be )?work|time ?zone (are|will) you (be )?(based|located|working)", ["Pacific Time","Pacific","PT","PST","Pacific Time (PT)"]),   # Santa Clara, CA
 (r"currently hands-on with|contributing production-level code|hands-on .{0,60}production(-level| level)? code", ["Yes","yes"]),
 (r"experience with llm-as-judge|llm-as-a-judge|llm as (a )?judge", ["I've experimented with it in my own projects"]),
 (r"requir\w* (spon?orship|sponsership)", ["No","no"]),   # misspelt "sponsorship" on some forms; US citizen needs none
 (r"from 0.?(→|->|to).?1|0 ?to ?1 .{0,40}(model|ml)|new ml model or ml-powered system", ["Yes","yes"]),   # Yahoo TFX recommendation/clustering models, Hyperion fraud-detection ML
 (r"metaview|ai notetaking tool|record(ing)? and summariz", ["Yes","yes"]),   # consent to an AI notetaker in interviews
 (r"what is your (current )?age|^your age$|^age$|current age|how old are you|age (range|group|bracket)", ["50-59","50 - 59","50 to 59","50-54","50 - 54","45-54","50+","50 or older","Over 50"]),   # applicant: age 50
 (r"(40|forty) (years (of age|old) )?or older|over (the age of )?(40|forty)|at least (40|forty)", ["Yes","yes"]),   # applicant: age 50
 (r"based out of our (nyc|new york)|(nyc|new york) (headquarters|hq|office).{0,80}(situation|describes)|relocate to (nyc|new york)", ["I'm not in NYC yet, but I'm able and willing to relocate within 3 months of starting.","willing to relocate","able and willing to relocate","Yes","yes"]),   # applicant: will move to NYC
 (r"geographical requirements", ["I can be based in the US where I do not need visa support"]),
 (r"delivered production technical solutions in complex enterprise", ["Yes, and I've led strategic enterprise deployments","Yes, regularly"]),
 (r"knowledge/experience do you have with n8n|experience (do you have )?with n8n", ["I've used other automation tools in current or previous roles"]),
 (r"worked with hands-on in production", ["REST or GraphQL APIs","OAuth/OIDC or other authentication/authorization patterns","Webhooks or event-driven architectures","Data transformation/mapping between systems","Queues, messaging, or asynchronous processing","Custom connectors, nodes, plugins, or SDKs"]),
 (r"experience building reusable integrations", ["I've owned reusable integration frameworks or similar platform capabilities","I've built reusable integrations used across multiple teams/customers"]),
 (r"countries where we cannot have|all-remote .{0,60}(country|countries)", ["I am authorized to work in the country due to my nationality."]),
 (r"status that allows you to work and live", ["I am a citizen / permanent resident of the country where I plan to live & work from."]),
 (r"authori[sz]ed to (reside and )?work in the country", ["Yes","yes"]),
 (r"based in san francisco or open to relocating", ["San Francisco based","San Francisco","Bay Area"]),   # lives in Santa Clara (Bay Area)
 (r"hear about trm", ["I have read and understand the expectations of working at TRM. I understand this is a high intensity, high ownership environment, and I wish to be considered for a role with these expectations."]),
 (r"employment may be contingent upon|confirm (my|your) understanding", ["I confirm my understanding.","I confirm","Yes"]),
 (r"sharing this information is optional.{0,80}people operations", ["No","no"]),
 (r"long hours .{0,30}performance culture|strong performance culture", ["Yes","yes"]),
 (r"joined a company at an early stage|founding engineer or one of the first engineering hires", ["Yes","yes"]),   # co-founder of Motocho and Hyperion AI
 (r"manage(d)? a platform ?(/|or) ?service team", ["Yes","yes"]),
 (r"do you use ai tools in your (professional|personal|daily|everyday|work)", ["Yes - regularly","Yes, regularly","Yes"]),
 (r"consider yourself to be trans|transgender", ["I prefer not to answer","Prefer not to answer","I prefer not to say","Decline to self-identify","I don't wish to answer"]),
 (r"(currently|previously) .{0,20}engaged with .{0,60}(employee|affiliate)", ["No","no"]),
 (r"(located|based|reside|residing|live|living) in (north america|the americas|the us or canada|us or canada|canada or the (us|united states))", ["Yes","yes"]),
 (r"authori[sz]ed? .{0,40}without (company |employer |visa |any )?sponsorship|without (company |employer |visa )?sponsorship|legal(ly)? authori[sz]ation to work in the (us|u\.s\.|united states)", ["Yes","yes"]),   # US citizen: authorized without sponsorship
 (r"(require|need|will you .{0,30}require) .{0,30}(work authori[sz]ation|visa|sponsorship|immigration)", ["No","no"]),   # US citizen: will never require work authorization / sponsorship (Wellfound's standard question)
 (r"(5|five) days? (per|a|each) week|five days a week|5 days/week|(5|five)[- ]days? (on-?site|in[- ]office|in[- ]person)", ["Yes","yes"]),   # applicant: any work mode in the Bay Area (NYC on-site roles are filtered out before applying)   # applicant: no fully on-site 5-day roles
 (r"engineering blog|influence your decision|how much did .{0,60}influence", ["3 = Neutral","Neutral","3","Moderate","4 = Moderate"]),   # marketing-attribution scale questions
 (r"level of experience with (ai|llm|genai|generative ai|ai tools|coding assistants)|experience with ai (tools|coding)|proficien(cy|t) with ai|how (often|much) do you use ai", ["4 - Cross-functional","Cross-functional","Expert","Advanced","Extensive","Daily","Every day","Power user","5","4"]),   # AI-tooling experience scale (not an AI-disclosure question)
 (r"personally built|built and (operated|shipped|deployed)|(built|shipped|deployed|operated) .{0,30}(ai agent|agentic|llm|ml model|machine learning).{0,30}(production|in prod)|production (ai|ml|llm|agent)", ["Yes","yes"]),   # hands-on AI/agent production experience
 (r"grow into (greater )?leadership|developed? another (engineering )?leader|helped another engineer|grow(n)? (an engineer|engineers) into|promoted .{0,30}(engineer|report)s? (to|into)", ["Yes, I developed an engineer into","Yes, I coached","Yes, I have","Yes","yes"]),   # has grown engineers into leads/managers (CTO, Chief Architect)
 (r"partner(ed|ship)? with product|collaborat\w* with product|co-?own(ed)? product|work(ed)? with product (teams|managers)", ["I co-owned product direction","Co-owned","I regularly collaborated","Regularly","Yes"]),   # co-founder/CTO: co-owned product direction
 (r"formal(ly)? (people |line )?manag|people management experience|formal manager", ["I have been the formal manager","Formal manager","I have managed","Yes","yes"]),   # has been the formal manager of engineers
 (r"accommodation|assistance to participate|reasonable adjustment", ["No, I do not require","No, I do not","No","no"]),   # no accommodation needed
 (r"how often did you (interact|work|meet|communicate)|how frequently .{0,40}(stakeholders|customers|clients)|interact directly with (non-technical|customers|clients|stakeholders)", ["Daily","Every day","Weekly"]),   # CTO/co-founder: daily stakeholder contact
 (r"coordination hours|core (working )?hours|available for meetings|impromptu communication|overlap(ping)? hours", ["Yes","yes"]),
 (r"headquartered in .{0,40}(mountain view|san francisco|palo alto|menlo park|sunnyvale|san jose|santa clara|redwood city|san mateo|oakland|berkeley|bay area|cupertino|foster city|burlingame|los altos|campbell|milpitas)", ["Yes","yes"]),   # applicant lives in Santa Clara
 (r"authori[sz]ed to (to )?work|allowed to work in the (us|u\.s\.|united states)|lawfully in the united states", ["Yes","yes"]),
 (r"client-?facing|customer-?facing", ["Yes","yes"]),
 (r"active interview process|currently interviewing elsewhere|other interview processes", ["Yes","yes"]),
 (r"min(imum|\.)? (bs|b\.s\.|bachelor)|bachelor.{0,20}computer science|bs in computer science", ["Yes","yes"]),
 (r"frequent travel|requires? .{0,20}travel", ["Yes","yes"]),
 (r"able to work in the location listed|work (in|from) the location (listed|for this role)", ["Yes","yes"]),
 (r"currently interviewing or actively being considered for a role at|being considered for (another|a) role at", ["No","no"]),
 (r"where in the americas|which region .{0,20}americas", ["USA","United States","US"]),
 (r"on-?call", ["Yes","yes"]),
 (r"heard of .{0,30} before applying|heard of us before", ["Yes","yes"]),
 (r"contact your .{0,30}employers?", ["Yes","yes"]),
 (r"ever been fired|asked to resign|terminated from (a|any) (job|position)", ["No","no"]),
 (r"essential functions of (this|the) job|with or without reasonable accom", ["Yes","yes"]),
 (r"authori[sz]ed to be employed", ["Yes","yes"]),
 (r"rate .{0,40}position in ai|compared to other tech companies", ["Excellent","4 - Among the leaders in the industry","Among the leaders in the industry","4"]),   # applicant: "Excellent"
 (r"current .{0,25}customer or employed by|are you a current .{0,20}customer", ["No","no"]),
 (r"portfolio of ml models across the payments|payments lifecycle", ["Yes","yes"]),   # applicant: yes
 (r"location would you be interested in working|which (office|location) .{0,40}(days|week)|(3|three) days/?week", ["San Francisco","SF","San Francisco Bay Area","Bay Area"]),
 (r"athlete|esports? (competitor|player)|professional (gamer|player)|participate in (games|contests)", ["No","no"]),
 (r"proof of (employment |work )?authori[sz]ation|employment authori[sz]ation|provide (proof|documentation) .{0,30}(eligib|authori)", ["Yes","yes"]),
 (r"(EST|EDT|ET|Eastern|PST|PDT|PT|Pacific|CST|Central|MST|Mountain)\b.{0,30}(business )?hours|work (in|during) .{0,20}(time ?zone|hours)|overlap with .{0,30}(hours|time ?zone)", ["Yes","yes"]),   # remote: works any US business hours
 (r"credentialed|been a (client|patient|provider|therapist|customer) of|used our (product|service|platform) as a", ["No","no"]),   # never a provider/client of the hiring company
 (r"immediate family|relatives? (who )?(work|employed)|family members? (who )?(work|employed)|debarred|excluded by the OIG|convicted|felony|criminal|non-?compete|conflict of interest|restrictive covenant", ["No","no"]),   # compliance questions: none apply
 (r"are you ready|ready to (take|do|complete|go through|participate)|actively involved in product development|technical (portion|assessment|interview|screen|take-?home|challenge)|hands[- ]on (coding|technical)|comfortable (writing|with) code|still (write|writing) code|willing to (code|write code)", ["Yes","yes"]),   # hands-on leader: yes to technical interviews
 (r"^location( \(city\))?$|^(current |your |home )?location$|^city$", ["Santa Clara, California, United States","Santa Clara, CA","California, United States","United States","Santa Clara, California","Santa Clara County, California"]),   # applicant (2026-10-04): take whatever the place picker offers - city first, else California/United States (some pickers only suggest regions)
 (r"select your (current )?location|your current location|which (hub|location|city|metro) (are you|is closest|do you)|where (are|do) you (currently )?(based|live|located|reside)", ["San Francisco Bay Area","SF Bay Area","Bay Area","San Francisco","San Jose","Santa Clara","Bay Area, CA","California","Remote, United States","Remote - United States","Remote (US)","US Remote","United States","Remote","Outside of","Outside the","Other location","Elsewhere","Other","None of the above"]),
 (r"sponsor", ["No","no"]),
 (r"interviewed .*before|applied .*before|previously (applied|interviewed)", ["No","no"]),
 (r"in[- ]person|open to working|come into the office|days? (a|per) week|times (a|per) week|commit to being in|being in (one of )?(these|our|the) offices?|days (from|in|at) (one of )?our office|office hub", ["Yes","yes"]),
 (r"understand that .{0,40}(may )?use ai|company may use ai|we (may )?use ai|ai tools to assist in the (application|interview)", ["Yes","I understand","I acknowledge","Acknowledge"]),
 (r"how (do )?you use ai|use ai tools today|describes (how )?you use ai|your (use|usage) of ai tools|ai (proficiency|fluency)", ["I design or automate workflows with AI","I regularly use AI tools","I have experimented with AI tools","Advanced","Expert"]),
 (r"ai agent (applying|submitting)|applying on behalf of (a|the) candidate|are you an ai|automated (agent|applicant|submission)", ["__ASK__"]),   # an employer asking whether an AI agent is applying: the applicant answers this, never the filler
 (r"ai policy|(did|have) you use(d)? (any )?ai|without (the use of )?(any )?ai|no ai (assistance|tools)|ai.{0,20}(was|were) not used|(did not|didn't|have not) use.{0,20}ai|used? ai (to|in|for) (this|the|your|my) application|ai assistance", ["__ASK__"]),
 (r"authori[sz]ed to (lawfully |legally )?work|lawfully work|authori[sz]ation to work|legally (able|eligible|authorized)|work authori[sz]ation|eligible to work|right to work|employment eligibility",["Yes, without company sponsorship","Yes, without sponsorship","Yes - without sponsorship","Yes, I do not require sponsorship","Yes","yes","Can work for any employer","Any employer","I am authorized","Authorized","U.S. Citizen","US Citizen","Citizen"]),
 (r"currently an? .{0,60}(employee|contractor|intern)\b|current(ly)? (employee|contractor) of|employed by .{0,40}(currently|now|today)|(ever|previously|formerly) been (an? )?(employee|contractor|intern|employed)", ["No","no"]),   # not a current or former employee of the hiring company
 (r"experience with (aws|gcp|azure|the cloud|cloud (platforms|infrastructure)|kubernetes|terraform)|describe your (level of )?experience (with|in)", ["Both hands-on","Both","Hands-on experience operating","Hands-on","Expert","Advanced","Extensive","Very experienced","10+ years","5+ years"]),   # hands-on and led teams
 (r"\bFINRA\b|series (7|24|27|63|65|66|99)\b|securities licen[sc]e", ["No","no"]),
 (r"(taiwan|chin(a|ese)|india|indian|canad(a|ian)|mexic|korea|japan|uk|british|german|french|israel|singapore|brazil|european|eu|foreign|other) (citizen|national|passport)|citizen of (?!(the )?(u\.?s|united states|america))", ["No","no"]),   # US citizen only
 (r"citizen", ["Yes","U.S. Citizen","US Citizen"]),
 (r"^(?!.*(indicate|select|provide|enter|choose|which|what)\b.{0,25}\bstate\b).*(reside|live|based|located|living) in the (united states|u\.?s\.?a?\b|usa)", ["Yes","yes"]),
 (r"(?=.*(san francisco|bay area|california|santa clara|san jose|palo alto|silicon valley|united states|\bu\.?s\.?a?\b))(currently |are you |do you )?(located|based|residing|reside|live|living) (in|within|near)", ["Yes","yes","I currently live","I live in"]),   # the applicant lives in Santa Clara, CA
 (r"(?!.*(san francisco|bay area|california|santa clara|san jose|palo alto|silicon valley|san ramon|pleasanton|dublin, ca|walnut creek|concord, ca|livermore|hayward|san leandro|union city|campbell|los gatos|saratoga|belmont|san bruno|millbrae|daly city|alameda|richmond, ca|emeryville|novato|san rafael|half moon bay|danville|lafayette, ca|morgan hill|gilroy|newark, ca|united states|north america|\bu\.?s\.?a?\b))(currently |are you |do you )?(located|based|residing|reside|live|living) (in|within|near) ", ["No","no"]),   # any other named place (NYC, Chicago, Taipei, ...): the applicant is in Santa Clara, CA
 (r"currently live (in|or)|live (in|near) (this |the )?(job|role|position)|live or (are you )?willing to relocate", ["I currently live in this job's location","I currently live","I live in","Yes, I live","I am willing to relocate","Willing to relocate","Yes"]),
 (r"relocat", ["Yes","yes"]),
 (r"remote|hybrid|on-?site|in[- ]office|work from|commut", ["Yes","yes","Hybrid","Remote"]),
 (r"pronoun", ["He / Him","He/Him","He/him","He, him","He"]),
 (r"have you (ever )?used|are you a (current )?(user|customer)|used (our|the) (product|app|platform)", ["Yes","yes"]),
 (r"FHIR|HL7|CCDA|HIPAA|\bPHI\b|\bEHR\b|EMR\b|healthcare partner|ICD-?10|CPT codes|claims data|payer", ["Yes","yes"]),   # applicant: has healthcare experience
 (r"clinical|medical device|\bFDA\b|GxP|pharma", ["No","no"]),   # clinician / device / pharma work is not in his background
 (r"previously,? (applied|worked|employed)|currently,? (or have you|work|employed)|currently employed by|worked (for|at) .* before|have you (ever )?worked (at|for)|worked at .*(employee|contractor|consultant)|former .{0,30}employee|current .{0,30}employee|current or former|former or current|ever (worked|been employed)(?! (with|on|in|using|across|alongside|as an? (engineer|developer|architect|lead|manager))\b)|(previously|ever) been employed|been employed (at|by|with)",["No","no","I have not previously been employed","I have not been employed","I have not worked","have not worked","have not been","Never worked","Never","None of the above","Not applicable","N/A"]),
 (r"(experience|worked|work(ing)? with|proficien\w*|familiar\w*|expertise|hands-on|used|built|developed|certified).{0,80}(?<![a-z0-9])(salesforce|apex|sap|abap|servicenow|workday (hcm|financials|integrations?)|netsuite|dynamics 365|unity|unreal|game engine|swiftui|ios development|android development|kotlin|php|laravel|ruby on rails|epic (ehr|systems)|cerner|hl7|verilog|vhdl|systemverilog|rtl design|plc|autocad|solidworks|cobol|mainframe|sharepoint|power bi|tableau developer|figma|neo4j|graph database|cypher|mongodb|dynamodb|snowflake|dbt|looker|react native|angular(js)?|vue(\.?js)?|next\.?js|svelte)(?![a-z0-9])", ["No","no"]),   # not on the resume: answer honestly
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
 (r"(which|what) (departments?|teams?|functions?|areas?) (are|would) you (be )?interested in|departments? of interest", ["Engineering","Software Engineering","Technology","Engineering & Technology","Product & Engineering","Data Science","Data","Research & Development","IT"]),
 (r"office location|preferred (office|location|hub)|which office|office (would|do|will) you|closest office|nearest office",["Menlo Park","San Francisco","Santa Clara","Sunnyvale","Mountain View","Palo Alto","San Jose","Bay Area","California","Remote","New York"]),
 (r"hispanic|latino", ["No","I am not Hispanic or Latino","Not Hispanic or Latino"]),
 (r"\brace\b|racial|ethnic|hispanic|asian|caucasian|african", ["I don't wish to answer","Do not wish to identify","I do not wish to identify","I do not wish to answer","Decline to State","Decline to state","Decline To Self Identify","Decline to self identify","Decline to self-identify","I choose not to disclose","Choose not to disclose","I prefer not to disclose","Prefer not to disclose","I choose not to self-identify","Not disclosed","Decline","Prefer not to say","Prefer not to answer","I do not wish to answer","I don't wish","Asian: Indian","Asian - Indian","Asian Indian","Asian or Indian Subcontinent","Asian (Indian)","South Asian","Asian","Asian (Not Hispanic or Latino)","Asian or Asian American"]),   # applicant: Asian (Indian) where no decline option exists; never a bare "Indian" (would match American Indian)
 (r"golden record|master data management|\bMDM\b|data governance (lead|owner)|chief data officer", ["No","no"]),   # not in the applicant's background: answer honestly
 (r"support of .{0,40} to maintain (that |your )?(work )?authori[sz]ation|maintain (that |your )?(work )?authori[sz]ation|visa support|immigration support", ["No","no"]),
 (r"how much notice|notice period|notice do you (require|need)", ["Immediate","Immediately","None","No notice required","Less than 1 week","1 week","2 weeks","Two weeks","Less than 2 weeks","Less than 1 month"]),   # applicant: two weeks' notice
 (r"compensation is standardi[sz]ed|comfortable with the (salary|compensation|pay)|salary (range |band )?(is )?non-negotiable|salary being offered|within (the|this) (salary|compensation|pay) range|acceptable to you|expectations? (align|aligned|fit|fall) with(in)? the (salary|compensation|pay)|(listed|posted|stated) (salary|compensation|pay)( range)? (meet|meets|match|fit)|(salary|compensation|pay|expectations?) (fall|falls|fit|fits) with(in)? (our|the|this) (estimated |posted |listed )?(salary |pay |compensation )?range|(salary|compensation|pay) range (listed|posted|in the job)", ["Yes","yes","I understand","Yes, I understand"]),   # applicant: salary is not a filter
 (r"(directly |previously |ever )?managed (a |an )?(team|engineers|people|direct reports|software)|people manag|managed (software|ml|ai) engineers|have you (been|served as) (a |an )?(engineering |people )?manager", ["Yes","yes"]),
 (r"(willing|able|open|available)[^.?]*travel|travel (twice|once|up to|\d+ ?%|a quarter|per (month|quarter|year))|travel requirement", ["Yes","yes"]),
 (r"export control|u\.?s\.? person|ITAR|EAR", ["U.S. Citizen","US Citizen","U.S. citizen or national","I am a U.S. person","Yes","A"]),   # US citizen: option A on lettered export-control lists
 (r"veteran|military", ["I am not a veteran","I am not a protected veteran","I AM NOT A VETERAN","No military service","I have not served","No","Decline To Self Identify","I don't wish to answer","I do not wish to self-identify","Prefer not to say"]),
 (r"disabilit", ["No, I do not have a disability","No, I don't have a disability","No","I do not have a disability","I don't wish to answer"]),
 (r"18\+|18 (years|or older)|age of 18|over 18|at least 18", ["Yes","yes"]),
 (r"subject to (any )?(employment (agreement|restriction|contract|covenant)|non-?compete|restrictive|post)|post-?employment restriction|restrictive covenant|non-?solicit|bound by (a|any) (non-?compete|agreement)", ["No","no","None"]),
 (r"\bsms\b|whatsapp|text message|receive (communications|updates|marketing|alerts)|marketing communications|newsletter|opt.in|stay up to date|keep me (updated|informed)|job alerts|similar jobs|careers content", ["No","no"]),
 (r"background check|drug|non-?compete|agreement|acknowledge|certify|consent|privacy|terms|policy|subscribe|agree|gdpr|disclosure|notice",["Yes","I agree","I acknowledge","I consent","Consent","Confirmed","Confirm","I have read","Acknowledge","Agree","Accept","yes"]),
 (r"how did you (first |initially )?(hear|learn|find out)|hear about|learn about|find out about|source", ["Company Website","Company website","Company Careers","Careers Site","Career Site","Careers Website","Career Website","Careers Page","Career Page","Website","Careers","Job Post Site","Job Board","Other","Job Board","Other/Not Listed","Google Search","Search engine","Careers page","Career Page"]),
 (r"(undergrad\w*|bachelor\w*|degree).{0,80}(us|u\.s\.|united states|american) (university|college|school|institution)", ["No","no"]),   # degree is from the University of Madras (India)
 (r"school|university|college", ["University of Madras","Other","School Not Listed","Other Institution","Madras University","Other School","Not Listed"]),   # never a partial match on some other university's name
 (r"discipline|major|field of study", ["Computer Science","Computer Engineering","Engineering","Other"]),
 (r"degree|education|highest level", ["Bachelor of Engineering","Bachelor's Degree","Undergraduate/Bachelor's degree","B.E.","BE","Bachelor of Technology","B.Tech","Bachelor of Science","Bachelor's","Bachelors","Bachelor","BS/BA","BA/BS","B.S./B.A.","BS","B.S.","Bachelor of Science","College Degree","4-year degree","Four-year degree","University degree","Bachelor degree","Bachelors degree","Bachelor\u2019s degree","Bachelor"]),
 (r"outside business|advisory|consulting|consultanc|freelance|board (role|membership)|side business|other business|own, operate|provide services to|conflict of interest|moonlight", ["No","no","None"]),
 (r"family member|relative|personal relationship|related to (anyone|any employee|an employee)|know anyone|referred by|were you referred|referred to this", ["No","no","None"]),
 (r"been employed by|employed by .* in the past|(worked|employed|interviewed|applied|contracted|consulted) .{0,60}in the past|in the past .{0,40}(worked|employed|interviewed|applied)", ["No","no","Never"]),
 (r"security clearance|clearance", ["No","None","no"]),
 (r"professional engineer \(pe\)|professional engineer licens|\bpe licens|licensed professional engineer|fundamentals of engineering|\bfe exam\b|engineer[- ]in[- ]training", ["No","no","None"]),
 # --- recurring dropdowns that used to be left for the user (answer-every-question) ---
 (r"years? of (professional |relevant |software |industry |work |engineering )?experience|how many years|years in the (software )?industry", ["25+","25+ years","25","20+","20+ years","20","15+","15+ years","15","10+","10+ years","10","8+","7+","6+","5+","5+ years","5"]),   # 25+ years: take the highest band offered
 (r"willing to work (on[- ]?site|in[- ]?(the )?office|from (the|our) office)|work on[- ]?site|onsite (role|position|work)|able to work (on[- ]?site|in[- ]office)|commute to (the )?office", ["Yes","yes"]),   # only Bay Area onsite roles reach this queue (Santa Clara based)
 (r"python (proficiency|experience|skill)|proficien(cy|t) (in|with) python|describe your python", ["Advanced","Advanced — regularly build production solutions or substantial integrations","Expert","Proficient","4","5"]),
 (r"accurately reflect|(information|details) (i|you) (submitted|provided|entered) (is|are) (accurate|true|correct)|my own (employment|work) history", ["Yes","I confirm","Confirm","I agree"]),   # résumé/application accuracy confirmation
 (r"professional languages? spoken|languages? (you )?(speak|are fluent)|fluent languages?", ["English","english"]),
 (r"(currently|previously|ever) (been )?(employed|worked) (by|at|for|with)|former (employee|contractor)|have you (ever )?worked (for|at)|employment history (with|at)", ["No","I have never","Never","None","I have not"]),   # never worked for the hiring company   # applicant holds no PE/FE license -> No
 (r"visa", ["No","no"]),
 (r"sanction|embargo|belarus|\bcuba\b|\biran\b|north korea|\bsyria\b|\brussia\b|following countries or regions|restricted (countr|region)", ["No","no"]),
 (r"country", ["United States","United States of America","USA"]),
 (r"\bstates?\b(?! of (the )?(art|mind))|province", ["California","CA","Another State in the US","Another state","Other US","Other"]),
 (r"experience with|familiar|proficien|(how many|number of|total|minimum of|at least) (\w+ )?years|years (of|in|with|working|leading|managing|building|hands)|years'? experience|how much (\w+ ){0,4}experience", ["25+ years","25+","20+ years","20+","More than 20 years","20 or more","15+ years","15+","15 +","16+","More than 15 years","15 or more","Over 15","15-20 years","15-20","13+","12+","11+","10+ years","10+","10 or more years","7 or more years","7+ years or more","More than 10 years","10 or more","Over 10","8+ years","8+","8 +","7+","6+","7+ years","6+ years","5+ years","5+","More than 5 years","5 or more","5-10 years","5 - 10 years","Expert","Yes","More than 13 years","More than 12 years","More than 10 years","10+ years","10+","10+ years","10+","8+ years","7+ years","5+ years","5+","4+ years","4+","3+ years","3+"]),
]
# ---- technical questions with no specific rule (applicant: never leave a technical question blank; answer from his real work)
PERSONAL_Q=re.compile(r"\bgaps?\b|\bearn\b|student (or temporary )?visa|temporary visa|on an? .{0,20}visa|visa (type|holder|status|expir)|\bf-?1\b|\bopt\b|\bcpt\b|h-?1b|green card|immigration|citizenship|salary|compensation|desired pay|\bpay\b(?!-)|\bpay (range|expectation)|visa (status|sponsor)|sponsor|work authori[sz]ation|authori[sz]ed to work|citizen|\bgender\b|\brace\b|ethnic|veteran|disabilit|pronoun|hear about|referr|start date|\bstart\b.{0,20}\b(role|position|job)|notice period|relocat|commut|\btravel\b|\bconvict|criminal|felony|background check|drug (test|screen)|non-?compete|non-?solicit|relatives? (who|employed|work)|family members?|government|sanction|export control|security clearance|\bclearance\b|e-?signature|your signature|\bi certify|certify that|attest that|acknowledge|consent|personally (completed|wrote|written|filled)|ai agent|this application|cover letter|\bresume\b|\bcv\b|your availability|\btime ?zone|sports|contest|how many years|years of|\bgpa\b|\bdegree\b|school|university|graduat|references\b|\bdate\b|your (name|address|city|state|zip|e-?mail|phone|linkedin|github|website|portfolio)|\b(zip|postal) code|where (are you|do you) (live|located|based)",re.I)
TECH_Q=re.compile(r"describe|explain|tell us|walk us|share|example|how (would|do|did) you|what (is|was|would)|design|approach|experience|built|build|architect|debug|trace|scale|system|technical|engineer|code|project",re.I)
TECH_BANK=[('healthcare|health care|health ?tech|digital health|hipaa|\\bphi\\b|protected health|\\behr\\b|\\bemr\\b|fhir|hl7|claims|payer|health plan|patient|care (delivery|coordination|management)|senior care|medicare|medicaid|value-based', 'Healthcare has been part of my work alongside financial services. I have built systems that handle protected health information under HIPAA with the same controls I use in regulated finance: role-based access and least privilege, encryption in transit and at rest, complete audit trails, de-identification for analytics and AI workloads, and BAA-aware reviews of every vendor and data flow. I have worked with healthcare data and workflows such as EHR/EMR integrations, FHIR and HL7 interfaces, and claims and eligibility data. At Hyperion AI I apply this to AI agents and data pipelines over sensitive records: evaluation gates before anything reaches production, human review for high-stakes outputs, and PHI-safe logging and tracing.'),('trace|tracing|debug|bug|incident|outage|post-?mortem|root cause|production (issue|problem|failure)|on-?call|langsmith|observab', 'At Hyperion AI our multi-agent loop (plan, validate, dispatch, replan) kept re-planning on a subset of benchmark tasks and burning its step budget, although every component looked correct in the code. I opened the full trace of one failing run in our tracing and replay harness (the equivalent of a LangSmith trace: every model call, tool call, input, output and latency as one tree). It showed that an MCP tool returned a truncated JSON payload once results passed a size limit, the validator scored the truncated result as a failed step, and the planner re-issued the identical call. Each part behaved correctly on its own; only the step-by-step trace exposed the interaction. The fix was pagination in the tool plus a validator check that tells truncation apart from failure, and that trace became a regression case in the replay suite.'), ('\\bllms?\\b|agent|agentic|\\brag\\b|retrieval|prompt|fine-?tun|evaluat|evals?\\b|inference|model serving|embedding|vector|genai|generative|machine learning|\\bml\\b|\\bai\\b|\\bmodels?\\b', 'At Hyperion AI (2023-present) I built our agentic AI platform end to end: MCP clients and servers (3 servers, 9 tools), a multi-agent plan-validate-dispatch-replan loop, open-weight model serving (Qwen, Llama 3.3-70B, gpt-oss) through llama.cpp and vLLM, fine-tuning and evaluation workflows, and a reproducible benchmarking platform with a 121-measure scorecard informed by MLPerf Inference and BFCL. Every change, human- or AI-written, went through evaluation gates and replay tests before production. Earlier, at Yahoo Finance, I architected OpenAI/LangChain RAG research assistants and led the 2023 Vertex AI proofs of concept with Google.'), ('data (pipeline|platform|infrastructure|model|warehouse|lake)|etl|elt|stream|kafka|event|spark|databricks|snowflake|warehouse|lakehouse|schema|batch', 'At JPMorgan Chase I architected journal and replay event streams for multi-asset trading, so every order event could be replayed deterministically for recovery, audit and testing. At Yahoo Finance I led the data paths behind quotes, charts, portfolios and screeners for about 40M daily users through the bare-metal-to-AWS migration. At Hyperion AI I built chain and RPC ingestion pipelines in Rust and Go with custody-sensitive reconciliation. My default stack is Kafka or Redpanda for events, Postgres for state, Spark or Databricks for batch, and explicit schemas and contracts between producers and consumers.'), ('payment|visa|mastercard|card network|issuing|acquir|trading|fintech|ledger|reconcil|crypto|blockchain|web3|defi|exchange|wallet|bank|financ|order', 'I have spent most of my career in financial systems: sub-250-microsecond multi-asset execution paths at JPMorgan Chase designed for the 100K-500K TPS range, trading and application platforms at Morgan Stanley, and systems at Bloomberg, Bank of America/Merrill and Barclays. At Hyperion AI I built digital-asset systems in Rust (Tokio), C++17 and Go/gRPC: chain and RPC ingestion, DEX routing, wallet analytics, custody-sensitive reconciliation and an Intel SGX-based exchange architecture. The constant across all of them is correctness first: idempotent operations, journals and replay, reconciliation, and latency budgets measured end to end.'), ('lead|manag|team|hire|hiring|mentor|coach|conflict|stakeholder|culture|people|org(ani[sz]ation)?', "As Chief Architect at Yahoo Finance I led 75+ engineers and partners through the platform's bare-metal-to-AWS migration; at JPMorgan Chase I led a 50+ person organization across the US, UK and India; and as CTO and co-founder of Hyperion AI I built and led the engineering team from zero. My approach: set a clear technical direction and a small number of standards, hire strong tech leads and give them ownership, keep design reviews and incident reviews blameless and concrete, and stay hands-on on the critical path so I can make informed trade-offs quickly."), ('startup|0 ?(to|-) ?1|zero to one|founding|founder|ambigu|mvp|prototype|ship|fast|early[- ]stage|scrappy|wear many hats', 'I have built from zero twice: as CTO and technical co-founder of Hyperion AI (agentic AI platform, open-weight model serving, benchmarking, and digital-asset systems) and as co-founder of Motocho. At Hyperion I wrote much of the critical-path code myself in Python, Rust, Go and C++, set up the infrastructure and evaluation gates, and shipped to customers with a very small team. I work well with ambiguity: I pick the smallest version that proves the idea, instrument it, and harden what users actually use.'), ('security|secur|sgx|enclave|attestation|custody|\\bkeys?\\b|compliance|privacy|soc ?2|pci|encrypt|auth|identity|threat', 'I design for security and compliance from the start: at JPMorgan Chase, Morgan Stanley, Bank of America/Merrill and Barclays that meant regulated, audited systems with strict change control; at Hyperion AI it meant custody-sensitive reconciliation, key handling and an Intel SGX-based exchange architecture. In practice: least-privilege access, secrets in a managed vault, encryption in transit and at rest, audit trails via journals, and threat modeling in design reviews.'), ('\\btest|quality|ci/?cd|deploy|release|devops|reliab|sre|slo|uptime|monitor', 'My standard for reliability is measurable: SLOs per service, dashboards and alerts through OpenTelemetry, Prometheus and Grafana, CI/CD with automated tests and staged rollouts, and a rollback plan for every release. At Yahoo Finance I ran the bare-metal-to-AWS migration with phased cutovers, rollback planning and 24x7 operation for about 40M daily users; at JPMorgan Chase deterministic replay of journaled events let us test changes against real production traffic before release.'), ('cloud|aws|gcp|azure|kubernetes|k8s|docker|terraform|infra|migrat|cost|scal', 'As Chief Architect at Yahoo Finance I led the move of the quotes, charts, portfolios, screeners and research platform (about 40M daily and 150M monthly users) from bare metal to AWS: phased migration, cutover and rollback planning, and 24x7 operation. I work with Kubernetes, Terraform and managed services on AWS, GCP and Azure, and I treat cost as a design input: right-sizing, autoscaling, and measuring cost per request alongside latency.'), ('frontend|front-end|react|ui\\b|user interface|full[- ]?stack|typescript|javascript|node', 'I work across the stack: backend services in Python, Go, Rust, C++ and Java, and web front ends in TypeScript/JavaScript with React and Node.js. At Yahoo Finance the platform served quotes, charts and portfolios to about 40M daily users, so front-end performance and API design mattered as much as the backend; at Hyperion AI I built the product end to end, from the agent services to the web UI.'), ('performance|latency|throughput|optimi|rust|c\\+\\+|golang|\\bgo\\b|memory|concurren', 'Performance work has been a constant for me: at JPMorgan Chase I architected sub-250-microsecond multi-asset execution paths in C++ and Java designed for the 100K-500K TPS range, and at Hyperion AI I built latency-critical services in Rust (Tokio), C++17 and Go/gRPC. My method is to set a latency budget per hop, measure end to end with percentiles rather than averages, remove allocations and locks on the hot path, and keep a replayable workload so every optimization is verified against real traffic.')]
TECH_DEFAULT='At JPMorgan Chase I architected multi-asset execution paths where being wrong costs money directly: sub-250-microsecond paths designed for the 100K-500K TPS range. As Chief Architect at Yahoo Finance I led the re-architecture of a platform serving about 40M daily users through its bare-metal-to-AWS migration, directing 75+ engineers. Most recently, as CTO and co-founder of Hyperion AI, I built an agentic AI platform end to end, with correctness gates, replay harnesses and observability in production. In each case I start from the requirements and failure modes, choose the simplest architecture that meets them, and make it measurable.'
NOT_MINE=re.compile(r"salesforce|\bsap\b|servicenow|camunda|snowflake|angular|\bphp\b|\bruby\b|rails|kotlin|swift\b|\bios\b|android|unity|unreal|mainframe|cobol|guidewire|pega|workday (integration|studio)",re.I)
def tech_answer(label):
    l=(label or "").lower()
    if PERSONAL_Q.search(l) or not TECH_Q.search(l): return None
    if re.match(r"\s*if (yes|so|applicable|other)\b",l):
        # a follow-up to a Yes/No question: N/A when the question was about something the applicant answers No to
        if NOT_MINE.search(label or "") or re.search(r"camunda|\bbpm\b|clinical|government|clearance|relative|referr|sponsor|visa|previous(ly)? (employ|work)|worked (for|at)|non-?compete|convict",l): return "N/A"
        l=re.sub(r"^\s*if (yes|so|applicable)[,:]?\s*","",l)
    ranked=sorted(TECH_BANK,key=lambda b: -len(re.findall(b[0],l)))
    hits=[b for b in ranked if re.search(b[0],l)][:2]
    ans=" ".join(b[1] for b in hits) if hits else TECH_DEFAULT
    m=NOT_MINE.search(label or "")
    if m:   # never imply hands-on experience with a stack the applicant has not used
        ans=f"My production work has been in Python, Go, Rust, C++, Java and C#/.NET on AWS, GCP and Azure rather than {m.group(0).strip()}, so here is the closest comparable experience. "+ans
    return ans
JOB_CHOICE_RULES=[]; JOB_TEXT_RULES=[]   # set per application in run_one (e.g. "have you applied here before", from our own records)
def pick(label,rules):
    l=label.lower()
    if rules is CHOICE_RULES: rules=JOB_CHOICE_RULES+rules
    elif rules is TEXT_RULES: rules=JOB_TEXT_RULES+rules
    for pat,val in rules:
        # lowercase alternatives match the lowercased label; CAPITALISED acronyms (EAR, ITAR, EST, FINRA) match only where the
        # original label has them in capitals, so 'EAR' never matches 'hear' / 'year' / 'learn'
        if re.search(pat,l) or (re.search(r"[A-Z]",pat) and re.search(pat,label)):
            if JOB_WHY and isinstance(val,str) and val==ANS.get("why_us",""): return JOB_WHY   # company- and role-specific "why us"
            return val
    return None
JOB_WHY=""
WHY_BY_CAT={
 "fintech":"it sits where I have spent most of my career: financial systems where correctness, latency and trust matter. I have built trading and market-infrastructure systems at JPMorgan Chase, Morgan Stanley and Bloomberg, and digital-asset systems at Hyperion AI, and this role lets me apply that directly while building modern, AI-enabled platforms",
 "agentic":"you are putting AI agents into production, which is exactly where I have been doing my hands-on work: at Hyperion AI I built an agentic platform (MCP tools with allowlists and budgets, a plan-validate-dispatch-replan loop, evaluation and replay gates), and this role is a chance to bring that, plus 25 years of large-scale systems experience, to a team shipping it to real users",
 "inference":"model serving and inference performance is where I have been spending my hands-on time: at Hyperion AI I built and profiled open-weight model serving (llama.cpp and vLLM, prefill/decode throughput, TTFT and TPOT), and I want to do that at your scale",
 "leadership":"the role combines what I do best: building and leading engineering teams while staying close to the architecture and the critical-path code. I led 75+ engineers at Yahoo Finance and a 50+ person organization at JPMorgan Chase, and co-founded Hyperion AI as CTO",
 "platform":"the work is the kind of platform I have spent my career building and operating: large-scale, reliable, cost-aware systems such as Yahoo Finance's move to the cloud for about 40M daily users and low-latency services at JPMorgan Chase. I like owning the architecture and the critical-path code together, and this role combines both",
}
def why_for(company,title,desc):
    """A short, specific 'why us' for this company and role (the fit paragraph follows the posting's category)."""
    cat=cover.category(title or "",desc or "")
    co=(company or "your team").strip()
    return (f"I want to join {co} as {title} because {WHY_BY_CAT.get(cat,WHY_BY_CAT['platform'])}. "
            "I still write critical-path code in Python, Go, Rust and C++, I measure what I build, and I am based in Santa Clara, CA with no sponsorship needed.")
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
EDU_DATE_JS=r"""(el)=>{const i=(el.tagName==='INPUT'||el.tagName==='SELECT')?el:(el.querySelector('input,select')||el);
  const id=i.id||''; if(/^(start|end)-(month|year)--\d/.test(id)) return true;
  const box=i.closest('[class*=education],[id*=education],[data-section*=education]'); if(!box) return false;
  return /date|month|year|graduat/i.test((document.querySelector('label[for="'+CSS.escape(id)+'"]')||{}).innerText||i.getAttribute('aria-label')||id);}"""
EDU_START=(1991,"August"); EDU_END=(1995,"May")   # University of Madras, B.E. Computer Science and Engineering (applicant: 1991-1995)
def edu_value(lab,h=None):
    l=(lab or "").lower(); end=bool(re.search(r"\bend|to\b|graduat|finish|complet",l))
    y,m=EDU_END if end else EDU_START
    if "month" in l: return m
    if "year" in l: return str(y)
    return None
async def is_edu_date(h):
    """An education start/end date field. The resume gives no graduation years, so these are never guessed."""
    try: return await h.evaluate(EDU_DATE_JS)
    except Exception: return False
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
async def autocomplete_fill(page,h,text,prefer,strict=False,retry_texts=()):
    """Type into an autocomplete box and pick the first matching suggestion. strict: only a suggestion matching prefer
    (never the first one or Enter), trying retry_texts in turn; a wrong city is worse than an empty field."""
    if strict:
        for t in (text,)+tuple(retry_texts):
            got=await autocomplete_fill(page,h,t,prefer,strict=False,retry_texts=("__strict__",))
            if got=="picked": return got
            if got=="nosugg": return "typed"   # a plain text box (no suggestion list): the typed city stays
        try: await h.fill(""); await dismiss_menu(page,h)
        except Exception: pass
        return None
    try:
        await h.scroll_into_view_if_needed(timeout=3000); await h.click(timeout=3000); await h.fill("")
        await h.type(text,delay=40); await page.wait_for_timeout(1800)
        opts=page.locator('[role="option"]:visible:not(.iti__country), [role="listbox"] li:visible, [class*="dropdown"] li:visible, [class*="option"]:visible, [class*="Option"]:visible, [class*="suggestion"]:visible')
        n=await opts.count()
        if retry_texts==("__strict__",) and n==0: return "nosugg"
        for i in range(min(n,30)):
            o=opts.nth(i)
            try:
                if await o.is_visible() and re.search(prefer,await o.inner_text(),re.I): await o.click(timeout=3000); await page.wait_for_timeout(500); return "picked"
            except Exception: pass
        if retry_texts==("__strict__",): return None
        for i in range(min(n,30)):
            o=opts.nth(i)
            try:
                if await o.is_visible(): await o.click(timeout=3000); await page.wait_for_timeout(500); return "picked-first"
            except Exception: pass
        if n: await h.press("ArrowDown"); await h.press("Enter"); await page.wait_for_timeout(500); return "enter"
        await dismiss_menu(page,h); return None   # no suggestions: Enter here would submit the form
    except Exception: return None
async def choose_select(page,h,options_pref,label=""):
    opts=await h.evaluate("(s)=>[...s.options].map(o=>o.text.trim())")
    usable=mask_hear(opts,label)
    for pref in options_pref:
        # exact option first, then a leading / whole-word match, then a plain substring for longer preferences
        cand=[o for o in usable if o and o.lower()==pref.lower()] or [o for o in usable if o and _match(o,pref)] or [o for o in usable if o and len(pref)>=4 and pref.lower() in o.lower()]
        for o in cand[:1]:
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
ENV_TRUE=r"internal or external audit controls|audit controls|\bsoc ?2\b|\bsox\b|sarbanes|vendor negotiation|budget ownership|healthcare or benefits|healthcare|health ?tech|backend systems powering|consumer apps|start-?up|scale-?up|product-led|ambiguous|evolving|roadmap|enterprise|established processes|remote|distributed|hybrid|cross-functional|global|regulated|fintech|financ|b2b|saas|platform|\bai\b|\bml\b|cloud|high-growth|fast-moving|early-stage|growth-stage|public company|series [a-f]"
# option statements that are true for the applicant (Santa Clara, CA; hybrid in SF Bay Area fine; open to relocation elsewhere)
STACK_TRUE=r"c\+\+|\brust\b|tokio|\bgo\b|golang|c#|\.net|dotnet|asp\.net|python|scripting|\bbash\b|shell|powershell|solidity|smart contract|typescript|javascript|\bjs\b|node|react|\bjava\b|\bsql\b|postgres|mysql|redis|kafka|kubernetes|\bk8s\b|\baks\b|docker|terraform|\baws\b|amazon web services|\bgcp\b|google cloud|azure (functions|app services?|storage|devops|key vault|kubernetes|sql|cosmos|api management|service bus|event hubs?|blob|monitor)|lambda|\bs3\b|\bec2\b|microservices|\brest\b|grpc|graphql|ci/cd|github actions|jenkins|\bgit\b|linux|\bllms?\b|machine learning|pytorch|tensorflow|vector|\brag\b|openai|langchain|vllm|spark|databricks|airflow|unit test|integration test|end-to-end|\be2e\b|regression|performance test|load test|contract test|api test|automated test|hiring|recruit|mentor|coach|performance (review|management)|career (growth|development)|team building|managing managers|budget|roadmap|stakeholder|cross-functional|one-on-one|1:1|feedback|org(anizational)? design|onboarding|distributed systems|event-driven|observability|monitoring|security|devsecops"   # the applicant's stack and leadership practice
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
    for i,t in enumerate(texts):   # an exact option first ('English' over 'English only / No additional languages')
        if t and t.lower().strip()==pref.lower().strip(): return i
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
HEAR_Q=re.compile(r"hear about|learn about|find out about|how did you (first |initially )?(hear|learn|find)|\bsource\b|referred",re.I)
HEAR_BAD=re.compile(r"recruit|employee|referr|refer(ral|red)|event|fair|conference|meetup|friend|colleague|agency|linkedin|university|campus|blog|podcast|hosted",re.I)
LOC_Q=re.compile(r"location|city|where .{0,20}(based|live|located|reside)|residence",re.I)
def mask_hear(texts,label):
    """'How did you hear about us?': never pick an option that claims a referral, an event, a recruiter or LinkedIn.
    Location questions: never a 'Santa Clara' outside the US (Santa Clara, Villa Clara, Cuba)."""
    out=[]
    for t in texts:
        if t and HEAR_Q.search(label or "") and HEAR_BAD.search(t): t=""
        elif t and LOC_Q.search(label or "") and re.search(r"santa clara",t,re.I) and not re.search(r"california|\bca\b|united states|\busa?\b",t,re.I): t=""
        out.append(t)
    return out
PREF_ALIASES={"united states":["United States of America","USA","U.S.","US"],"united states of america":["United States","USA","US"],"united kingdom":["UK","Great Britain"]}   # fallback only: menus that abbreviate the answer
async def choose_react_select(page,control,options_pref,label):
    """react-select: type the preferred answer into the inner input, pick the visible matching option (or Enter), verify."""
    if options_pref==["__ASK__"]: return None
    inp=control.locator('input[role="combobox"], input.select__input, input').first
    has_inp=bool(await inp.count())
    if not has_inp:
        try:   # the control may itself be the typeahead input (Ashby's location autocomplete)
            if (await control.evaluate("el=>el.tagName"))=="INPUT": inp=control; has_inp=True
            else: inp=control   # button[aria-haspopup="listbox"]: keys go to the control itself
        except Exception: inp=control
    async def current():
        try:
            if (await control.evaluate("el=>el.tagName"))=="INPUT": return (await control.input_value()).strip()
            return (await control.inner_text()).strip()
        except Exception: return ""
    try:
        for pref in (options_pref[:4] if has_inp else []):   # type-to-filter needs a real inner input
            await inp.scroll_into_view_if_needed(timeout=3000); await open_menu(control,inp)
            await inp.press("Control+A"); await inp.press("Backspace"); await page.wait_for_timeout(200)
            await inp.type(pref[:30],delay=25); await page.wait_for_timeout(900)
            opts,texts=await visible_options(page)
            for _ in range(14):   # async search menus (e.g. the school list) can take a few seconds; "No options" may be stale from the previous search
                if texts and not all(re.search(r"^(loading|searching|no options|no results)",t or "",re.I) for t in texts): break
                await page.wait_for_timeout(500); opts,texts=await visible_options(page)
            texts=mask_hear(texts,label)
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
        LAST_OPTIONS[label[:160]]=[t for t in texts if t][:25]; texts=mask_hear(texts,label)
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
        # still unmatched: retry with abbreviation aliases (Stripe's country list says "US", not "United States"),
        # then drive menus the scan couldn't see whole: ARIA typeahead for button listboxes, scroll+rescan for virtualized ones.
        prefs2=options_pref+[a for p in options_pref for a in PREF_ALIASES.get((p or "").lower().strip(),[]) if a.lower() not in [x.lower() for x in options_pref]]
        async def try_visible(opts,texts):
            texts=mask_hear(texts,label)
            for pref in prefs2:
                i=best_index(texts,pref)
                if i is not None:
                    await opts.nth(i).click(timeout=3000); await page.wait_for_timeout(500)
                    cur=await current()
                    if cur and cur.lower()!="select...": return cur[:80]
            return None
        got=await try_visible(opts,texts)   # alias pass over the menu already open
        if got: return got
        if not has_inp:
            try:   # typeahead: a focused button listbox jumps to the typed prefix (a real input would filter instead, maybe to nothing)
                for ch in re.sub(r"[^a-z]","",prefs2[0].lower())[:6]: await page.keyboard.press(ch)
                await page.wait_for_timeout(400)
                got=await try_visible(*await visible_options(page))
                if got: return got
            except Exception: pass
        seen=set(LAST_OPTIONS.get(label[:160]) or []); stall=0
        for _ in range(30):   # virtualized/paginated menus render options only as the list scrolls
            moved=await page.evaluate('()=>{const vis=e=>e&&e.getClientRects().length;const scr=e=>e&&e.scrollHeight>e.clientHeight+4;const cands=[];for(const lb of [...document.querySelectorAll(\'[role="listbox"],[class*="select__menu-list"]\')].filter(vis).reverse()){cands.push(lb);let p=lb.parentElement;for(let i=0;i<3&&p;i++){cands.push(p);p=p.parentElement}cands.push(...lb.querySelectorAll("*"))}const o=[...document.querySelectorAll(\'[role="option"],[class*="select__option"]\')].find(vis);if(o){let p=o.parentElement;while(p&&p!==document.body){cands.push(p);p=p.parentElement}}const el=cands.find(scr);if(!el)return false;const b=el.scrollTop;el.scrollTop+=el.clientHeight*0.8;el.dispatchEvent(new Event("scroll",{bubbles:true}));return el.scrollTop>b}')
            await page.wait_for_timeout(300)
            opts,texts=await visible_options(page)
            new=[t for t in texts if t and t not in seen]
            if new: seen.update(new); LAST_OPTIONS[label[:160]]=(LAST_OPTIONS.get(label[:160]) or [])+new
            got=await try_visible(opts,texts)
            if got: return got
            stall=0 if (moved or new) else stall+1
            if stall>=3: break
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
    # the answers on the form go with the request, so they can be reviewed before the code is handed over
    json.dump({"tag":tag,"email":P["email"],"url":report.get("url"),"ts":time.time(),"filled":report.get("filled"),"chosen":report.get("chosen")},open(req,"w"),indent=1)
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
GENERIC_TOKENS={"the","ai","san","new","open","one","first","next","big","blue","red","green","smart","data","cloud","tech","labs","lab","inc","co","company","team","global","digital","alpha","beta","meta","x","a","an","of","and",
 "wf","wf2","wd","dgh","dice2","gh","li","yc","batch"}   # batch/stream prefixes in tags are never company names
def company_keys(tag,company=None):
    toks=[t for t in (tag or "").split("_") if t]
    ks=set()
    if company: ks.add(re.sub(r"[^a-z0-9]","",str(company).lower()))
    if toks and len(toks[0])>=2 and toks[0] not in GENERIC_TOKENS and not toks[0].isdigit() and toks[0]!="dice": ks.add(toks[0])   # short board slugs count too (x9, okta, step)
    if len(toks)>1: ks.add(toks[0]+toks[1])
    ks={BOARD_ALIAS.get(k,k) for k in ks}
    return {k for k in ks if len(k)>=2 and k not in GENERIC_TOKENS}
# companies the applicant never wants to apply to (checked against tag, company, title and URL of every job)
NEVER_APPLY=re.compile(r"bitcot|employvision|fanatics|\bfaire\b|cohesity|ava[ _-]?labs|avalabs|\bankr\b|bloomberg|early[ _-]?warning|earlywarning|zelle|altruist|geico|alpaca|morgan[ _-]?stanley|ms\.wd5\.myworkdayjobs|(^|[^a-z0-9])x9_|tapestry|epic[ _-]?semi\w*|global[ _-]?settlement[ _-]?systems?|globalsettlement|tata[ _-]?consult\w*|(^|[^a-z])tcs([^a-z]|$)|cloudflare|anthropic|roblox|waymo|snorkel|real[ _-]?chemistry|earnin|nvidia|openai|open[ _-]?ai|(^|[^a-z])xai([^a-z]|$)|x\.ai|coinbase|semgrep|\bclera\b|airwallex|nubank|openrouter|\bhims\b|hims?[ _-]?(&|and)[ _-]?hers|true[ _-]?talent|perplexity|hippocratic|(^|[^a-z])stripe([^a-z]|$)|paypal|pay[ _-]?pal",re.I)
# Applicant (2026-10-01): no New Jersey hybrid / on-site roles, and no investment-bank roles that need on-site presence in New
# York (hybrid included). Fully remote roles are fine. The primary location is the Workday URL's location segment or the first
# listed location.
NJ_LOC=re.compile(r"\bNJ\b|new[ -]jersey|jersey[ -]city|hoboken|newark|iselin|princeton|parsippany|berkeley[ -]heights|basking[ -]ridge|weehawken|secaucus|morristown|whippany|piscataway|holmdel|bridgewater",re.I)
NY_LOC=re.compile(r"new[ -]york|\bnyc\b|\bny\b|manhattan|brooklyn|white plains|rye brook",re.I)
IB_CO=re.compile(r"\bciti(group|bank)?\b|j\.?\s?p\.?\s?morgan|jpmc|\bchase\b|goldman|bank of america|\bbofa\b|merrill|barclays|deutsche|\bubs\b|credit suisse|jefferies|evercore|lazard|moelis|\bpjt\b|houlihan|\brbc\b|\bbmo\b|td securities|wells[ _-]?fargo|\bbny\b|bank of new york|nomura|mizuho|\bhsbc\b|soci[eé]t[eé] g[eé]n[eé]rale|\bbnp\b|macquarie|piper sandler|raymond james|stifel|cowen|guggenheim|perella|centerview|state street|northern trust",re.I)
def location_block(company, url="", loc="", where=""):
    m=re.search(r"/job/([^/]+)/",url or "")
    txt=(loc or where or "").strip()
    first=re.split(r"\s*(?:/|;|\||\bor\b)\s*",txt)[0] if txt else ""
    if first==txt and txt.count(",")>=3: first=txt.split(",")[0]   # a long comma list of places: the first one
    primary=(m.group(1).replace("-"," ") if m else "")+" "+first
    alltext=" ".join([url or "",loc or "",where or ""])
    if re.search(r"\bremote\b",primary+" "+alltext,re.I) and not re.search(r"hybrid|on-?site|in[- ]office",alltext,re.I): return None   # fully remote, even when an NJ/NY city is listed
    if NJ_LOC.search(primary): return "New Jersey hybrid/on-site role (applicant: never)"
    if IB_CO.search(company or "") and (NY_LOC.search(primary) or NJ_LOC.search(primary) or (not primary.strip() and (where or "").strip().lower()=="nyc")): return "investment bank with on-site presence in New York (applicant: never)"
    return None
# one company behind two Greenhouse board names (found from the security-code e-mail's company name)
BOARD_ALIAS={"cssmerge":"atoms","cssmergestaff":"atoms","addepar1":"addepar","hubspotjobs":"hubspot","truebill":"rocketmoney","digitalocean98":"digitalocean"}
_META_TITLES={}
def _norm_role(t):
    t=re.sub(r"\(.*?\)|\[.*?\]","",(t or "").lower())
    t=re.sub(r"\s[-\u2013\u2014|:]\s*(remote|hybrid|on-?site|us|usa|united states|new york|nyc|san francisco|sf|bay area)\b.*$","",t)
    t=re.sub(r"^(coe|remote|urgent|hiring|immediate)\s*[-:|]\s*","",t)
    return re.sub(r"[^a-z0-9]+"," ",t).strip()
def _title_of(tag):
    """Job title for a report tag, from the queue files (reports do not always store it)."""
    if not _META_TITLES:
        import glob as _g
        for f in _g.glob(os.path.join(HERE_REPO,"job-search","batches","*.json"))+_g.glob(os.path.join(os.path.dirname(JOBS_DIR),"**","*.json"),recursive=True):
            if "/out/" in f: continue
            try: d=json.load(open(f))
            except Exception: continue
            if isinstance(d,list):
                for j in d:
                    if isinstance(j,dict) and j.get("tag") and j.get("title"): _META_TITLES.setdefault(j["tag"],j["title"])
        _META_TITLES.setdefault("__loaded__","1")
    return _META_TITLES.get(tag)
def applied_elsewhere(tag,company=None,days=45,title=None):
    """Return the tag of an earlier submitted application at the same company once the per-company cap is reached
    (MAX_PER_COMPANY, default 3: the applicant allows 2-3 different roles per company when they match the resume; the
    same position is never submitted twice, which the per-tag report check in the batch runner enforces), else None."""
    import glob as _glob
    cap=int(os.environ.get("MAX_PER_COMPANY","1"))   # applicant (2026-10-04): one application per company, full stop
    ks=company_keys(tag,company)
    if not ks: return None
    cutoff=time.time()-days*86400
    # Gmail is the ground truth: reports vanish with the container, confirmations don't. Any company with
    # application evidence in the mailbox ledger (applied_gmail.json) inside the window is blocked outright.
    g=_gmail_ledger()
    SUFG={"usa","us","inc","llc","hq","co","corp","io","ai","app","labs","lab","global","group","tech","technologies"}
    for a in ks:
        for b,dt in g.items():
            if dt<cutoff: continue
            if a==b or (min(len(a),len(b))>=5 and ((a.startswith(b) and a[len(b):] in SUFG) or (b.startswith(a) and b[len(a):] in SUFG))):
                return f"{b} (gmail ledger, applied {time.strftime('%Y-%m-%d',time.localtime(dt))})"
    SUF={"usa","us","inc","llc","hq","co","corp","io","ai","app","labs","lab","global","group","tech","technologies","careers","jobs"}
    hits=[]
    for f in _glob.glob(f"{OUT}/*_report.json"):
        if os.path.basename(f)==f"{tag}_report.json" or os.path.getmtime(f)<cutoff: continue
        try: r=json.load(open(f))
        except Exception: continue
        if not r.get("submitted") or "ALREADY APPLIED" in (r.get("result") or "") or (r.get("tag") or "").endswith("_r2"): continue   # correction resubmits do not count
        ks2=company_keys(r.get("tag"),r.get("company"))
        if (ks & ks2) or any((a.startswith(b) and a[len(b):] in SUF) or (b.startswith(a) and b[len(a):] in SUF) for a in ks for b in ks2 if min(len(a),len(b))>=5):
            hits.append(r.get("tag"))
            t2=r.get("title") or _title_of(r.get("tag"))
            if title and t2 and _norm_role(t2)==_norm_role(title): return f"{r.get('tag')} (same role)"   # never the same role twice, reposts included
    # applications the applicant sent himself (not in these reports) count toward the cap too
    for k,n in APPLIED_BY_APPLICANT.items():
        if k in ks: hits += [f"{k} (applied by the applicant)"]*n
    return hits[0] if len(hits)>=cap else None
APPLIED_BY_APPLICANT={"welbehealth":2}
_GMAIL_LEDGER_CACHE=None
def _gmail_ledger():
    """Normalized company key -> latest application timestamp, from the mailbox audit (applied_gmail.json,
    rebuilt from Gmail confirmations/security-code emails). Empty dict when the file is absent."""
    global _GMAIL_LEDGER_CACHE
    if _GMAIL_LEDGER_CACHE is not None: return _GMAIL_LEDGER_CACHE
    out={}
    try:
        _p=os.path.join(os.path.dirname(os.path.dirname(OUT)),"applied_gmail.json")
        if not os.path.exists(_p):   # Mac runs: the ledger ships with the repo
            _p=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","applied_gmail.json")
        d=json.load(open(_p))
        for k,v in (d.get("companies") or {}).items():
            ts=[time.mktime(time.strptime(x,"%Y-%m-%d")) for x in (v.get("dates") or []) if re.match(r"\d{4}-\d{2}-\d{2}$",x)]
            if ts: out[re.sub(r"[^a-z0-9]","",k.lower())]=max(ts)
    except Exception: pass
    _GMAIL_LEDGER_CACHE=out
    return out
def prior_company_apps(tag,company=None,days=183):
    """Titles of earlier submitted applications at the same company (other tags) within `days`: answers "have you applied to us before?" truthfully."""
    import glob as _glob
    ks=company_keys(tag,company)
    if not ks: return []
    cutoff=time.time()-days*86400; out=[]
    SUF={"usa","us","inc","llc","hq","co","corp","io","ai","app","labs","lab","global","group","tech","technologies","careers","jobs"}
    base=re.sub(r"_r\d$","",tag or "")
    for f in _glob.glob(f"{OUT}/*_report.json"):
        if os.path.getmtime(f)<cutoff: continue
        try: r=json.load(open(f))
        except Exception: continue
        t=r.get("tag") or ""
        if t==tag or not r.get("submitted") or "ALREADY APPLIED" in (r.get("result") or ""): continue
        ks2=company_keys(t,r.get("company"))
        if (ks & ks2) or any((a.startswith(b) and a[len(b):] in SUF) or (b.startswith(a) and b[len(a):] in SUF) for a in ks for b in ks2 if min(len(a),len(b))>=5):
            tt=r.get("title") or _title_of(t) or ""
            if not tt or "_" in tt: tt=re.sub(r"_r\d$","",t).replace("_"," ").strip().title()
            out.append(tt)
    for k,n in APPLIED_BY_APPLICANT.items():
        if k in ks: out.append("another role (applied directly)")
    return sorted(set(x for x in out if x))   # applicant (2026-09-30): applied to the WelbeHealth Director role himself; with our Engineering Manager application, stop at WelbeHealth
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
            try:
                _prev=json.load(open(f"{OUT}/{job['tag']}_report.json"))
            except Exception: _prev={}
            if _prev.get("submitted") and "ALREADY" not in (_prev.get("result") or ""):
                print(json.dumps({"tag":job["tag"],"ats":job["ats"],"url":job["url"],"submitted":True,"result":"ALREADY SUBMITTED earlier (skipped)"}),flush=True); continue
            if not ASSIST and (_prev.get("spam_blocked") or re.search(r"spam check|pause browser extensions|different (network )?connection instead",_prev.get("result") or "")):
                if not _prev.get("spam_blocked"):
                    _prev["spam_blocked"]=True; _prev["result"]="NOT SUBMITTED: blocked by the site's spam check - apply by hand"; json.dump(_prev,open(f"{OUT}/{job['tag']}_report.json","w"),indent=1)
                print(json.dumps({"tag":job["tag"],"ats":job["ats"],"url":job["url"],"submitted":False,"result":"SKIPPED: the site's spam check blocked this earlier - apply by hand"}),flush=True); continue
            if NEVER_APPLY.search(" ".join(str(job.get(k) or "") for k in ("tag","company","title","url"))):
                r={"ats":job["ats"],"url":job["url"],"tag":job["tag"],"submitted":False,"result":"SKIPPED: company on the applicant's do-not-apply list","unanswered":[],"errors":[]}
                print(json.dumps(r),flush=True); continue
            _lb=location_block(job.get("company") or job.get("tag","").split("_")[0],job.get("url",""),job.get("loc",""),job.get("where",""))
            if _lb:
                r={"ats":job["ats"],"url":job["url"],"tag":job["tag"],"submitted":False,"result":"SKIPPED: "+_lb,"unanswered":[],"errors":[]}
                print(json.dumps(r),flush=True); continue
            prior=None if job.get("resubmit") else applied_elsewhere(job["tag"],job.get("company"),title=job.get("title"))   # one application per company across every stream and site (a correction resubmit is exempt)
            if prior:
                r={"ats":job["ats"],"url":job["url"],"tag":job["tag"],"submitted":False,"result":f"NOT SUBMITTED: ALREADY APPLIED at this company today (cap reached; e.g. {prior})","unanswered":[],"errors":[]}
                json.dump(r,open(f"{OUT}/{job['tag']}_report.json","w"),indent=1)
                summary.append(r); print(json.dumps(r),flush=True); continue
            ctx=await b.new_context(ignore_https_errors=True,user_agent=UA,viewport={"width":1280,"height":(860 if ASSIST else 2000)},locale="en-US",timezone_id="America/Los_Angeles")
            ctx.set_default_timeout(8000)
            r=await run_one(ctx,job["ats"],job["url"],job["tag"],job.get("answers",{}),job.get("company"),job.get("title"))
            if not r.get("submitted") and any(("uploadFile" in (e or "")) or ("Resume/CV is required" in (e or "")) for e in (r.get("errors") or [])):
                # Greenhouse's uploader sometimes fails to initialise: load the whole form again once
                print(f"RETRY {job['tag']}: resume uploader error, reloading the form",flush=True)
                await ctx.close(); await asyncio.sleep(20)
                ctx=await b.new_context(ignore_https_errors=True,user_agent=UA,viewport={"width":1280,"height":(860 if ASSIST else 2000)},locale="en-US",timezone_id="America/Los_Angeles")
                ctx.set_default_timeout(8000)
                r=await run_one(ctx,job["ats"],job["url"],job["tag"],job.get("answers",{}),job.get("company"),job.get("title"))
            summary.append({k:r.get(k) for k in ("tag","ats","url","submitted","result","unanswered","captcha_present","errors","code_required","code_source")})
            print(json.dumps(summary[-1]),flush=True)
            await ctx.close()
            if PACE and not ASSIST and job is not jobs[-1]:
                import random; gap=random.uniform(*PACE)
                if not r.get("submitted") and re.search(r"location restricted|in-office NYC|job closed|managed outside|ALREADY APPLIED",r.get("result") or ""): gap=min(gap,20)   # nothing was submitted: no need for the full human-paced gap
                print(f"PACE waiting {int(gap)}s before the next application",flush=True); await asyncio.sleep(gap)
        json.dump(summary,open(f"{OUT}/batch_summary_{int(time.time())}.json","w"),indent=1)
        await b.close()
async def run_one(ctx,ats,url,tag,extra,company=None,jtitle=None):
    global CUR_ATS
    CUR_ATS=ats
    if ats=="lever":
        m=re.match(r"(https://jobs\.(?:eu\.)?lever\.co/[^/?#]+/[0-9a-f-]{36})/?(?:\?.*)?$",url)
        if m: url=m.group(1)+"/apply"   # the posting page has no form; the application lives at /apply
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
                    try: ta_label=re.sub(r"\s+"," ",(await label_of(ta)) or (await ta.get_attribute("placeholder")) or "")
                    except Exception: ta_label=""
                    if ta_label and not re.search(r"about you|note|message|cover|introduc|anything else|additional|why (are you|do you|you)|interest",ta_label,re.I) and re.search(r"\?|describe|explain|tell us|walk (me|us) through|what |how |which ",ta_label,re.I):
                        ta=page.locator('textarea.__no_note_box__')   # the first box is an employer question, not the note: leave it to the question rules
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
                for attempt in range(6):   # transient proxy/network errors ("upstream request failed", 502/503): reload with a growing pause
                    await page.goto(url,wait_until="domcontentloaded",timeout=60000); await page.wait_for_timeout(3500)
                    if not re.search(r"^\s*upstream request failed|Error\s+50[234]\b|50[234]\s+(Bad Gateway|Service|Gateway)|lost in the weeds|ERR_|This site can.t be reached",await body_text(page),re.I): break
                    await page.wait_for_timeout([8000,15000,25000,40000,60000,60000][attempt])
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
            # "have you applied to us before / for another role?": answered from our own submitted applications to this company
            global JOB_CHOICE_RULES, JOB_TEXT_RULES
            try: _prior=prior_company_apps(tag,company)
            except Exception: _prior=[]
            _PAT=r"(previously|ever|already|recently) applied|applied (for|to) (another|other|a different|any other|an?other|any) (role|position|job|opening)|applied (to|with|at) .{0,40}(before|previously|in the (past|last)|within the (past|last))|applied .{0,30}within the (past|last) \\d+|participated in (a|any) (hiring|recruiting|interview) process|interviewed (with|at) .{0,40}(before|previously|in the (past|last))"
            JOB_CHOICE_RULES=[(_PAT,["Yes","yes"] if _prior else ["No","no","No, I have not","I have not applied"])]
            try:
                _top=(await page.evaluate("()=>document.body.innerText.slice(0,1500)"))
                _bay=bool(re.search(r"San Francisco|Bay Area|Palo Alto|Menlo Park|Mountain View|Sunnyvale|San Jose|Santa Clara|Redwood City|San Mateo|Oakland|Berkeley|Cupertino|Foster City|Burlingame|Fremont|Milpitas|Emeryville|Los Gatos|Campbell|Pleasanton|San Ramon|Walnut Creek|Hayward|Newark, CA",_top))
            except Exception: _bay=False
            JOB_CHOICE_RULES.append((r"if you are not (a )?local( candidate)?,? (do|would) you (require|need) relocation|not (a )?local candidate.{0,40}relocation", ["No","no","N/A"] if _bay else ["Yes","yes"]))
            JOB_TEXT_RULES=[(r"^if (yes|so).{0,80}\bappl(ied|y|ication)|(which|what) (role|position)s? did you (previously )?apply|when did you (previously )?apply", ("Yes: "+"; ".join(_prior[:3])+" (2026)") if _prior else "N/A")]
            if _prior: report["prior_company_apps"]=_prior[:5]
            global JOB_WHY
            try:
                _ptitle=await page.title(); _m2=re.search(r"\bat ([^|\-–]+?)\s*$",_ptitle or "")
                _co=(_m2.group(1).strip() if _m2 else None) or (re.sub(r"[-_]+"," ",company).title() if company else None)
                _body=await page.evaluate("()=>document.body.innerText.slice(0,6000)")
                JOB_WHY=why_for(_co, jtitle or re.sub(r"\s*[|@\-–].*$","",_ptitle or ""), _body)
            except Exception: JOB_WHY=""
            # an "application password" printed in the posting (a did-you-read-it check): answer it from the posting itself
            try:
                _pt=await page.evaluate("()=>document.body.innerText")
                _m=re.search(r"application (password|keyword|code ?word|pass ?phrase)\s*(?:is|:|-|=)?\s*[\"\u201c'\u2018]?([A-Za-z0-9][\w-]{1,30})",_pt,re.I)
                if _m and not any(re.search(r"password|keyword|code ?word|pass ?phrase",k,re.I) for k in extra):
                    extra=dict(extra); extra["application "+_m.group(1).lower()]=_m.group(2); report["posting_password"]=_m.group(2)
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
                try: await files.nth(ri).set_input_files(resume_for(jtitle),timeout=15000); report["filled"]["resume"]="uploaded"; report["resume_file"]=os.path.basename(resume_for(jtitle))
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
                    if await is_edu_date(h):
                        if not (await h.input_value()).strip():
                            ev=edu_value(lab,h)
                            if ev: await fill_text(page,h,ev); report["filled"]["Education "+lab[:50]]=ev
                        continue
                    ph=(await h.get_attribute("placeholder") or "")
                    if lab.strip().lower() in ("select...","select") or re.search(r"select2",(await h.get_attribute("class")) or ""): continue
                    if await h.evaluate("(el)=>el.getAttribute('aria-autocomplete')==='list'||el.getAttribute('role')==='combobox'||/select__input|react-select|requiredInput/i.test(el.className+' '+el.id)||!!el.closest('[class*=select__control],[class*=Select__control]')||!!(el.parentElement&&el.parentElement.querySelector('[class*=select__control],[class*=Select__control]'))"): continue   # dropdowns are handled below
                    if re.search(r"^(current |your )?location( \(city\))?$|^city$|^where are you (based|located)",lab,re.I) or (ats=="lever" and name=="location") or (re.search(r"start typing",ph,re.I) and re.search(r"location|city",lab,re.I)):
                        if not (await h.input_value()).strip():
                            got=await autocomplete_fill(page,h,"Santa Clara, California",r"santa clara.{0,40}(california|\bca\b|united states|usa)",strict=True,retry_texts=("Santa Clara, CA","Santa Clara"))
                            report["filled"][lab[:60] or name]=f"autocomplete:{got}"
                        continue
                    if re.search(r"ai policy|use of ai|ai assistance|ai tools? (in|during)|without (the use of )?ai",lab,re.I):
                        _aiv=next((v for k,v in extra.items() if k.lower() in (name+" "+lab).lower()),None) or pick(lab,TEXT_RULES)
                        if not _aiv or _aiv==["__ASK__"]:
                            report["unanswered"].append({"type":"text","label":lab[:160],"name":name,"note":"AI-use question left for user"}); continue
                        # the applicant's reviewed AI-disclosure rules (2026-10-02) answer this: fall through to the normal fill
                    key=lab or name
                    val=None
                    for k,v in extra.items():
                        if k.lower() in (name+" "+lab).lower(): val=v; break
                    if val is None:
                        mw=re.search(r"why (are )?you(\'re| are)? ?(are )?(interested|excited)( in| about)? (working at|working for|joining|to join|to work at|to work for) ([A-Z][\w&.'\- ]{1,40}?)[\s.?,]*$|why (do )?you want to (work at|join) ([A-Z][\w&.'\- ]{1,40}?)[\s.?,]*$",re.sub(r"^in \d-\d sentences,? (describe |explain )?","",lab.strip(),flags=re.I),re.I)
                        if mw:
                            co=(mw.group(7) or mw.group(10) or "").strip()   # group 10 = company in "why do you want to work at X" (group 11 does not exist)
                            val=(f"{co}'s mission and the scope of this role sit where my experience is strongest: building and leading platforms where performance, correctness and trust matter. "
                                 f"As CTO and co-founder of Hyperion AI I built an agentic AI platform end to end, and as Chief Architect at Yahoo Finance I led 75+ engineers on a platform serving about 40M daily users. "
                                 f"I want to bring that mix of hands-on architecture and engineering leadership to {co}'s products and team.")
                    if val is None: val=pick(key,TEXT_RULES)
                    if val=="Company careers page" and "wellfound" in (ats or "").lower(): val="Wellfound"   # applying through Wellfound: say so
                    if re.search(r"cover letter",lab,re.I) and cl_text: val=cl_text
                    if ats=="lever" and re.search(r"^location$",name): val=P["location"]
                    if val is None and (await h.get_attribute("placeholder") or ""): val=pick(await h.get_attribute("placeholder"),TEXT_RULES)
                    if val is None and not (await h.input_value()).strip():
                        # applicant: fill every technical question, optional ones included (never a link field or an "if yes" follow-up that is optional)
                        _req=await is_required(h)
                        if _req or not re.search(r"\b(link|url|website|github|portfolio|profile|handle|twitter|linkedin)\b|^\s*if (yes|so|applicable|other)\b|anything else|additional (info|comments?|notes?|details)|cover letter|message (to|for)|note (to|for)",key,re.I):
                            val=tech_answer(key)
                            if val: report.setdefault("tech_fallback" if _req else "tech_fallback_optional",[]).append(key[:120])
                    if val is None and await is_required(h) and not (await h.input_value()).strip():
                        _k=key.lower()
                        _hc=re.search(r"type\s+[\"']?([A-Za-z0-9]{2,20})[\"']?\s*(?:below|here|in the box|to (?:confirm|verify|proceed)|$)",key,re.I)
                        if _hc and re.search(r"real person|not a robot|prove you|human|verify you are|type the word",_k):
                            val=_hc.group(1)                       # anti-bot check: type the exact required word (e.g. "Real")
                        elif not PERSONAL_Q.search(_k) and re.search(r"\bwhy\b|describe|tell us|what (makes|draws|interests|excites|motivat)|how (do|would|have) you|motivat|interest you|passion|about (this|the|our) (role|company|team|mission|product)|most (proud|excited)|anything (else|you)",_k):
                            val=("I'm a hands-on engineering leader - CTO and co-founder of Hyperion AI, and formerly Chief Architect at Yahoo Finance leading 75+ engineers on a platform serving about 40M daily users - who still writes critical-path code in Python, Rust, Go and C++. I build AI, platform and data-intensive systems where performance, correctness and trust matter, and I would bring that mix of architecture and engineering leadership to this role.")
                            report.setdefault("generic_fallback",[]).append(key[:100])
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
                        got=await choose_select(page,h,pref,lab); report["chosen"][lab[:60]]=got
                        if not got and await is_required(h): report["unanswered"].append({"type":"select","label":lab[:160],"options":(await h.evaluate("(s)=>[...s.options].map(o=>o.text.trim())"))[:12]})
                    elif await is_required(h): report["unanswered"].append({"type":"select","label":lab[:160],"options":(await h.evaluate("(s)=>[...s.options].map(o=>o.text.trim())"))[:12]})
                except Exception: pass
            _ctried=set()
            for _cpass in range(2):   # a second pass catches selects revealed by earlier answers (Upstart: Veteran Status after Hispanic/Latino)
                # react-select style comboboxes (Greenhouse/Ashby)
                combos=page.locator('[class*="select__control"], [role="combobox"]:not(input), div[class*="Select"] [class*="control"], button[aria-haspopup="listbox"], input[id^="react-select-"][id$="-input"]:not([class*="select__input"]), input.ashby-application-form-input-autocomplete')
                n=await combos.count()
                for i in range(n):
                    h=combos.nth(i)
                    try:
                        if not await h.is_visible(): continue
                        if await h.evaluate("(el)=>el.tagName==='INPUT'"): h=h.locator('xpath=ancestor::div[3]')   # unstyled react-select (Wellfound): use the control container
                        lab=await label_of(h)
                        if not lab: continue
                        if _cpass and lab in _ctried: continue   # second pass: only selects that appeared after the first
                        _ctried.add(lab)
                        if await is_edu_date(h):
                            cur=(await h.inner_text()).strip()
                            if not cur or re.search(r"^select",cur,re.I):
                                ev=edu_value(lab,h)
                                got=await choose_react_select(page,h,[ev,ev[:3]],lab) if ev else None
                                report["chosen"]["Education "+lab[:50]]=got
                                if not got and await is_required(h): report["unanswered"].append({"type":"combo","label":"Education "+lab[:140],"keep":True})
                            continue
                        cur=(await h.inner_text()).strip()
                        cur=re.sub(r"\s+"," ",re.sub(r"option\s*[^.]{0,120}?,\s*selected\.?|[^.|]{0,40}is focused\s*,?\s*type to refine list,?\s*press down to open the menu,?|press down to open the menu,?","",cur,flags=re.I)).strip(" ,|")   # react-select's screen-reader text is not an answer
                        if cur and cur not in ("-","–","—") and not re.search(r"^select|^choose|^please (select|choose)|--",cur,re.I): continue
                        pref=None
                        for k,v in extra.items():
                            if k.lower() in lab.lower(): pref=[v]; break
                        pref=pref or pick(lab,CHOICE_RULES)
                        if pref==["__ASK__"]:
                            report["unanswered"].append({"type":"combo","label":lab[:160],"note":"AI-use question left for user"}); continue
                        if pref and company and re.search(r"hear|learn about|find out|source",lab,re.I):
                            cn=re.sub(r"(usa|inc|llc|corp)$","",company,flags=re.I).strip()   # the company's own careers page first, if listed
                            pref=[f"{cn} careers",f"{cn} career site",f"{cn} careers site",f"{cn} website",f"{cn}.com",f"{cn} careers page",f"{cn} job board"]+pref   # never the bare name: it matches "<Company> Recruiter" / "<Company> Employee"
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
                    if "wellfound" in (CUR_ATS or "").lower() and re.search(r"hear about|learn about|find out about|how did you (hear|find|learn)|source",qlab,re.I): cands.append(["Wellfound","AngelList","Wellfound (AngelList)"])   # applying through Wellfound: say so
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
                    if not done and len(opts)>=2 and all(re.search(r",\s*[A-Z]{2}\b|,\s*[A-Z][a-z]+|remote|hybrid",(l or v),re.I) for v,l in opts):   # an office-location list with no question text: choose the Bay Area office
                        for pref in (r"santa clara",r"san jose|sunnyvale|mountain view|palo alto|menlo park|cupertino|redwood city|san mateo",r"san francisco|bay area|south san francisco|oakland",r"remote.{0,15}(us|united states)|united states.{0,10}remote",r"remote"):
                            for x,(v,l) in zip(hs,opts):
                                if not done and re.search(pref,l or v,re.I):
                                    try: await x.check(timeout=3000)
                                    except Exception:
                                        try: await x.evaluate("(el)=>{const l=el.id&&document.querySelector('label[for=\"'+CSS.escape(el.id)+'\"]'); if(l) l.click(); else {el.click();} if(!el.checked){el.checked=true; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true}));}}")
                                        except Exception: continue
                                    done=l or v
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
            done_groups=set(); ov_groups=set()   # ov_groups: groups fully answered from a per-item "answers" override below
            for h,lab,gk,q in boxes:
                try:
                    if gk in ov_groups: continue   # a later member of an override-answered group: never re-touch it (e.g. via the agree/privacy regex)
                    members=[b for b in boxes if b[2]==gk]
                    if re.search(r"personally (completed|filled|prepared|written|wrote) (out )?(this|the|my) (application|form)|completed (this|the) application (myself|personally|on my own)|(filled|written) (out )?(this|the) application (myself|personally)|(completed|submitted) by (me|the candidate) (personally|alone)",lab,re.I): report["unanswered"].append({"type":"checkbox","label":lab[:160],"note":"personal certification left for the applicant","keep":True}); continue
                    if re.search(r"non-?compete|non-?solicit|financial interest|conflict of interest|relatives?\b|related to|family member|government official|convicted|felony|i am (currently )?subject to|i (currently )?hold|i have (a|an) (current|existing|ongoing)|i (was|have been) (previously )?(employed|terminated)|debarred|sanction|export",lab,re.I):   # a disclosure statement ("I am subject to a non-compete", "I hold a financial interest"): never tick it
                        report["chosen"][lab[:60]]="left unticked (disclosure)"; continue
                    if re.search(r"agree|acknowledge|consent|certify|confirm|\battest\b|\bauthorize\b|privacy|terms|policy|accurate|true|currently work|current (role|position|job)|i still work|to present|^accept\*?$|i accept"
                                 r"|tools assist our recruit|do not replace human judgment|(use of |uses? |may use )ai (tools )?(in|during|for|to assist) (the |our |its )?(hiring|recruit|application|screening)|ai (tools|technolog(y|ies)) (may be|are|is) used",lab,re.I):   # employer's AI-in-hiring process acknowledgment (Lever): accepted, like its dropdown form
                        await tick(h); report["chosen"][lab[:60]]="checked"; continue
                    if len(members)>1:
                        # a pick-list rendered as checkboxes (e.g. "How did you hear about us?"): tick exactly one option
                        if gk in done_groups: continue
                        done_groups.add(gk)
                        if not q and any(re.search(r"he/him|she/her|they/them",b[1],re.I) for b in members): q="Preferred pronouns"   # pronoun pick-list without a captured heading
                        # a per-item "answers" override naming this group (by its question, or its option texts when no heading was captured): tick exactly the options it lists
                        ov=None
                        for k,v in extra.items():
                            if isinstance(v,str): v=[v]   # a single answer is a one-option list
                            if isinstance(v,list) and v and (k.lower() in (q+" "+lab).lower() or k.lower() in " ".join(b[1] for b in members)[:200].lower()): ov=v; break
                        if ov:
                            ov_groups.add(gk); mem=[b[1] for b in members]; ticked=[]
                            for pv in ov:
                                bi=best_index(mem,str(pv))
                                if bi is None: bi=next((j for j,t in enumerate(mem) if t and (str(pv).lower() in t.lower() or t.strip().lower() in str(pv).lower())),None)
                                if bi is None: bi=next((b for a in PREF_ALIASES.get(str(pv).lower().strip(),[]) for b in [best_index(mem,a)] if b is not None),None)   # "United States" ticks a box labeled "US"
                                if bi is not None and mem[bi][:40] not in ticked:
                                    try: await tick(members[bi][0]); ticked.append(mem[bi][:40])
                                    except Exception: pass
                            report["chosen"][(q or lab)[:60]]=", ".join(ticked)
                            if not ticked: report["unanswered"].append({"type":"checkbox","label":(q or lab)[:160],"note":"override matched no option","options":mem[:8]})
                            continue
                        is_src=bool(re.search(r"hear about|learn about|find out about|source|referred|how did you find",q+" "+lab,re.I))
                        want=pick(q or lab,CHOICE_RULES) or (["Company Website","Careers page","Job Board","Other","Greenhouse"] if is_src else None)
                        if not want or want==["__ASK__"]: continue   # no rule for this question: leave it for the applicant, never guess
                        if "wellfound" in report["ats"].lower() and re.search(r"hear|learn about|find out|source",q or lab,re.I): want=["Wellfound","AngelList","Wellfound (AngelList)","Other","Job board"]+want   # applying through Wellfound: say so, else Other
                        if re.search(r"hear|learn about|find out|source",q or lab,re.I): members=[b for b in members if not HEAR_BAD.search(b[1])] or members   # never claim LinkedIn, a referral, an event or a recruiter as the source
                        if re.search(r"select all that apply|check all that apply|environments|best describes?|which (of the following )?(technolog|tools|languages|frameworks|services|platforms|types of|kinds of|practices|people-leadership|leadership)",q,re.I) and not re.search(r"hear|learn|source|ethnic|race|gender|disab|veteran|pronoun|sanction|citizenship|countr",q,re.I):
                            # "which environments / technologies / practices (select all that apply)": tick every option true for the applicant
                            ticked=[]
                            for b in members:
                                if (re.search(ENV_TRUE,b[1],re.I) or re.search(STACK_TRUE,b[1],re.I)) and not re.search(r"none of the above|not applicable|n/a|prefer not|^other\b",b[1],re.I):
                                    try: await tick(b[0]); ticked.append(b[1][:40])
                                    except Exception: pass
                            if ticked: report["chosen"][(q or lab)[:60]]=", ".join(ticked); continue
                        choice=None
                        for pv in want:
                            bi=best_index([b[1] for b in members],pv)
                            if bi is not None: choice=members[bi]; break
                        if not choice and is_src:
                            choice=next((b for b in members if re.search(r"other",b[1],re.I)),members[0])
                        if choice: await tick(choice[0]); report["chosen"][(q or lab)[:60]]=choice[1][:60]
                    elif await is_required(h):
                        # a per-item "answers" override naming this lone box ticks it; otherwise never tick it blind
                        if any(k.lower() in lab.lower() and str(v).lower() in ("check","checked","yes","true") for k,v in extra.items() if isinstance(v,(str,bool))):
                            await tick(h); report["chosen"][lab[:60]]="checked (override)"
                        else: report["unanswered"].append({"type":"checkbox","label":lab[:160]})
                except Exception: pass
            answered={k.lower()[:40] for k,v in report["chosen"].items() if v} | {k.lower()[:40] for k in report["filled"].keys()}
            seen=set(); uu=[]
            for u in report["unanswered"]:
                if u["label"] in seen: continue
                if u.get("keep"): seen.add(u["label"]); uu.append(u); continue   # e.g. education dates: same label as the filled employment dates
                if u["label"].lower()[:40] in answered: continue
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
            if ASSIST:
                # the applicant submits: fill everything, bring the window forward, wait for the site's confirmation
                who=f"{company or ''} - {jtitle or tag}".strip(" -")
                todo="; ".join((u.get("label") or "")[:70] for u in report["unanswered"])
                print(f"ASSIST {tag}: form filled for {who}. Review it in the browser window"+(f" and answer: {todo}" if todo else "")+f", then click Submit yourself. Waiting up to {ASSIST_WAIT//60} min (close the tab to skip).",flush=True)
                if platform.system()=="Darwin":
                    try:
                        import subprocess
                        subprocess.run(["osascript","-e",'display notification "Review the form and click Submit" with title "Ready: '+re.sub(r'[\"\\\\]','',who)[:60]+'" sound name "Glass"'],timeout=5)
                    except Exception: pass
                try: await page.bring_to_front()
                except Exception: pass
                sm=None; t0=time.time(); body=""
                while time.time()-t0<ASSIST_WAIT:
                    await asyncio.sleep(3)
                    try: body=await body_text(page); url_now=page.url
                    except Exception: break   # the applicant closed the tab: skip this job
                    sm=re.search(r"thank you for (applying|your application|submitting|your interest|sharing)|thanks for applying|application (has been |was |is )?(submitted|received|sent|in\b|complete)|we('ve| have) received your application|successfully submitted|you're all set",body,re.I)
                    if not sm and re.search(r"/confirmation\b",url_now): sm=re.search(r"\S.{0,60}",body)
                    if sm: break
                report["assist"]=True; report["submitted"]=bool(sm)
                report["result"]=("Submitted by the applicant in assist mode: "+sm.group(0)) if sm else "NOT SUBMITTED: assist mode - not submitted (skipped or timed out)"
                if not sm and re.search(r"possible spam|flagged as (possible )?spam|pause browser extensions|different (network )?connection instead",body,re.I): report["spam_blocked"]=True
            elif submit and not report["unanswered"]:
                cands=page.locator('button:has-text("Send application"), button#btn-submit, button[type="submit"], input[type="submit"], button:has-text("Submit application"), button:has-text("Submit Application"), button:has-text("Submit")')
                btn=None
                for i in range(await cands.count()):
                    c=cands.nth(i)
                    try:
                        if await c.is_visible() and re.search(r"submit|apply|send",(await c.inner_text()) or (await c.get_attribute("value")) or "submit",re.I): btn=c; break
                    except Exception: pass
                if btn is None:
                    if re.search(r"job board you were viewing is no longer active|job you requested was not found|Job not found|can.t find that page|could not find that page|Page not found|job (you are looking for )?(is )?no longer (open|available)|position (has been )?(filled|closed)",await body_text(page),re.I):
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
                            for _w in range(15):   # the submit spinner can run for a while after the code: wait for a confirmation, an error or a rejected code
                                await page.wait_for_timeout(3000)
                                body=await body_text(page)
                                if re.search(r"thank you for|thanks for|application (has been |was |is )?(submitted|received|sent|in\b)|success|/confirmation",body+" "+page.url,re.I): break
                                if re.search(r"invalid|incorrect|expired|doesn.t match|try again",body,re.I) and re.search(r"security code|verification code",body,re.I): break
                            if re.search(r"security code|verification code",body,re.I) and re.search(r"invalid|incorrect|expired|doesn.t match|try again",body,re.I): report.setdefault("errors",[]).append("verification code rejected")
                    # Greenhouse's uploader occasionally drops the file ("Cannot read properties of undefined (reading 'uploadFile')"): re-attach and submit once more
                    errs0=await page.evaluate("()=>[...document.querySelectorAll('[class*=error], [role=alert]')].map(e=>e.innerText.trim()).filter(Boolean).slice(0,8)")
                    if attempt==0 and any(re.search(r"uploadFile|Resume/CV is required",e) for e in errs0):
                        try:
                            await page.locator('input[type="file"]').first.set_input_files(resume_for(jtitle),timeout=15000); await page.wait_for_timeout(6000)
                            report.setdefault("notes",[]).append("resume re-attached after uploader error"); continue
                        except Exception: pass
                    break
                sm=re.search(r"thank you for (applying|your application|submitting|your interest|sharing)|thanks for applying|application (has been |was |is )?(submitted|received|sent|in\b|complete)|we('ve| have) received your application|successfully submitted|you're all set|task complete|good news",body,re.I)
                if re.search(r"/confirmation\b",page.url) and re.search(r"upstream (request failed|connect error)|bad gateway|service unavailable|gateway time-?out|\b50[234]\b",body[:400],re.I):
                    # the confirmation page itself failed to render (proxy/CDN hiccup): reload it once to read the real confirmation
                    try:
                        await page.reload(wait_until="domcontentloaded",timeout=45000); await page.wait_for_timeout(4000); body=await body_text(page)
                        sm=re.search(r"thank you for (applying|your application|submitting|your interest|sharing)|thanks for applying|application (has been |was |is )?(submitted|received|sent|in\b|complete)|we('ve| have) received your application",body,re.I)
                    except Exception: pass
                    if not sm: report["confirmation_page_error"]=True
                if not sm and re.search(r"/confirmation\b",page.url) and not report.get("confirmation_page_error"): sm=re.search(r"\S.{0,60}",body)   # Greenhouse confirmation page URL
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
                if report.get("confirmation_page_error") and not ok:   # redirected to /confirmation but the page never rendered: never retried (it may have gone through), never counted
                    report["submitted"]=True; report["result"]="UNCERTAIN: redirected to the Greenhouse confirmation URL but the confirmation page failed to load; counted only after a confirmation email"
                if not ok and re.search(r"possible spam|flagged as (possible )?spam|pause browser extensions|pause ad ?blockers|different (network )?connection instead|could not verify|verify you are (a )?human",body,re.I):
                    report["result"]="NOT SUBMITTED: blocked by the site's spam check - apply by hand"; report["spam_blocked"]=True
                await page.screenshot(path=f"{OUT}/{tag}_after.png",full_page=True)
            elif submit and any(re.search(r"update your location preferences|^i am currently in",u.get("label",""),re.I) for u in report["unanswered"]):
                report["result"]="NOT SUBMITTED: location restricted by employer (location picker offers no US option)"
            elif submit: report["result"]="NOT SUBMITTED: unanswered required questions"
        except Exception as e:
            report["result"]=f"ERROR {type(e).__name__}: {str(e)[:300]}"
            try: await page.screenshot(path=f"{OUT}/{tag}_error.png",full_page=True)
            except Exception: pass
        json.dump(report,open(f"{OUT}/{tag}_report.json","w"),indent=1)
        await page.close()
        return report
asyncio.run(run())
