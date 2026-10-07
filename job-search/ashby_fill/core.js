/* Ashby + Lever application filler (core). Runs in the applicant's own browser on jobs.ashbyhq.com and jobs.lever.co.
 * - Attaches the applicant's resume (picked once, kept only in this browser) and answers the form with the same rules
 *   as job-search/tools/apply.py (exported to rules.js; email/phone/street come from the one-time setup, never the repo).
 * - AI-use questions about this application are answered Yes (the applicant's answer, 2026-10-07); a certification that
 *   no AI was used, or that the applicant personally filled the form, is never ticked. Never guesses a question it has
 *   no rule for, never ticks disclosures.
 * - Fill mode: fills and stops; the applicant reviews and clicks Submit.
 * - Batch mode (userscript only): the applicant confirms a category once; each form is submitted only when every
 *   required question was answered by the rules and no captcha challenge is shown. Anything else is left for the
 *   applicant. A spam rejection is recorded and never retried; two in a row stop the batch.
 * Requires AKF_RULES (rules.js). Optional: GM_getValue/GM_setValue (Tampermonkey), window.__AKF (bookmarklet setup). */
(function () {
'use strict';
if (window.__AKF_LOADED) { try { window.__AKF_LOADED.run({ manual: true }); } catch (e) {} return; }
const R = AKF_RULES;
const VERSION = '2026-10-07.9';
const SITE = /(^|\.)jobs\.lever\.co$/.test(location.hostname) ? 'lever' : 'ashby';
// Timers run in a Web Worker: Chrome throttles a background tab's own timers (to once a minute after 5 minutes hidden),
// a worker's timers keep their pace, so a run in a background tab / behind other windows keeps going at full speed.
const sleep = (() => {
  let w = null, seq = 0; const cbs = {};
  try {
    w = new Worker(URL.createObjectURL(new Blob(['onmessage=e=>setTimeout(()=>postMessage(e.data.id),e.data.ms)'], { type: 'text/javascript' })));
    w.onmessage = e => { const f = cbs[e.data]; delete cbs[e.data]; if (f) f(); };
    w.onerror = () => { w = null; };
  } catch (e) { w = null; }
  return ms => new Promise(r => {
    if (!w) return setTimeout(r, ms);
    const id = ++seq; cbs[id] = r;
    setTimeout(() => { if (cbs[id]) { delete cbs[id]; r(); } }, ms + 2000);   // fallback if the worker is blocked
    w.postMessage({ id, ms });
  });
})();
function keepAlive() {   // a held Web Lock keeps Chrome from freezing / discarding this tab while a batch runs
  try { if (navigator.locks && !keepAlive.on) { keepAlive.on = true; navigator.locks.request('akf-keepalive', () => new Promise(() => {})); } } catch (e) {}
}
function notify(text) {   // a desktop notification when the applicant is needed (captcha), even with the tab in the background
  try { if (typeof GM_notification === 'function') GM_notification({ title: 'Job filler', text, timeout: 60000 }); } catch (e) {}
}
const clean = s => (s || '').replace(/\s+/g, ' ').replace(/[✱*]/g, '').trim();
const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// ---------------- storage (Tampermonkey storage when available, else this site's localStorage) ----------------
const HAS_GM = typeof GM_getValue === 'function' && typeof GM_setValue === 'function';
const W = (typeof unsafeWindow !== 'undefined' && unsafeWindow) || window;   // the page window (for window.opener)
const S = {
  get(k, d) {
    try {
      if (HAS_GM) { const v = GM_getValue(k); return v === undefined ? d : v; }
      const v = localStorage.getItem('akf_' + k); return v == null ? d : JSON.parse(v);
    } catch (e) { return d; }
  },
  set(k, v) {
    try { if (HAS_GM) GM_setValue(k, v); else localStorage.setItem('akf_' + k, JSON.stringify(v)); return true; }
    catch (e) { return false; }
  },
};
// bookmarklet setup: the helper page puts the applicant's details into the bookmarklet itself
if (window.__AKF && typeof window.__AKF === 'object') {
  const cur = S.get('me', {});
  for (const k of ['email', 'phone', 'street']) if (window.__AKF[k]) cur[k] = String(window.__AKF[k]);
  S.set('me', cur);
}
const me = () => S.get('me', {});
const today = (plusDays = 0, yy = false) => {
  const d = new Date(Date.now() + plusDays * 86400000);
  const mm = String(d.getMonth() + 1).padStart(2, '0'), dd = String(d.getDate()).padStart(2, '0');
  return `${mm}/${dd}/${yy ? String(d.getFullYear()).slice(2) : d.getFullYear()}`;
};
function sub(v) {
  if (Array.isArray(v)) return v.map(sub);
  if (typeof v !== 'string') return v;
  const m = me();
  return v.replace(/\{\{(email|phone|street|today)\}\}/g, (_, k) => k === 'today' ? today(0, true) : (m[k] || ''));
}
const P = new Proxy({}, { get: (_, k) => (['email', 'phone', 'street'].includes(k) ? me()[k] || '' : R.PROFILE[k] || '') });

// ---------------- rules (same order and matching as apply.py's pick) ----------------
const compile = rules => rules.map(([p, v]) => [new RegExp(p), /[A-Z]/.test(p), v]);
const TEXT = compile(R.TEXT_RULES), CHOICE = compile(R.CHOICE_RULES);
const rx = (p, f) => new RegExp(p, f || '');
const PERSONAL_Q = rx(...R.PERSONAL_Q), TECH_Q = rx(...R.TECH_Q), NOT_MINE = rx(...R.NOT_MINE);
const TECH_BANK = R.TECH_BANK.map(([p, v]) => [new RegExp(p), v]);
const STACK_TRUE = rx(R.STACK_TRUE, 'i'), ENV_TRUE = rx(R.ENV_TRUE, 'i'), OPTION_TRUE = rx(R.OPTION_TRUE, 'i');
const HEAR_BAD = rx(R.HEAR_BAD, 'i'), HEAR_Q = rx(R.HEAR_Q, 'i');
const JOB = { why: '', textRules: [], choiceRules: [], bay: false };
function pick(label, kind) {
  const l = (label || '').toLowerCase();
  const rules = kind === 'text' ? JOB.textRules.concat(TEXT) : JOB.choiceRules.concat(CHOICE);
  for (const [re, upper, v] of rules) {
    if (re.test(l) || (upper && re.test(label))) {
      if (JOB.why && typeof v === 'string' && v === R.WHY_US) return JOB.why;
      return sub(v);
    }
  }
  return null;
}
function techAnswer(label) {
  let l = (label || '').toLowerCase();
  if (PERSONAL_Q.test(l) || !TECH_Q.test(l)) return null;
  if (/^\s*if (yes|so|applicable|other)\b/.test(l)) {
    if (NOT_MINE.test(label) || /camunda|\bbpm\b|clinical|government|clearance|relative|referr|sponsor|visa|previous(ly)? (employ|work)|worked (for|at)|non-?compete|convict/.test(l)) return 'N/A';
    l = l.replace(/^\s*if (yes|so|applicable)[,:]?\s*/, '');
  }
  const count = re => (l.match(new RegExp(re.source, 'g')) || []).length;
  const hits = TECH_BANK.map((b, i) => [count(b[0]), i, b]).filter(x => x[0] > 0).sort((a, b) => b[0] - a[0] || a[1] - b[1]).slice(0, 2).map(x => x[2][1]);
  let ans = hits.length ? hits.join(' ') : R.TECH_DEFAULT;
  const m = (label || '').match(NOT_MINE);
  if (m) ans = `My production work has been in Python, Go, Rust, C++, Java and C#/.NET on AWS, GCP and Azure rather than ${m[0].trim()}, so here is the closest comparable experience. ` + ans;
  return ans;
}
function category(title, desc) {
  const t = (title || '') + ' ' + (desc || ''); let best = ['platform', 0];
  for (const [c, p] of R.CATS) { const n = (t.match(new RegExp(p, 'gi')) || []).length; if (n > best[1]) best = [c, n]; }
  return best[0];
}
function whyFor(company, title, desc) {
  const cat = category(title, desc); const co = (company || 'your team').trim();
  return `I want to join ${co} as ${title} because ${R.WHY_BY_CAT[cat] || R.WHY_BY_CAT.platform}. ` +
    'I still write critical-path code in Python, Go, Rust and C++, I measure what I build, and I am based in Santa Clara, CA with no sponsorship needed.';
}
function coverText(company, title, desc) {
  const cat = category(title, desc); company = company || 'your team';
  return `Dear ${company} Hiring Team,\n\nI am applying for the ${title} role. I bring the combination this position needs: the ability to design the architecture, build the critical software and lead engineering through delivery. Across 25+ years in financial technology, distributed systems and, most recently, agentic AI and open-model inference, I have worked where performance, correctness and trust are non-negotiable.\n\n${R.PARA[cat] || R.PARA.platform}\n\nI still write critical-path Python, Rust, C++ and Go, I use agentic engineering practices daily, and I measure what I build. I am based in Santa Clara, CA, fully authorized to work in the United States with no sponsorship required, open to remote, hybrid or relocation, and available to start immediately.\n\nI would welcome the chance to discuss how I can contribute to ${company}.\n\nSincerely,\nAmbarish Krishnamurthy\n${P.email} | ${P.phone} | ${P.linkedin}`;
}
// option text t satisfies preference pref (apply.py _match): equal, leading phrase, or (loose) whole-word
function match(t, pref, strict) {
  const tl = (t || '').toLowerCase().trim(), pl = (pref || '').toLowerCase().trim();
  if (!tl || !pl) return false;
  if (tl === pl || new RegExp('^' + esc(pl) + "($|[\\s,./:;()\\-'])").test(tl)) return true;
  if (strict) return false;
  return pl.length >= 3 && new RegExp('(^|[^a-z0-9])' + esc(pl) + '($|[^a-z0-9])').test(tl);
}
function bestIndex(texts, prefs) {
  for (const pv of prefs) {
    if (typeof pv !== 'string') continue;
    let i = texts.findIndex(t => t && t.toLowerCase().trim() === pv.toLowerCase().trim()); if (i >= 0) return i;
    for (const strict of [true, false]) { i = texts.findIndex(t => t && match(t, pv, strict)); if (i >= 0) return i; }
  }
  return -1;
}

// ---------------- DOM helpers ----------------
function setValue(el, v) {
  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const desc = Object.getOwnPropertyDescriptor(proto, 'value');
  el.focus();
  desc.set.call(el, v);
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}
function press(el) {
  for (const t of ['pointerdown', 'mousedown', 'pointerup', 'mouseup']) el.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window }));
  el.click();
}
const visible = el => !!(el && (el.offsetParent || el.getClientRects().length));
function labelOf(input) {
  const l = input.id && document.querySelector('label[for="' + CSS.escape(input.id) + '"]');
  if (l && clean(l.innerText)) return clean(l.innerText);
  const c = input.closest('label'); if (c && clean(c.innerText)) return clean(c.innerText);
  let p = input.parentElement;
  for (let i = 0; i < 4 && p; i++) { const t = clean(p.innerText); if (t && t.length < 300) return t; p = p.parentElement; }
  return input.name || '';
}
const ENTRY_SEL = SITE === 'lever'
  ? '#application-form .application-question, form[action*="apply"] .application-question, .application-additional, .eeo-section .application-question'
  : '.ashby-application-form-field-entry, fieldset.ashby-application-form-input-checkbox-group, fieldset[class*="fieldEntry"]';
function entries() {
  return [...document.querySelectorAll(ENTRY_SEL)]
    .filter((e, i, a) => visible(e) && !a.some(o => o !== e && o.contains(e)));
}
function titleOf(e) {
  if (SITE === 'lever') {
    const t = e.querySelector('.application-label, .text, label, legend, h4');
    return t ? clean(t.innerText) : clean((e.innerText || '').split('\n')[0]);
  }
  const t = e.querySelector('.ashby-application-form-question-title, label, legend');
  return t ? clean(t.innerText) : '';
}
function descOf(e) {
  const d = e.querySelector(SITE === 'lever' ? '.application-question-description, .description' : '.ashby-application-form-question-description');
  return d ? clean(d.innerText) : '';
}
function isRequired(e) {
  if (SITE === 'lever') {
    const t = e.querySelector('.application-label, label');
    return !!e.querySelector('.required') || !!(t && /✱/.test(t.innerText || '')) || !!e.querySelector('[required], [aria-required="true"]');
  }
  const t = e.querySelector('.ashby-application-form-question-title, label, legend');
  return !!(t && (/_required_/.test(t.className) || /[*✱]\s*$/.test(t.innerText || ''))) || !!e.querySelector('[required], [aria-required="true"]');
}
async function waitFor(fn, ms = 8000, step = 200) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { try { const v = fn(); if (v && !(Array.isArray(v) && !v.length)) return v; } catch (e) {} await sleep(step); }
  return null;
}
const optionsNow = () => [...document.querySelectorAll('[role="option"]')].filter(visible);

// ---------------- files ----------------
function b64ToFile(f) {
  const bin = atob(f.b64); const u = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
  return new File([u], f.name, { type: f.type || 'application/pdf' });
}
function resumeFor(title) {
  const exec = /\b(CTO|Chief (Technology|AI|Executive|Product|Information)|VP|SVP|EVP|Vice President|Head of|Director|Manager|TLM)\b/i.test(title || '') && !/\bArchitect/i.test(title || '');
  return (exec && S.get('resume_exec')) || S.get('resume_main') || S.get('resume_exec');
}
async function attach(input, f, entry) {
  const dt = new DataTransfer(); dt.items.add(b64ToFile(f));
  input.files = dt.files;
  input.dispatchEvent(new Event('change', { bubbles: true }));
  input.dispatchEvent(new Event('input', { bubbles: true }));
  if (SITE === 'lever') {
    const box = entry || input.closest('.application-question') || input.closest('li') || input.parentElement;
    const ok = await waitFor(() => box && (box.innerText.includes(f.name) || /success|uploaded/i.test(box.innerText)) && !/uploading|parsing/i.test(box.innerText), 15000, 400);
    return !!ok || (!!(input.files && input.files.length) && !/error|fail|too large/i.test(box ? box.innerText : ''));
  }
  const box = entry || input.closest('.ashby-application-form-field-entry') || input.parentElement;
  return !!(await waitFor(() => box && box.innerText.includes(f.name) && !/uploading|parsing|analyzing/i.test(box.innerText), 20000, 400));
}

// ---------------- answering one question ----------------
const AI_TEXT = /ai policy|use of ai|ai assistance|ai tools? (in|during)|without (the use of )?ai|ai agent|are you an ai|automated (agent|applicant|submission)|(did|have) you use(d)? (any )?ai|(prepared|submitted|written|generated|completed).{0,40}\b(ai|artificial intelligence)\b/i;
const AI_YES = /^Yes\. I used AI tools/;   // the applicant's own AI-use disclosure (TEXT_RULES); nothing else answers an AI question
const DISCLOSE = /non-?compete|non-?solicit|financial interest|conflict of interest|relatives?\b|related to|family member|government official|convicted|felony|i am (currently )?subject to|i (currently )?hold|i have (a|an) (current|existing|ongoing)|i (was|have been) (previously )?(employed|terminated)|debarred|sanction|export/i;
const ACK = /agree|acknowledge|consent|certify|confirm|privacy|terms|policy|accurate|true|^accept$|i accept|i have read/i;
const PERSONAL_CERT = /personally (completed|filled|prepared|written|wrote) (out )?(this|the|my) (application|form)|completed (this|the) application (myself|personally|on my own)/i;
const BAY_OFFICE = [/santa clara/i, /san jose|sunnyvale|mountain view|palo alto|menlo park|cupertino|redwood city|san mateo/i, /san francisco|bay area|south san francisco|oakland/i, /remote.{0,15}(us|united states)|united states.{0,10}remote/i, /remote/i];

async function answerText(e, q, input, rep) {
  const path = e.getAttribute('data-field-path') || '';
  const cur = input.value || '';
  let v = null;
  const nm = input.name || '';
  if (path === '_systemfield_name' || (SITE === 'lever' && nm === 'name')) v = P.name;
  else if (path === '_systemfield_email' || input.type === 'email' || (SITE === 'lever' && nm === 'email')) v = P.email;
  else if (SITE === 'lever' && nm === 'phone') v = P.phone;
  else if (SITE === 'lever' && nm === 'org') v = P.org;
  else if (SITE === 'lever' && /^urls\[linked/i.test(nm)) v = P.linkedin;
  else if (SITE === 'lever' && /^urls\[git/i.test(nm)) v = P.github;
  else if (SITE === 'lever' && /^urls\[/i.test(nm)) { if (!isRequired(e)) return !!cur.trim(); v = P.linkedin; }
  else if (AI_TEXT.test(q)) { v = pick(q, 'text'); if (!(typeof v === 'string' && AI_YES.test(v))) { rep.ask.push(q); return false; } }
  else if (!isRequired(e) && /^middle name|pronunciation|favou?rite|like (most|best) about|fun fact|hobb(y|ies)|nickname|^\s*if\s*[\'"“‘]?other\b|^\s*if you (selected|chose|answered|picked)\s*[\'"“‘]?(other|yes)\b|something you built with/i.test(q)) return !!cur.trim();
  else if (/^\s*if you (selected|chose|answered|picked)\s*[\'"“‘]?other\b/i.test(q)) v = 'N/A';
  else {
    const mw = q.replace(/^in \d-\d sentences,? (describe |explain )?/i, '').match(/why (are )?you('re| are)? ?(are )?(interested|excited)( in| about)? (working at|working for|joining|to join|to work at|to work for) ([A-Z][\w&.'\- ]{1,40}?)[\s.?,]*$|why (do )?you want to (work at|join) ([A-Z][\w&.'\- ]{1,40}?)[\s.?,]*$/i);
    if (mw) { const co = (mw[7] || mw[10] || '').trim(); v = `${co}'s mission and the scope of this role sit where my experience is strongest: building and leading platforms where performance, correctness and trust matter. As CTO and co-founder of Hyperion AI I built an agentic AI platform end to end, and as Chief Architect at Yahoo Finance I led 75+ engineers on a platform serving about 40M daily users. I want to bring that mix of hands-on architecture and engineering leadership to ${co}'s products and team.`; }
    if (v == null && /cover letter/i.test(q)) v = coverText(JOB.company, JOB.title, JOB.desc);
    if (v == null) v = pick(q, 'text');
    if (v == null && input.placeholder && !/type here/i.test(input.placeholder)) v = pick(input.placeholder, 'text');
    if (v == null && !cur.trim()) {
      const req = isRequired(e);
      if (req || !/\b(link|url|website|github|portfolio|profile|handle|twitter|linkedin)\b|^\s*if (yes|so|applicable|other)\b|anything else|additional (info|comments?|notes?|details)|cover letter|message (to|for)|note (to|for)/i.test(q)) {
        v = techAnswer(q); if (v) rep.tech.push(q);
      }
    }
  }
  if (v == null || v === '') return !!cur.trim();
  if (cur.trim() && input.tagName === 'TEXTAREA' && !/cover letter/i.test(q)) return true;
  if (cur !== v) setValue(input, v);
  input.blur();
  rep.filled.push([q, String(v).slice(0, 60)]);
  return true;
}
async function answerLocation(e, q, input, rep) {
  if (input.value && /santa clara/i.test(input.value)) return true;
  for (const t of ['Santa Clara, California', 'Santa Clara, CA', 'Santa Clara']) {
    setValue(input, t);
    const opt = await waitFor(() => optionsNow().filter(x => /santa clara/i.test(x.innerText)), 7000, 300);
    if (opt) {
      const o = opt.find(x => /santa clara.{0,40}(california|\bca\b|united states|usa)/i.test(x.innerText));
      if (o) {
        press(o); await sleep(600);
        if (/santa clara/i.test(input.value) || /santa clara/i.test(e.innerText.replace(q, ''))) { rep.filled.push([q, clean(o.innerText).slice(0, 60)]); input.blur(); return true; }
      }
    }
  }
  // some forms only list countries (Docker): the applicant is in the United States
  setValue(input, 'United States');
  const us = await waitFor(() => optionsNow().filter(x => /^united states( of america)?$/i.test(clean(x.innerText))), 5000, 300);
  if (us) { press(us[0]); await sleep(500); input.blur(); rep.filled.push([q, 'United States']); return true; }
  setValue(input, ''); input.blur();
  return false;
}
async function answerLeverLocation(e, q, input, rep) {
  const sel = document.querySelector('#selected-location, input[name="selectedLocation"]');
  if (input.value && /santa clara/i.test(input.value) && (!sel || sel.value)) return true;
  input.focus(); setValue(input, 'Santa Clara');
  for (const t of ['keydown', 'keypress', 'keyup']) input.dispatchEvent(new KeyboardEvent(t, { key: 'a', bubbles: true }));   // Lever looks places up on key events
  const opt = await waitFor(() => [...document.querySelectorAll('.dropdown-location, .dropdown-results div, [role="option"]')].filter(x => visible(x) && /santa clara/i.test(x.innerText)), 8000, 300);
  const o = opt && opt.find(x => /santa clara.{0,40}(california|\bca\b|united states|usa)/i.test(x.innerText));
  if (o) { press(o); await sleep(500); }
  input.blur(); rep.filled.push([q, clean(input.value).slice(0, 60) || 'Santa Clara, California']);
  return true;
}
async function answerCombo(e, q, input, rep) {
  const cur = clean(input.value);
  if (cur && !/^select|^start typing/i.test(cur)) return true;
  let prefs = pick(q, 'choice') || pick(q + ' ' + descOf(e), 'choice');
  if (prefs && prefs[0] === '__ASK__') { rep.ask.push(q); return false; }
  if (!prefs) return false;
  prefs = prefs.filter(p => typeof p === 'string');
  if (HEAR_Q.test(q)) prefs = prefs.filter(p => !HEAR_BAD.test(p));
  const toggle = e.querySelector('button[class*="toggle"]');
  if (toggle) press(toggle); else { input.focus(); press(input); }
  let opts = await waitFor(optionsNow, 5000, 250) || [];
  let texts = opts.map(o => clean(o.innerText)).map(t => (HEAR_Q.test(q) && HEAR_BAD.test(t)) ? '' : t);
  let i = bestIndex(texts, prefs);
  if (i < 0) {   // long lists render part of their options: type the first preference to filter
    setValue(input, prefs[0].slice(0, 20));
    opts = await waitFor(optionsNow, 5000, 250) || [];
    texts = opts.map(o => clean(o.innerText)); i = bestIndex(texts, prefs);
  }
  if (i < 0) { input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); input.blur(); rep.options[q] = texts.slice(0, 15); return false; }
  press(opts[i]); await sleep(500); input.blur();
  rep.filled.push([q, texts[i].slice(0, 60)]);
  return true;
}
async function answerYesNo(e, q, rep) {
  const btns = [...e.querySelectorAll('button[data-option], .ashby-application-form-input-yesno button')];
  if (btns.some(b => b.getAttribute('aria-pressed') === 'true')) return true;
  let prefs = pick(q, 'choice') || pick(q + ' ' + descOf(e), 'choice');
  if (prefs && prefs[0] === '__ASK__') { rep.ask.push(q); return false; }
  if (!prefs) return false;
  const texts = btns.map(b => clean(b.innerText));
  const i = bestIndex(texts, prefs);
  if (i < 0) { rep.options[q] = texts; return false; }
  press(btns[i]); await sleep(250);
  rep.filled.push([q, texts[i]]);
  return btns[i].getAttribute('aria-pressed') === 'true' || !!(await waitFor(() => btns[i].getAttribute('aria-pressed') === 'true', 1500, 150));
}
async function check(input) {
  if (input.checked) return true;
  const l = input.id && document.querySelector('label[for="' + CSS.escape(input.id) + '"]');
  (l || input).click(); await sleep(150);
  if (!input.checked) { input.click(); await sleep(150); }
  return input.checked;
}
async function answerRadio(e, q, rep) {
  const radios = [...e.querySelectorAll('input[type="radio"]')];
  if (radios.some(r => r.checked)) return true;
  const opts = radios.map(labelOf);
  const p1 = pick(q, 'choice') || pick(q + ' ' + descOf(e), 'choice'), p2 = pick(opts.join(' '), 'choice');
  if (p1 && p1[0] === '__ASK__') { rep.ask.push(q); return false; }
  const cands = [p1, p2 && p2[0] !== '__ASK__' ? p2 : null].filter(Boolean);
  let texts = opts.slice();
  if (HEAR_Q.test(q)) texts = texts.map(t => HEAR_BAD.test(t) ? '' : t);
  let i = -1;
  for (const prefs of cands) { i = bestIndex(texts, prefs.filter(p => typeof p === 'string')); if (i >= 0) break; }
  if (i < 0 && texts.length >= 2 && texts.every(t => /,\s*[A-Z]{2}\b|,\s*[A-Z][a-z]+|remote|hybrid/i.test(t))) {   // an office list with no question text: the Bay Area office
    for (const re of BAY_OFFICE) { i = texts.findIndex(t => re.test(t)); if (i >= 0) break; }
  }
  if (i < 0) i = texts.findIndex(t => t && OPTION_TRUE.test(t) && !/\b(not|unable|outside|don't|do not)\b/i.test(t));
  if (i < 0) { rep.options[q] = opts.slice(0, 12); return false; }
  const ok = await check(radios[i]);
  if (ok) rep.filled.push([q, opts[i].slice(0, 60)]);
  return ok;
}
async function answerCheckboxes(e, q, rep) {
  const boxes = [...e.querySelectorAll('input[type="checkbox"]')].filter(b => !b.closest('.ashby-application-form-input-yesno'));
  if (!boxes.length) return false;
  if (boxes.some(b => b.checked)) return true;
  const labs = boxes.map(labelOf);
  if (boxes.length === 1) {
    const t = labs[0] || q;
    if (PERSONAL_CERT.test(t)) { rep.ask.push(t); return false; }
    if (!isRequired(e) && /marketing|newsletter|future (job )?opportunit|talent (community|pool)|keep me|stay in touch|text message|\bsms\b|job alerts/i.test(t + ' ' + q)) return false;
    if (DISCLOSE.test(t) && !ACK.test(q)) return false;
    if (ACK.test(t) || ACK.test(q)) { const ok = await check(boxes[0]); if (ok) rep.filled.push([q || t, 'checked']); return ok; }
    return false;
  }
  const isSrc = HEAR_Q.test(q);
  let members = boxes.map((b, i) => [b, labs[i]]);
  if (isSrc) members = members.filter(m => !HEAR_BAD.test(m[1])) || members;
  if (/select all that apply|check all that apply|environments|best describes?|which (of the following )?(technolog|tools|languages|frameworks|services|platforms|types of|kinds of|practices|people-leadership|leadership)/i.test(q) && !/hear|learn|source|ethnic|race|gender|disab|veteran|pronoun|sanction|citizenship|countr/i.test(q)) {
    const ticked = [];
    for (const [b, l] of members) if ((ENV_TRUE.test(l) || STACK_TRUE.test(l)) && !/none of the above|not applicable|n\/a|prefer not|^other\b/i.test(l)) { if (await check(b)) ticked.push(l.slice(0, 30)); }
    if (ticked.length) { rep.filled.push([q, ticked.join(', ')]); return true; }
  }
  let want = pick(q, 'choice') || (isSrc ? ['LinkedIn', 'Company Website', 'Careers page', 'Job Board', 'Other'] : null);
  if (want && want[0] === '__ASK__') { rep.ask.push(q); return false; }
  if (!want) { rep.options[q] = labs.slice(0, 12); return false; }
  let i = bestIndex(members.map(m => m[1]), want.filter(p => typeof p === 'string'));
  if (i < 0 && isSrc) i = Math.max(0, members.findIndex(m => /other/i.test(m[1])));
  if (i < 0) { rep.options[q] = labs.slice(0, 12); return false; }
  const ok = await check(members[i][0]);
  if (ok) rep.filled.push([q, members[i][1].slice(0, 60)]);
  return ok;
}
async function answerDate(e, q, input, rep) {
  if (input.value) return true;
  const v = /start|available|availability|join|begin|notice/i.test(q) ? today(14) : (/today|date of application|signature|sign/i.test(q) ? today(0) : null);
  if (!v) return false;
  setValue(input, v); input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); input.blur(); await sleep(300);
  const ok = !!input.value; if (ok) rep.filled.push([q, v]);
  return ok;
}
async function answerSelect(e, q, sel, rep) {
  if (sel.value) return true;
  const prefs = pick(q, 'choice'); if (!prefs || prefs[0] === '__ASK__') return false;
  const texts = [...sel.options].map(o => clean(o.text));
  const i = bestIndex(texts, prefs); if (i < 0) return false;
  sel.value = sel.options[i].value; sel.dispatchEvent(new Event('change', { bubbles: true }));
  rep.filled.push([q, texts[i]]); return true;
}
const TEXT_SEL = 'textarea, input[type="text"]:not([role="combobox"]):not(.ashby-application-form-input-date), input[type="email"], input[type="tel"], input[type="url"], input[type="number"], input:not([type]):not([role="combobox"])';
const OFFICE3_Q = /\b(three|four|five|3|4|5)\s*(\+\s*)?(days?|x)\s*(a|per|each)?\s*week|\b(fully|full[- ]time|100%) (in[- ]office|on[- ]?site|in[- ]person)|in[- ]person (5|five) days/i;
function answered(e) {
  const t = e.querySelector(TEXT_SEL);
  if (t && !clean(t.value)) return false;
  if (e.querySelector('.ashby-application-form-input-yesno')) return [...e.querySelectorAll('button[data-option]')].some(b => b.getAttribute('aria-pressed') === 'true');
  if (e.querySelector('input[type="radio"]')) return [...e.querySelectorAll('input[type="radio"]')].some(r => r.checked);
  if (e.querySelector('input[type="file"]')) { const f = e.querySelector('input[type="file"]'); return (f.files && f.files.length > 0) || /\.(pdf|docx?)\b/i.test(e.innerText); }
  if (e.querySelector('input[role="combobox"]')) { const c = e.querySelector('input[role="combobox"]'); return !!clean(c.value) || !!e.querySelector('[class*="selected"], [class*="chip"], [class*="tag"]'); }
  if (e.querySelector('input[type="checkbox"]')) return [...e.querySelectorAll('input[type="checkbox"]')].some(b => b.checked);
  if (e.querySelector('select')) return !!e.querySelector('select').value;
  if (t) return !!clean(t.value);
  return true;
}

// ---------------- one form ----------------
function jobInfo() {
  const m = location.pathname.match(/^\/([^/]+)\/([0-9a-f-]{36})/i);
  if (SITE === 'lever') {
    const h = document.querySelector('.posting-headline h2, .posting-header h2, h2');
    const parts = document.title.split(/\s+[-–]\s+/);
    return { slug: m && m[1], id: m && m[2], title: clean((h && h.innerText) || parts.slice(1).join(' - ')), company: clean(parts[0] || (m && m[1]) || ''), desc: clean(document.body.innerText).slice(0, 6000) };
  }
  const h1 = document.querySelector('h1');
  const title = clean((h1 && h1.innerText) || document.title.split('@')[0]);
  const company = clean((document.title.split('@')[1] || (m && m[1]) || '').replace(/[-_]+/g, ' '));
  return { slug: m && m[1], id: m && m[2], title, company, desc: clean(document.body.innerText).slice(0, 6000) };
}
async function fillForm(opts = {}) {
  const rep = { filled: [], ask: [], tech: [], options: {}, missing: [], resume: null, notes: [], office: [] };
  const info = jobInfo(); Object.assign(JOB, info);
  JOB.bay = /San Francisco|Bay Area|Palo Alto|Menlo Park|Mountain View|Sunnyvale|San Jose|Santa Clara|Redwood City|San Mateo|Oakland|Berkeley|Cupertino|Foster City|Burlingame|Fremont|Milpitas|Emeryville|Los Gatos|Campbell|Pleasanton|San Ramon|Walnut Creek|Hayward/.test(info.desc.slice(0, 1500));
  JOB.okOffice = JOB.bay || (/New York|NYC|Manhattan|Brooklyn/.test(info.desc.slice(0, 1500)) && /hybrid/i.test(info.desc));   // Bay Area on-site / hybrid and NY hybrid are fine (applicant's rules)
  const prior = (opts.prior || []).filter(Boolean);
  JOB.choiceRules = compile([
    ["(previously|ever|already|recently) applied|applied (for|to) (another|other|a different|any other|an?other|any) (role|position|job|opening)|applied (to|with|at) .{0,40}(before|previously|in the (past|last)|within the (past|last))|participated in (a|any) (hiring|recruiting|interview) process|interviewed (with|at) .{0,40}(before|previously|in the (past|last))", prior.length ? ['Yes', 'yes'] : ['No', 'no', 'No, I have not', 'I have not applied']],
    ['if you are not (a )?local( candidate)?,? (do|would) you (require|need) relocation|not (a )?local candidate.{0,40}relocation', JOB.bay ? ['No', 'no', 'N/A'] : ['Yes', 'yes']],
  ]);
  JOB.textRules = compile([["^if (yes|so).{0,80}\\bappl(ied|y|ication)|(which|what) (role|position)s? did you (previously )?apply|when did you (previously )?apply", prior.length ? 'Yes: ' + prior.slice(0, 3).join('; ') + ' (2026)' : 'N/A']]);
  JOB.why = whyFor(info.company, info.title, info.desc);
  if (SITE === 'ashby' && !/\/application/.test(location.pathname)) {   // on the posting: open the application tab
    const a = [...document.querySelectorAll('a, button')].find(x => /^apply( for this job)?$/i.test(clean(x.innerText)) || /\/application$/.test(x.getAttribute('href') || ''));
    if (a) { press(a); await sleep(2500); }
  }
  await waitFor(() => document.querySelector(SITE === 'lever' ? '#application-form, form[action*="apply"] .application-question' : '#_systemfield_name, .ashby-application-form-field-entry'), 15000);
  for (const t of ['Necessary Only', 'Accept All']) { const b = [...document.querySelectorAll('button')].find(x => clean(x.innerText) === t); if (b) { b.click(); break; } }
  // 1) resume first: Ashby may pre-fill from it, so everything else is answered after it
  const rin = document.querySelector('#_systemfield_resume') || document.querySelector('input[type="file"][id*="resume"], input[type="file"][name="resume"]');
  const rf = resumeFor(info.title);
  if (rin && rf) {
    const ok = (rin.files && rin.files.length) || await attach(rin, rf);
    rep.resume = ok ? rf.name : 'FAILED'; if (!ok) rep.notes.push('resume upload not confirmed');
  } else if (rin) { rep.resume = 'NOT SET UP'; rep.notes.push('no resume saved yet: open the panel and choose your resume once'); }
  // 2) every question, twice (answers can reveal follow-up questions)
  const done = new Set();
  for (let pass = 0; pass < 2; pass++) {
    for (const e of entries()) {
      if (done.has(e)) continue; done.add(e); progress();
      const path = e.getAttribute('data-field-path') || '';
      if (/_systemfield_education|_systemfield_resume/.test(path) || e.closest('[class*="education"]')) continue;
      const q = titleOf(e) || descOf(e);
      try {
        const file = e.querySelector('input[type="file"]');
        if (file) {
          if (/cover/i.test(q) && S.get('cover')) { const ok = await attach(file, S.get('cover'), e); if (ok) rep.filled.push([q, S.get('cover').name]); }
          continue;
        }
        if (OFFICE3_Q.test(q + ' ' + descOf(e)) && !JOB.okOffice) rep.office.push(q);
        if (e.querySelector('.ashby-application-form-input-yesno')) { await answerYesNo(e, q, rep); continue; }
        const date = e.querySelector('.ashby-application-form-input-date, input[placeholder*="date" i]');
        if (date) { await answerDate(e, q, date, rep); continue; }
        const combo = e.querySelector('input[role="combobox"]');
        if (combo) { if (path === '_systemfield_location' || /location|\bcity\b|where .{0,20}(based|live|located|reside)|intend to work from/i.test(q) && !/country/i.test(q)) await answerLocation(e, q, combo, rep); else await answerCombo(e, q, combo, rep); continue; }
        const inp = e.querySelector(TEXT_SEL);
        if (inp && SITE === 'lever' && (inp.name === 'location' || inp.id === 'location-input')) { await answerLeverLocation(e, q, inp, rep); continue; }
        if (inp) await answerText(e, q, inp, rep);
        if (e.querySelector('input[type="radio"]')) await answerRadio(e, q, rep);
        else if (e.querySelector('input[type="checkbox"]')) await answerCheckboxes(e, q, rep);
        else { const sel = e.querySelector('select'); if (sel) await answerSelect(e, q, sel, rep); }
      } catch (err) { rep.notes.push(q.slice(0, 50) + ': ' + (err && err.message || err)); }
    }
    await sleep(600);
  }
  for (const e of entries()) {
    const path = e.getAttribute('data-field-path') || '';
    if (/_systemfield_education/.test(path)) continue;
    if (isRequired(e) && !answered(e)) rep.missing.push(titleOf(e) || descOf(e) || path);
  }
  rep.ready = !rep.missing.length && !rep.ask.length && !rep.office.length && rep.resume && rep.resume !== 'FAILED' && rep.resume !== 'NOT SET UP';
  return rep;
}

// ---------------- submit (batch mode only, after the applicant confirmed the batch) ----------------
const OK_RX = /thank you for (applying|your application|submitting|your interest)|thanks for applying|application (has been |was |is )?(successfully )?(submitted|received|sent|complete)|we('ve| have) received your application|successfully submitted|you're all set/i;
const onThanks = () => SITE === 'lever' && /\/thanks\/?$/.test(location.pathname);
const SPAM_RX = /submission (is )?(currently )?unavailable|unable to submit|possible spam|flagged as (possible )?spam|pause (your )?(browser extensions|ad ?blockers)|different (network )?connection|unusual activity|could not verify|verify (that )?you are (a )?human/i;
function captchaChallenge() {
  return [...document.querySelectorAll('iframe[src*="recaptcha"][src*="bframe"], iframe[src*="hcaptcha"], iframe[title*="challenge" i]')].some(f => { const r = f.getBoundingClientRect(); return r.width > 50 && r.height > 50 && getComputedStyle(f).visibility !== 'hidden'; });
}
async function submitForm() {
  const btn = (SITE === 'lever' && document.querySelector('#btn-submit, button[data-qa="btn-submit"]')) || [...document.querySelectorAll('button')].find(b => /^submit application$/i.test(clean(b.innerText)) && visible(b));
  if (!btn) return { status: 'error', why: 'no Submit button' };
  btn.scrollIntoView({ block: 'center' }); await sleep(300);
  btn.click();
  const t0 = Date.now();
  while (Date.now() - t0 < 30000) {
    await sleep(500); progress();
    const body = document.body.innerText || '';
    if (OK_RX.test(body)) return { status: 'submitted', why: (body.match(OK_RX) || [''])[0] };
    if (SPAM_RX.test(body)) return { status: 'blocked', why: (body.match(SPAM_RX) || [''])[0] };
    if (captchaChallenge()) return { status: 'captcha', why: 'a captcha challenge appeared: please solve it and click Submit yourself' };
    const err = [...document.querySelectorAll('[class*="error" i], [role="alert"]')].filter(visible).map(x => clean(x.innerText)).filter(Boolean);
    if (err.length && Date.now() - t0 > 4000) return { status: 'needs', why: err.slice(0, 3).join(' | ').slice(0, 200) };
  }
  return { status: 'unknown', why: 'no confirmation within 30 s' };
}

// ---------------- panel ----------------
let panel;
function ui() {
  if (panel && document.body.contains(panel)) return panel;
  panel = document.createElement('div');
  panel.id = 'akf-panel';
  panel.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:2147483647;width:340px;max-height:70vh;overflow:auto;background:#0f172a;color:#e2e8f0;font:13px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.35);padding:12px 14px';
  panel.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px"><b>Ashby filler</b><span style="opacity:.6;font-size:11px">${VERSION}</span></div>
  <div id="akf-status" style="white-space:pre-wrap"></div>
  <div id="akf-btns" style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px"></div>
  <details id="akf-setup" style="margin-top:8px"><summary style="cursor:pointer">Setup (once)</summary>
   <div style="display:grid;gap:6px;margin-top:6px">
    <label>Email <input id="akf-email" style="width:100%"></label>
    <label>Phone <input id="akf-phone" style="width:100%"></label>
    <label>Street address (optional) <input id="akf-street" style="width:100%"></label>
    <label>Resume (architect / engineer roles) <input id="akf-r1" type="file" accept=".pdf,.doc,.docx"></label>
    <label>Executive resume (CTO / VP / Head / Director / Manager) <input id="akf-r2" type="file" accept=".pdf,.doc,.docx"></label>
    <label>Cover letter (optional) <input id="akf-cl" type="file" accept=".pdf,.doc,.docx"></label>
    <label><input id="akf-auto" type="checkbox"> Fill automatically when an application opens</label>
    <button id="akf-save">Save</button><div id="akf-saved" style="opacity:.7"></div></div></details>`;
  panel.querySelectorAll('input:not([type]), input[id^="akf-e"], input[id^="akf-p"], input[id^="akf-s"]').forEach(i => i.style.cssText = 'width:100%;color:#0f172a;border-radius:6px;border:0;padding:4px 6px');
  document.body.appendChild(panel);
  const m = me();
  panel.querySelector('#akf-email').value = m.email || ''; panel.querySelector('#akf-phone').value = m.phone || ''; panel.querySelector('#akf-street').value = m.street || '';
  panel.querySelector('#akf-auto').checked = !!S.get('autofill', HAS_GM);
  const files = () => ['resume_main', 'resume_exec', 'cover'].map(k => S.get(k)).map((f, i) => `${['Resume', 'Executive resume', 'Cover letter'][i]}: ${f ? f.name : '-'}`).join('\n');
  panel.querySelector('#akf-saved').textContent = files();
  const readFile = inp => new Promise(res => { const f = inp.files && inp.files[0]; if (!f) return res(null); const r = new FileReader(); r.onload = () => res({ name: f.name, type: f.type || 'application/pdf', b64: String(r.result).split(',')[1] }); r.readAsDataURL(f); });
  panel.querySelector('#akf-save').onclick = async () => {
    S.set('me', { email: panel.querySelector('#akf-email').value.trim(), phone: panel.querySelector('#akf-phone').value.trim(), street: panel.querySelector('#akf-street').value.trim() });
    S.set('autofill', panel.querySelector('#akf-auto').checked);
    for (const [id, k] of [['akf-r1', 'resume_main'], ['akf-r2', 'resume_exec'], ['akf-cl', 'cover']]) { const f = await readFile(panel.querySelector('#' + id)); if (f) { if (!S.set(k, f)) alert('Could not save ' + f.name + ' (too large for this browser storage).'); } }
    panel.querySelector('#akf-saved').textContent = 'Saved.\n' + files();
  };
  if (!m.email || !(S.get('resume_main') || S.get('resume_exec'))) panel.querySelector('#akf-setup').open = true;
  return panel;
}
function banner(text, good, ms) {   // an unmissable confirmation that the filler is live on this page
  try {
    let el = document.getElementById('akf-banner');
    if (!el) { el = document.createElement('div'); el.id = 'akf-banner'; document.documentElement.appendChild(el); }
    el.textContent = text;
    el.style.cssText = `position:fixed;top:0;left:0;right:0;z-index:2147483647;padding:10px 14px;text-align:center;font:600 14px system-ui,sans-serif;color:#fff;background:${good ? '#0b6b58' : '#a15c07'}`;
    clearTimeout(banner.t); banner.t = setTimeout(() => { try { el.remove(); } catch (e) {} }, ms || (good ? 4000 : 9000));
  } catch (e) {}
}
function status(t) { ui().querySelector('#akf-status').textContent = t; }
function buttons(list) {
  const b = ui().querySelector('#akf-btns'); b.innerHTML = '';
  for (const [label, fn, primary] of list) {
    const x = document.createElement('button'); x.textContent = label;
    x.style.cssText = `padding:6px 10px;border-radius:8px;border:0;cursor:pointer;font-weight:600;${primary ? 'background:#22c55e;color:#052e16' : 'background:#334155;color:#e2e8f0'}`;
    x.onclick = fn; b.appendChild(x);
  }
}
function summary(rep) {
  const lines = [];
  lines.push(`Resume: ${rep.resume || '-'}`);
  lines.push(`Answered: ${rep.filled.length}`);
  if (rep.ask.length) lines.push(`For you (AI-use / personal certification): ${rep.ask.map(x => x.slice(0, 60)).join('; ')}`);
  if (rep.missing.length) lines.push(`Still needed: ${rep.missing.map(x => x.slice(0, 60)).join('; ')}`);
  if (rep.office.length) lines.push(`Heads-up: this form asks about office days outside the Bay Area / NY hybrid (${rep.office.map(x => x.slice(0, 60)).join('; ')}): your call.`);
  if (rep.notes.length) lines.push(`Notes: ${rep.notes.join('; ').slice(0, 300)}`);
  lines.push(rep.ready ? 'Ready: review the form, then click Submit Application.' : 'Please complete the items above, then click Submit Application.');
  return lines.join('\n');
}

// ---------------- batch (userscript) ----------------
const Q_KEY = 'queue';
function curJobId() { const m = location.pathname.match(/\/([0-9a-f-]{36})/i); return m && m[1].toLowerCase(); }
function nextUrl(item) {
  if (/jobs\.lever\.co/.test(item.u)) return item.u.replace(/\/apply\/?$/, '').replace(/\/$/, '') + '/apply';
  return item.u.replace(/\/application\/?$/, '').replace(/\/$/, '') + '/application';
}
function report(q, item, res) {
  q.results = q.results || {};
  q.results[item.id] = Object.assign({ t: item.t, c: item.c, u: item.u, at: Date.now() }, res);
  S.set(Q_KEY, q);
  try { if (W.opener) W.opener.postMessage({ akf: 'result', id: item.id, res: q.results[item.id] }, '*'); } catch (e) {}
}
const CLOSED_RX = /job (is )?no longer|not found|no longer accepting|no longer available|(doesn.t|does not|don.t) exist|(has been|is|was) (closed|filled|removed|unpublished)|position (is )?(closed|filled)|404/i;
// ---- pacing, one-window lock, and a persistent record of every job this browser already submitted ----
const PACE_MIN = 5000, PACE_MAX = 50000;            // random wait AFTER the form is filled, right before each submission: 5 s - 50 s (the run page can set its own), doubled after each Ashby block (up to x4)
const CAPTCHA_WAIT = 3 * 60000;                      // a captcha waits 3 min for the applicant (desktop notification), then the run moves on
const BLOCK_WAIT = [240000, 360000];                 // after Ashby's "submission unavailable" / spam block: 4-6 min before the next job
const TAB_ID = (() => {   // one id per browser tab: window.name survives every page load in the tab (also Ashby <-> Lever)
  try { const n = String(W.name || ''); if (/^akf-[a-z0-9]{6,}$/.test(n)) return n; const id = 'akf-' + Math.random().toString(36).slice(2, 10); W.name = id; return id; }
  catch (e) { return 'akf-' + Math.random().toString(36).slice(2, 10); }
})();
let lastProgress = Date.now();
const progress = () => { lastProgress = Date.now(); };
const STUCK_MS = 120000;                             // a job with no progress for 2 minutes is recorded and the run moves on
const DONE_KEY = 'done';                             // {jobId: ts} - submitted jobs, kept across batches so a job is never sent twice
function doneMap() { return S.get(DONE_KEY, {}) || {}; }
function markDone(id) { const d = doneMap(); d[id] = Date.now(); S.set(DONE_KEY, d); }
async function acquireLock(q) {
  // only one window applies at a time: a second window waits while the first one's heartbeat is fresh
  for (let i = 0; i < 720; i++) {
    const l = S.get('lock', null);
    if (!l || l.id === TAB_ID || Date.now() - l.ts > 150000) { S.set('lock', { id: TAB_ID, ts: Date.now() }); return true; }
    if (q && S.get(Q_KEY, q).stopped) return false;
    status(`Another window is applying right now; this one waits so Ashby is not hit twice at once... (${Math.round((150000 - (Date.now() - l.ts)) / 1000)} s)`);
    progress(); await sleep(5000);
  }
  return true;
}
function heartbeat() { progress(); const l = S.get('lock', null); if (!l || l.id === TAB_ID) S.set('lock', { id: TAB_ID, ts: Date.now() }); }
function releaseLock() { const l = S.get('lock', null); if (l && l.id === TAB_ID) S.set('lock', null); }
async function paceWait(item, q, ms, label) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    if (S.get(Q_KEY, q).stopped) return false;
    heartbeat();
    const last = S.get('lastSubmitAt', 0); const ago = last ? Math.round((Date.now() - last) / 1000) : null;
    status(`Batch "${q.name}": ${q.i + 1} of ${q.items.length}\n${item.c} - ${item.t}\n${label || 'Form filled. Waiting'} ${Math.ceil((ms - (Date.now() - t0)) / 1000)} s ${label ? '' : 'before submitting '}(random ${(q.pace || [PACE_MIN, PACE_MAX]).map(x => Math.round(x / 1000)).join('-')} s, filler v${VERSION})${ago != null ? `\nLast submission: ${ago} s ago` : ''}`);
    await sleep(1000);
  }
  return true;
}
function watchdog(q, item) {   // a job that makes no progress for 2 minutes (page hung, form never loads) is recorded and skipped
  (async () => {
    for (;;) {
      await sleep(5000);
      if (advance.once || waitingForYou) return;
      const cur = S.get(Q_KEY, null);
      if (!cur || cur.done || cur.stopped || cur.i !== q.i) return;
      if (Date.now() - lastProgress > STUCK_MS) { report(cur, item, { status: 'unknown', why: 'no progress for 2 minutes: moved on', answered: -1 }); advance(cur); return; }
    }
  })();
}
let waitingForYou = false;
async function batchStep(q) {
  const item = q.items[q.i];
  if (!item || curJobId() !== item.id) return false;
  progress(); watchdog(q, item);
  // ONE random wait per job, whatever happens to it: before Submit when it is submitted, before moving on otherwise
  const [pMin, pMax] = (Array.isArray(q.pace) && q.pace.length === 2 && q.pace[1] >= q.pace[0]) ? q.pace : [PACE_MIN, PACE_MAX];   // pacing chosen by the run page
  const paceMs = q.auto ? Math.round((pMin + Math.random() * (pMax - pMin)) * (q.paceMul || 1)) : 0;
  const gap = async (why) => {   // the SPACER: a visible countdown after every job, before the next application opens
    if (!(paceMs > 0) || S.get(Q_KEY, q).stopped) return true;
    const t0 = Date.now(), pz = [pMin, pMax].map(x => Math.round(x / 1000)).join('-');
    while (Date.now() - t0 < paceMs) {
      if (S.get(Q_KEY, q).stopped) return false;
      heartbeat();
      const left = Math.ceil((paceMs - (Date.now() - t0)) / 1000);
      banner(`⏳ ${why} - next application in ${left} s (random ${pz} s spacing, v${VERSION})`, true, 2500);
      status(`Batch "${q.name}": ${q.i + 1} of ${q.items.length}\n${item.c} - ${item.t}\n${why}.\nNext application in ${left} s (random ${pz} s spacing).`);
      await sleep(1000);
    }
    return true;
  };
  status(`Batch "${q.name}": ${q.i + 1} of ${q.items.length}\n${item.c} - ${item.t}\nFilling...`);
  buttons([['Stop batch', () => { q.stopped = 'by you'; S.set(Q_KEY, q); status('Batch stopped.'); buttons([]); }]]);
  if (doneMap()[item.id]) {   // this browser already submitted this exact job (an earlier batch / the other window)
    report(q, item, { status: 'skipped', why: 'already submitted earlier from this browser', answered: 0 });
    S.set(Q_KEY, q); await gap('Already submitted earlier - skipped'); advance(q); return true;
  }
  if (!await acquireLock(q)) return true;
  keepAlive();
  if (onThanks() || (OK_RX.test(document.body.innerText || '') && !entries().length)) {   // the confirmation page of the job just submitted
    report(q, item, { status: 'submitted', why: (document.body.innerText.match(OK_RX) || ['confirmation page'])[0], answered: -1 }); markDone(item.id);
    q.blocks = 0; S.set(Q_KEY, q); await gap(`Submitted ${item.c}`); advance(q); return true;
  }
  heartbeat();
  // a closed / removed posting never holds the batch: wait (20 s at most) for the form OR a closed notice, then move on
  const seen = await waitFor(() => entries().length ? 'form' : (CLOSED_RX.test(document.body.innerText || '') ? 'closed' : null), 12000, 300);
  if (seen !== 'form') {
    if (q.stopped) return true;
    report(q, item, { status: 'closed', why: seen === 'closed' ? 'posting closed / not found' : 'no application form on the page (posting removed?)', answered: 0 });
    q.blocks = 0; S.set(Q_KEY, q); await gap(seen === 'closed' ? 'Posting closed - skipped' : 'No application form - skipped'); advance(q); return true;
  }
  let rep;
  try { rep = await fillForm({ prior: item.p || [] }); }
  catch (e) {   // a filler error on one job is logged and the batch continues
    if (q.stopped) return true;
    report(q, item, { status: 'unknown', why: 'filler error: ' + String((e && e.message) || e).slice(0, 80), answered: 0 });
    S.set(Q_KEY, q); await gap('Filler error - skipped'); advance(q); return true;
  }
  let res;
  if (q.stopped) return true;
  if (/job (is )?no longer|not found|no longer accepting/i.test(document.body.innerText) && !entries().length) res = { status: 'closed', why: 'posting closed' };
  else if (q.auto && rep.ready && captchaChallenge()) res = { status: 'captcha', why: 'tick the captcha, then click Submit application' };
  else if (q.auto && rep.ready) {
    const since = Date.now() - (S.get('lastSubmitAt', 0) || 0);   // shared by every tab and window: never two submissions closer than the spacing
    if (since < paceMs && !await paceWait(item, q, paceMs - since)) return true;
    S.set('lastSubmitAt', Date.now());
    status(`Submitting ${item.c} - ${item.t}...`); res = await submitForm();
  }
  else res = { status: 'needs', why: rep.missing.concat(rep.ask).concat(rep.office.map(x => 'office days: ' + x)).map(x => x.slice(0, 60)).join('; ') || rep.notes.join('; ') || 'not auto-submitted' };
  res.answered = rep.filled.length;
  if (res.status === 'captcha' || !q.auto) {   // the applicant reviews and clicks Submit; the next job opens after the site confirms
    status(summary(rep) + (res.status === 'captcha' ? `\n\n${res.why}` : '') + `\n\nWhen you click Submit and the site confirms, the next job opens by itself.${q.auto ? ' (Moves on by itself after 3 minutes.)' : ''}`);
    if (res.status === 'captcha') { notify(`Captcha for ${item.c} - ${item.t}: tick it and click Submit`); banner('Captcha: tick it, then click Submit application', false); }
    let skipped = false;
    buttons([['Skip this job', () => { skipped = true; }], ['Stop batch', () => { q.stopped = 'by you'; S.set(Q_KEY, q); skipped = true; }]]);
    const t0 = Date.now(); waitingForYou = true;
    while (!skipped && Date.now() - t0 < (q.auto ? CAPTCHA_WAIT : 30 * 60000)) {
      heartbeat();
      await sleep(1000);
      const body = document.body.innerText || '';
      if (OK_RX.test(body)) { res = { status: 'submitted', why: (body.match(OK_RX) || [''])[0], by: 'you', answered: rep.filled.length }; break; }
      if (SPAM_RX.test(body)) { res = { status: 'blocked', why: (body.match(SPAM_RX) || [''])[0], by: 'you', answered: rep.filled.length }; break; }
    }
    waitingForYou = false; progress();
    if (skipped && res.status !== 'submitted') res = { status: 'skipped', why: 'skipped by you', answered: rep.filled.length };
  }
  report(q, item, res);
  if (res.status === 'submitted') markDone(item.id);
  q.blocks = res.status === 'blocked' ? (q.blocks || 0) + 1 : 0;
  if (res.status === 'blocked') q.paceMul = Math.min(4, (q.paceMul || 1) * 2);   // Ashby pushed back: slow down for the rest of the run
  if (q.blocks >= 3) q.stopped = "Ashby rejected three submissions in a row (submission unavailable / spam check): wait an hour, then press Start again";
  S.set(Q_KEY, q);
  if (res.status === 'blocked' && !q.stopped) {   // back off before the next job instead of hammering
    const ms = BLOCK_WAIT[0] + Math.floor(Math.random() * (BLOCK_WAIT[1] - BLOCK_WAIT[0]));
    const t0 = Date.now();
    while (Date.now() - t0 < ms && !S.get(Q_KEY, q).stopped) { heartbeat(); status(`Ashby blocked that submission ("${(res.why || '').slice(0, 60)}"). Waiting ${Math.ceil((ms - (Date.now() - t0)) / 1000)} s before the next job...`); await sleep(1000); }
  }
  if (res.status !== 'blocked') await gap(res.status === 'submitted' ? `✓ Submitted ${item.c}` : res.status === 'needs' ? `Not submitted: ${item.c} needs an answer (listed at the end)` : `Not submitted (${res.status}): ${item.c}`);
  await sleep(800);
  advance(q);
  return true;
}
function advance(q) {
  if (advance.once) return; advance.once = true;   // one job per page: never skip a job by advancing twice
  q = S.get(Q_KEY, q);
  if (q.stopped) return finish(q);
  q.i += 1; S.set(Q_KEY, q);
  if (q.i >= q.items.length) return finish(q);
  location.href = nextUrl(q.items[q.i]);
}
function finish(q) {
  releaseLock();
  const r = Object.values(q.results || {});
  const by = s => r.filter(x => x.status === s);
  const lines = [`Batch "${q.name}" ${q.stopped ? 'stopped: ' + q.stopped : 'finished'}.`, `Submitted: ${by('submitted').length}`, `Need you: ${by('needs').length + by('captcha').length + by('unknown').length}`, `Skipped: ${by('skipped').length}`, `Blocked by Ashby: ${by('blocked').length}`, `Closed: ${by('closed').length}`];
  const left = q.items.slice(q.i + (q.stopped ? 1 : 0)).filter(x => !(q.results || {})[x.id]).map(x => ({ c: x.c, t: x.t, u: x.u, status: 'not started' }));
  const todo = r.filter(x => /needs|captcha|unknown|blocked|skipped/.test(x.status)).concat(q.stopped ? left : []);
  status(lines.join('\n') + (todo.length ? '\n\nOpen these to finish (the form fills itself):\n' : ''));
  const st = ui().querySelector('#akf-status');
  for (const x of todo) { const a = document.createElement('a'); a.href = x.u.replace(/\/$/, '') + '/application'; a.target = '_blank'; a.textContent = `• ${x.c} - ${x.t} (${x.status}${x.why ? ': ' + x.why.slice(0, 50) : ''})`; a.style.cssText = 'display:block;color:#93c5fd'; st.appendChild(a); }
  buttons([['Copy results', () => navigator.clipboard.writeText(JSON.stringify(r, null, 1)), true], ['Clear batch', () => { S.set(Q_KEY, null); status('Cleared.'); buttons([]); }]]);
  q.done = true; S.set(Q_KEY, q);
  try { if (W.opener) W.opener.postMessage({ akf: 'done', results: q.results }, '*'); } catch (e) {}
}
function readHashQueue() {
  const m = location.hash.match(/akf=([A-Za-z0-9_\-]+)/);
  if (!m) return null;
  history.replaceState(null, '', location.pathname + location.search);
  try {
    const json = decodeURIComponent(escape(atob(m[1].replace(/-/g, '+').replace(/_/g, '/'))));
    const d = JSON.parse(json);
    const items = (d.items || []).filter(x => x && /^https:\/\/jobs\.(ashbyhq\.com|lever\.co)\/[^/]+\/[0-9a-f-]{36}/i.test(x.u)).map(x => Object.assign(x, { id: x.u.match(/([0-9a-f-]{36})/i)[1].toLowerCase() }));
    if (!items.length) return null;
    const pace = Array.isArray(d.pace) && d.pace.length === 2 ? d.pace.map(Number).map(x => Math.max(1000, Math.min(300000, x || 0))) : null;
    return { name: String(d.name || 'batch').slice(0, 60), auto: !!d.auto, pace, items, i: 0, results: {} };
  } catch (e) { return null; }
}

// ---------------- entry points ----------------
async function run(opts = {}) {
  ui();
  if (!HAS_GM && !opts.manual && !S.get('autofill', false)) { status('Click "Fill this application".'); buttons([['Fill this application', () => run({ manual: true }), true]]); return; }
  status('Filling...'); buttons([]);
  const rep = await fillForm({ prior: opts.prior || [] });
  // apply on its own when asked to and the form is complete (bookmarklet single-job auto-submit)
  if (opts.submit && rep.ready && !captchaChallenge()) {
    banner('Submitting your application…', true);
    status(summary(rep) + '\n\nSubmitting…');
    const res = await submitForm();
    if (res.status === 'submitted') { banner('✓ Application submitted', true); status(summary(rep) + '\n\n✓ Submitted. Open the next job and click the bookmark again.'); buttons([['Fill again', () => run({ manual: true })]]); window.__AKF_LAST = rep; return rep; }
    status(summary(rep) + `\n\nCould not confirm (${res.why}). Review and click Submit Application yourself.`);
    buttons([['Fill again', () => run({ manual: true })]]); window.__AKF_LAST = rep; return rep;
  }
  if (rep.ready) banner('✓ Form filled — review and click Submit Application', true);
  else banner('Form filled; some items need you (see the panel)', false);
  status(summary(rep));
  buttons([['Fill again', () => run({ manual: true })]]);
  window.__AKF_LAST = rep;
  return rep;
}
async function boot() {
  if (!/(^|\.)jobs\.(ashbyhq\.com|lever\.co)$/.test(location.hostname)) { alert('Open an Ashby or Lever application page first.'); return; }
  banner(`✓ ${SITE === 'lever' ? 'Lever' : 'Ashby'} filler active · v` + VERSION, true);
  const hq = readHashQueue();
  if (hq) {
    const n = hq.items.length;
    const pz = (hq.pace || [PACE_MIN, PACE_MAX]).map(x => Math.round(x / 1000)).join('-');
    const ok = (hq.auto && n === 1) ? true : confirm(`Filler v${VERSION} - after every application it counts down a random ${pz} s before opening the next one.\n\n${hq.auto ? 'AUTO-SUBMIT' : 'Fill'} ${n} application${n > 1 ? 's' : ''} for "${hq.name}"?\n\n` +
      hq.items.slice(0, 20).map(x => `• ${x.c} - ${x.t}`).join('\n') + (n > 20 ? `\n...and ${n - 20} more` : '') +
      (hq.auto ? '\n\nEach form is submitted only if every required question is answered by your rules; anything else is left for you.' : ''));
    if (ok) S.set(Q_KEY, hq);
  }
  const q = S.get(Q_KEY, null);
  if (q && !q.done && !q.stopped && q.items && q.items[q.i]) {
    if (curJobId() === q.items[q.i].id) { await sleep(900); if (await batchStep(q)) return; }
    else if (/(^|\.)jobs\.(ashbyhq\.com|lever\.co)$/.test(location.hostname)) {
      await sleep(1200);
      const body = document.body.innerText || '';
      const item = q.items[q.i]; let res;
      if (OK_RX.test(body)) res = { status: 'submitted', why: (body.match(OK_RX) || [''])[0], answered: -1 };
      else if (SPAM_RX.test(body)) res = { status: 'blocked', why: (body.match(SPAM_RX) || [''])[0], answered: -1 };
      else res = { status: 'unknown', why: 'left the application page before a confirmation was seen', answered: -1 };
      report(q, item, res);
      if (res.status === 'submitted') markDone(item.id);
      q.blocks = res.status === 'blocked' ? (q.blocks || 0) + 1 : 0;
      if (q.blocks >= 2) q.stopped = "Ashby's spam check rejected two submissions in a row";
      S.set(Q_KEY, q);
      await sleep(1200); advance(q); return;
    }
  }
  if (q && q.done) { ui(); finish(q); }
  const auto = S.get('autofill', HAS_GM);
  if (curJobId() && (auto || window.__AKF) && (SITE === 'ashby' || /\/apply\/?$/.test(location.pathname))) { await sleep(1500); return run({ manual: true, submit: !!(window.__AKF && window.__AKF.auto) }); }
  ui(); status('Open an application, then click Fill.'); buttons([['Fill this application', () => run({ manual: true }), true]]);
}
window.__AKF_LOADED = { run, fillForm, submitForm, pick, techAnswer, bestIndex, version: VERSION };
if (!window.__AKF_TEST) boot();
})();
