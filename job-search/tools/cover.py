"""Per-posting cover letter generator: picks a fit paragraph from the job description and renders text + PDF."""
import re, os
CATS = [
 ("inference", r"inference|serving|vllm|gpu|kernel|throughput|latency|llama|model (performance|efficiency)|compute|cluster|training infra"),
 ("agentic", r"agent|mcp|tool[- ]calling|orchestrat|rag|retrieval|copilot|llm application|applied ai|ai platform|genai|generative"),
 ("fintech", r"fintech|payment|trading|exchange|crypto|blockchain|ledger|bank|lending|risk|fraud|wallet|defi|financial"),
 ("leadership", r"head of|vp|vice president|cto|chief|director|lead (the|a) team|build (and|&) lead|org"),
 ("platform", r"platform|infrastructure|distributed|kubernetes|scal|reliab|backend|data platform|storage|database"),
]
PARA = {
 "inference": "Your work on inference and model infrastructure is exactly where I have been spending my hands-on time. At Hyperion AI I built a Python/llama.cpp model-and-agent evaluation platform, profiled prefill/decode throughput, TTFT and TPOT across Qwen 1.5B-35B-A3B, gpt-oss-20B and Llama 3.3-70B configurations, designed CPU/GPU and accelerator runtime boundaries with PyTorch, ONNX Runtime and vLLM integration paths, and shipped reproducible benchmark evidence (121-measure scorecards informed by MLPerf Inference and BFCL). Earlier I engineered sub-250-microsecond execution paths at JPMorgan, so I am comfortable making latency, memory and correctness trade-offs measurable.",
 "agentic": "The agentic systems you are building map directly onto what I have shipped. At Hyperion AI I implemented MCP clients and three MCP servers exposing nine tools with role-based allowlists, schema validation, execution budgets and approval-gated actions; multi-agent plan-validate-dispatch-observe-replan loops with reasoner/verifier roles; and RAG pipelines over financial and regulatory documents using LangChain, Pinecone and Redis vector stores. At Yahoo Finance I architected OpenAI/LangChain research assistants over news, filings and fundamentals for roughly 40M daily users, with LLM observability, drift detection and governance built in.",
 "fintech": "I have spent 25+ years building the financial systems this role touches: OMS/EMS, smart order routing, market data, risk, clearing, settlement and reconciliation at JPMorgan, Morgan Stanley, Bloomberg and Bank of America, and more recently crypto trading, wallet analytics, DEX routing, Canton/Daml credentialing and KYC/AML workflows at Hyperion AI and Motocho. I connect those workflows to agentic AI with the controls regulated environments require: deterministic replay, idempotency, audit trails and approval-gated model actions.",
 "leadership": "As CTO and Technical Co-Founder of Hyperion AI I led a founding team of 15+ while owning architecture, critical-path code and institutional-partner conversations. As Distinguished Architect at Yahoo Finance I directed 75+ engineers and partners through a bare-metal-to-AWS modernization serving roughly 150M monthly users, aligning product, legal, security and compliance on phased migration, cutover and 24x7 operation. I lead by staying hands-on: architecture reviews, benchmarks, profiling and Claude Code-assisted engineering practices that raise a whole team's output.",
 "platform": "I have architected and operated the kind of platform you describe: AWS/GCP modernization at Yahoo Finance supporting roughly 40M daily active users with ~5 ms tick-to-quote streaming; Go/gRPC, Rust/Tokio and C++17 services with bounded concurrency, backpressure, idempotency and deterministic replay; Kubernetes, Kafka/Redpanda, Cassandra and Redis at scale; and cryptographic entitlement infrastructure at Cadence handling more than 2 million daily license checkouts.",
}
def category(title, desc):
    t=(title or "")+" "+(desc or "")
    scores=[(len(re.findall(pat,t,re.I)),c) for c,pat in CATS]
    scores.sort(reverse=True)
    return scores[0][1] if scores[0][0]>0 else "platform"
def text(company, title, desc, profile, pitch=None):
    """pitch: a paragraph written for this posting (what the role needs, matched to the applicant's own record); it leads
    the letter, followed by the category paragraph."""
    cat=category(title,desc)
    company=company or "your team"
    return (f"Dear {company} Hiring Team,\n\n"
            f"I am applying for the {title} role. I bring the combination this position needs: the ability to design the architecture, build the critical software and lead engineering through delivery. Across 25+ years in financial technology, distributed systems and, most recently, agentic AI and open-model inference, I have worked where performance, correctness and trust are non-negotiable.\n\n"
            + (f"{pitch.strip()}\n\n" if pitch else "") +
            f"{PARA[cat]}\n\n"
            f"I still write critical-path Python, Rust, C++ and Go, I use agentic engineering practices daily, and I measure what I build. I am based in Santa Clara, CA, fully authorized to work in the United States with no sponsorship required, open to remote, hybrid or relocation, and available to start immediately.\n\n"
            f"I would welcome the chance to discuss how I can contribute to {company}.\n\n"
            f"Sincerely,\nAmbarish Krishnamurthy\n{profile.get('email','')} | {profile.get('phone','')} | {profile.get('linkedin','')}")
def pdf(path, body):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.units import inch
    doc=SimpleDocTemplate(path,pagesize=letter,leftMargin=1*inch,rightMargin=1*inch,topMargin=0.9*inch,bottomMargin=0.9*inch)
    st=getSampleStyleSheet(); st["Normal"].fontSize=10.5; st["Normal"].leading=14
    els=[]
    for para in body.split("\n\n"):
        els.append(Paragraph(para.replace("\n","<br/>"),st["Normal"])); els.append(Spacer(1,8))
    doc.build(els); return path
