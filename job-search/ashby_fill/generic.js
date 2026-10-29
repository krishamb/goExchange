/* Any-ATS application filler (generic part of the Ashby filler userscript). build.py puts it before core.js; core.js calls
 * AKF_GENERIC(helpers) on every page that is not Ashby or Lever (SmartRecruiters, iCIMS, Workable, BambooHR, Rippling, Gem,
 * SuccessFactors, Pinpoint, ADP, Teamtailor, Zoho Recruit, Dover, UKG, Paycor, JazzHR, ClearCompany, Comeet, Oracle Cloud,
 * Jobvite, Greenhouse - the @match lines of the userscript header).
 * - FILL ONLY. It never clicks Submit / Apply / Next / Send (nor any submit button or link), never presses Enter, never signs
 *   in, and never touches a CAPTCHA (reCAPTCHA / hCaptcha / Turnstile / DataDome) or a field the page asks to leave blank.
 * - Answers come from the same tables as the Ashby / Lever filler (AKF_RULES TEXT_RULES / CHOICE_RULES, exported from
 *   tools/apply.py) and from the applicant's details kept in this browser (Setup: email, phone, street, ZIP, resume). Nothing
 *   personal is in the repository. A question the rules do not answer is left empty for the applicant; so is anything already
 *   filled, and a certification that no AI was used / that the applicant personally completed the form is never ticked.
 * - It fills what is on the page, then watches the page (multi-step forms, questions that appear late) and fills new fields as
 *   they appear. The small panel says how many fields it filled and has "Fill again". */
function AKF_GENERIC(L) {
'use strict';
const R = L.R, S = L.S, clean = L.clean, sleep = L.sleep, bestIndex = L.bestIndex, JOB = L.JOB;
const PANEL_ID = 'akf-gpanel';
let IN_FRAME = false; try { IN_FRAME = window.top !== window.self; } catch (e) { IN_FRAME = true; }
const HOST = location.hostname.toLowerCase();

// ---------------- where it may act (only career / application pages of these domains) ----------------
function pageOk() {
  const h = HOST, path = location.pathname.toLowerCase(), all = (location.pathname + location.search + location.hash).toLowerCase();
  if (/(^|\.)oraclecloud\.com$/.test(h)) return /candidateexperience|\/hcmui\/candidate|recruit/.test(all);
  if (/(^|\.)adp\.com$/.test(h)) return /recruit|career|mascsr|\/jobs?\b|apply/.test(all);
  if (/(^|\.)bamboohr\.com$/.test(h)) return /^\/(careers|jobs|hiring)\b/.test(path);
  if (/(^|\.)ultipro\.com$/.test(h)) return /^recruiting/.test(h) || /jobboard|opportunit|candidate|recruit/.test(all);
  if (/(^|\.)(successfactors|sapsf)\.\w+$/.test(h)) return /career|candidate|apply|jobreq|recruit/.test(all);
  if (/(^|\.)icims\.com$/.test(h)) return /^\/jobs\b/.test(path);
  if (/^app\.(teamtailor|pinpointhq)\.com$/.test(h)) return false;   // the recruiters' own app, not a careers site
  if (/(^|\.)clearcompany\.com$/.test(h)) return /career|job|apply|candidate|opening/.test(all);
  if (/(^|\.)dover\.com$/.test(h)) return /^\/(apply|jobs|careers)\b/.test(path);
  if (/^app\.jobvite\.com$/.test(h)) return /^\/companyjobs\//.test(path);   // the legacy apply pages, not the recruiters' app
  return true;
}

// ---------------- DOM helpers (open shadow roots included) ----------------
const txt = el => clean((el && (el.innerText || el.textContent)) || '');
function roots() {
  const out = [document];
  const walk = r => { for (const el of r.querySelectorAll('*')) if (el.shadowRoot) { out.push(el.shadowRoot); walk(el.shadowRoot); } };
  try { walk(document); } catch (e) {}
  return out;
}
function qsa(sel, rs) { const out = []; for (const r of rs || roots()) { try { for (const el of r.querySelectorAll(sel)) out.push(el); } catch (e) {} } return out; }
function byId(el, id) {
  if (!id) return null;
  try { const r = el.getRootNode ? el.getRootNode() : document; return (r && r.getElementById && r.getElementById(id)) || document.getElementById(id); } catch (e) { return null; }
}
function shown(el) {
  if (!el || el.nodeType !== 1 || !el.isConnected) return false;
  if (!(el.offsetParent || el.getClientRects().length)) return false;
  const cs = getComputedStyle(el);
  return cs.visibility !== 'hidden' && cs.display !== 'none';
}
function realBox(el) {   // a field a person can see: not a 1-px or off-screen bot trap
  const r = el.getBoundingClientRect();
  if (r.width < 6 || r.height < 6) return false;
  if (r.right < 0 || r.left > (window.innerWidth || 4000) + 40 || r.bottom + (window.scrollY || 0) < 0) return false;
  for (let p = el, i = 0; p && p.nodeType === 1 && i < 8; p = p.parentElement, i++) { if (getComputedStyle(p).opacity === '0') return false; }
  return true;
}
function deepActive() { let a = document.activeElement; try { while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement; } catch (e) {} return a; }
const CAPTCHA_SEL = '.g-recaptcha, .grecaptcha-badge, .h-captcha, .cf-turnstile, .frc-captcha, [data-sitekey], [data-hcaptcha-widget-id], [class*="captcha" i], [id*="captcha" i], [class*="turnstile" i], [id*="turnstile" i], [class*="datadome" i]';
const CHROME_SEL = 'header, nav, footer, [role="search"], [role="navigation"], [role="banner"], [role="contentinfo"], #onetrust-consent-sdk, #onetrust-banner-sdk, #CybotCookiebotDialog, [id*="cookie-banner" i], [class*="cookie-banner" i], [class*="cookieconsent" i], [id*="cookieconsent" i]';
function offLimits(el) {
  try {
    if (el.closest('#' + PANEL_ID + ', #akf-panel, #akf-banner')) return true;
    if (el.closest(CAPTCHA_SEL)) return true;                    // CAPTCHA widgets are never touched
    if (el.closest(CHROME_SEL)) return true;                     // site search, menus, cookie banners
    if (el.closest('[aria-hidden="true"], [inert]')) return true;
  } catch (e) {}
  const s = ((el.id || '') + ' ' + (el.getAttribute('name') || '') + ' ' + (typeof el.className === 'string' ? el.className : '') + ' ' + (el.getAttribute('autocomplete') || '')).toLowerCase();
  return /captcha|turnstile|honeypot|hpcsaf|requiredinput|iti__search|g-recaptcha|select2-search|chosen-search|bs-searchbox|choices__input--cloned|[_-]hp\b|\bhp[_-]/.test(s);
}
// never click these: anything that sends, submits, moves to the next step, signs in or leaves the page
const STOP_TEXT = /\b(submit|apply|send|next|continue|proceed|save|finish|complete|review|confirm( and)? submit|sign ?in|log ?in|sign ?up|register|create (an )?account|delete|remove|withdraw|upload|attach|import|autofill|back)\b/i;
function canClick(el) {
  if (!el || offLimits(el)) return false;
  const b = el.closest('button, a[href], input[type="submit"], input[type="image"], input[type="reset"], input[type="button"], [role="button"], [role="link"]');
  if (!b) return true;
  if (b.tagName === 'INPUT') return false;
  const t = clean(b.innerText || b.getAttribute('aria-label') || b.getAttribute('title') || '');
  if (STOP_TEXT.test(t) && !b.matches('[aria-haspopup], [role="option"], [role="combobox"]')) return false;
  if (b.tagName === 'BUTTON') return !((b.type || 'submit') === 'submit' && b.form) && b.type !== 'reset';
  if (b.tagName === 'A') return /^\s*(#|javascript:)/i.test(b.getAttribute('href') || '');
  return true;
}
function key(el, k) { for (const t of ['keydown', 'keyup']) { try { el.dispatchEvent(new KeyboardEvent(t, { key: k, code: k, bubbles: true, cancelable: true, composed: true })); } catch (e) {} } }
function setText(el, v, keepFocus) {   // the native setter + input / change (+ blur): React, Angular and Vue all take it
  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const d = Object.getOwnPropertyDescriptor(proto, 'value');
  try { el.focus({ preventScroll: true }); } catch (e) {}
  if (d && d.set) d.set.call(el, v); else el.value = v;
  el.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
  if (keepFocus) return;
  el.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
  L.leave(el, false);
}
function setSelect(sel, i) {
  try { sel.focus({ preventScroll: true }); } catch (e) {}
  sel.selectedIndex = i;
  sel.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
  sel.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
  L.leave(sel, false);
}

// ---------------- question text ----------------
const WEAK = /^(attach|attach file|upload|upload (a )?file|browse|choose( a)? files?|select( a)? files?|drop (your )?files?.*|or drag.*|drag (and|&) drop.*|select\W*|select\.\.\.|choose\W*|choose one\W*|choose an option|please select\W*|please choose\W*|select an option|select one|-+\s*select\s*-+|-+|–select–|type here\W*|start typing.*|search\W*|enter manually|optional|required|answer|your answer|enter (your )?answer( here)?|enter your text here|type your (answer|response) here|no file (selected|chosen)|file-input|none)$/i;
function strip(el) {   // an element's own words, without form controls and option lists inside it
  if (!el) return '';
  const c = el.cloneNode(true);
  try { c.querySelectorAll('select, option, input, textarea, button, svg, style, script, [role="listbox"], [role="option"], [role="alert"], [class*="error" i]').forEach(x => x.remove()); } catch (e) {}
  return clean(c.textContent || '');
}
function tidy(t) {
  return clean(String(t || '').replace(/\(\s*(required|optional)\s*\)/ig, ' ').replace(/\s+(required|optional)\s*$/i, '').replace(/[ ​]/g, ' ').replace(/\s*[:]\s*$/, '')).slice(0, 500);
}
function ariaText(el, attr) {
  const ids = (el.getAttribute(attr) || '').split(/\s+/).filter(Boolean);
  return clean(ids.map(id => byId(el, id)).filter(x => x && x !== el).map(strip).join(' '));
}
function labelOf(el) {   // the control's own label: aria-labelledby, <label>, aria-label
  const a = ariaText(el, 'aria-labelledby'); if (a) return a;
  let ls = [];
  try { ls = el.labels ? [...el.labels] : []; } catch (e) {}
  if (!ls.length && el.id) { try { ls = [...el.getRootNode().querySelectorAll('label[for="' + CSS.escape(el.id) + '"]')]; } catch (e) {} }
  if (!ls.length && el.closest) { const c = el.closest('label'); if (c) ls = [c]; }
  const t = clean(ls.map(strip).filter(Boolean).join(' '));
  if (t) return t;
  return clean(el.getAttribute('aria-label') || '');
}
function groupLabel(el) {   // the question a group of controls answers: fieldset legend, role=group / radiogroup label
  const g = el.closest && el.closest('fieldset, [role="radiogroup"], [role="group"]');
  if (!g) return '';
  const lg = g.tagName === 'FIELDSET' ? g.querySelector('legend') : null;
  if (lg && strip(lg)) return strip(lg);
  return ariaText(g, 'aria-labelledby') || clean(g.getAttribute('aria-label') || '');
}
function prevText(el, stopAtControl = true) {   // the nearest text before the control (no own label)
  const host = el.getRootNode && el.getRootNode() !== document ? el.getRootNode() : document.body;
  if (!host) return '';
  let w; try { w = document.createTreeWalker(host, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT); w.currentNode = el; } catch (e) { return ''; }
  let n, steps = 0;
  while ((n = w.previousNode()) && steps++ < 300) {
    if (n.nodeType === 1) {
      if (stopAtControl && n !== el && !n.contains(el) && n.matches('input:not([type="hidden"]), select, textarea') && shown(n)) return '';
      continue;
    }
    const s = clean(n.nodeValue); if (!s) continue;
    const pe = n.parentElement;
    if (!pe || pe.closest('option, select, script, style, button, [role="listbox"], [role="option"], [role="alert"], [class*="error" i]')) continue;
    if (/^(this field is required|required|optional|\*|error.*)$/i.test(s) || WEAK.test(s)) continue;
    const blk = pe.querySelector('input, select, textarea') ? null : pe.closest('label, legend, h1, h2, h3, h4, h5, h6, p, li, dt, th, td, span, div');
    const t = blk && !blk.querySelector('input, select, textarea') ? strip(blk) : s;
    return t.length <= 400 ? t : s;
  }
  return '';
}
function humanize(s) { return clean(String(s || '').replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[\[\]._\-]+/g, ' ').replace(/\d{3,}/g, ' ')); }
function questionOf(el) {
  let q = labelOf(el);
  if (!q || WEAK.test(q)) q = groupLabel(el) || q;
  if (!q || WEAK.test(q)) { const t = prevText(el); if (t && !WEAK.test(t)) q = t; }
  if (!q || WEAK.test(q)) { const ph = clean(el.getAttribute('placeholder') || ''); if (ph && !WEAK.test(ph)) q = ph; }
  if (!q || WEAK.test(q)) q = clean(el.getAttribute('title') || '') || humanize(el.getAttribute('name') || el.id || '');
  return tidy(WEAK.test(q) ? '' : q);
}
function requiredOf(el, extra) {
  if (el.required || el.getAttribute('aria-required') === 'true') return true;
  const g = el.closest && el.closest('[aria-required="true"], fieldset[required]'); if (g) return true;
  let t = '';
  try { t = (el.labels && el.labels[0] ? el.labels[0].textContent : '') || (byId(el, (el.getAttribute('aria-labelledby') || '').split(/\s+/)[0]) || {}).textContent || ''; } catch (e) {}
  return /[*✱]|\brequired\b/i.test(t + ' ' + (extra || ''));
}

// ---------------- the applicant's profile (Setup in this browser + the exported profile; nothing personal in the repo) ----------------
const PROF = R.PROFILE || {};
const NAME = clean(PROF.name || '');
function profileValue(k) {
  const m = L.me() || {};
  switch (k) {
    case 'first': return NAME.split(' ')[0] || '';
    case 'last': return NAME.split(' ').slice(1).join(' ');
    case 'name': return NAME;
    case 'email': case 'phone': case 'street': case 'zip': return m[k] || '';
    case 'linkedin': return PROF.linkedin || '';
    case 'github': return PROF.github || '';
    case 'website': return PROF.website || PROF.github || '';
    case 'city': return PROF.city || '';
    case 'state': return PROF.state || '';
    case 'country': return PROF.country || 'United States';
    case 'location': return PROF.location || '';
    case 'company': return PROF.org || '';
    case 'title': return pickText('your current title') || '';
  }
  return '';
}
function profilePrefs(k) {   // the same facts as menu answers
  if (k === 'country') return [PROF.country || 'United States', 'United States of America', 'USA', 'US', 'U.S.', 'United States (US)'];
  if (k === 'state') return [PROF.state || 'California', 'California', 'CA', 'California (CA)', 'CA - California', 'US-CA'];
  if (k === 'city') return [PROF.city || 'Santa Clara', 'Santa Clara'];
  if (k === 'phonecc') return ['United States (+1)', 'United States +1', 'United States', 'US (+1)', 'USA (+1)', '+1 (United States)', '+1 United States', 'US +1', '+1'];
  return null;
}
const NOT_SELF = /referr|reference|emergency|supervisor|manager.?s|recruiter|spouse|parent|guardian|relative|school|university|college|institution|previous|former|prior|employer.?s|company.?s|other names|maiden|alias|middle|nick ?name|pronunc|preferred name/i;
const KEY_LABEL = [
  ['email', /^(your |primary |personal |candidate )?e-?mail( address| id)?( \(.{0,40}\))?$|^(confirm|re-?enter|re-?type|verify) (your )?e-?mail( address)?$/],
  ['phone', /^(your |primary |personal |mobile |cell |home |candidate )?(phone|mobile|cell(ular)?|telephone|cell phone|mobile phone)( phone)?( number| no\.?| #)?( \(.{0,40}\))?$|^contact (phone|number)$|^phone number \(.{0,40}\)$/],
  ['first', /^(legal |your )?first( name)?( \(.{0,40}\))?$|^given name$|^forename$|^first \/ given name$/],
  ['last', /^(legal |your )?last( name)?( \(.{0,40}\))?$|^surname$|^family name$|^last \/ family name$/],
  ['name', /^(your |full |legal |candidate )?(full )?name$|^full legal name$|^first (and|&) last name$|^name \(first (and|&) last\)$/],
  ['linkedin', /linked ?in/],
  ['github', /^github( (profile|url|link|username|handle))?( url)?$/],
  ['website', /^(personal )?(website|web site|portfolio|blog)( url| link| address)?$|^website, blog or portfolio$|^portfolio( \/ |, | or )website$/],
  ['street', /^(street( address)?|address( line)? ?1|address line one|home address|mailing address|current address|residential address|address)$/],
  ['city', /^(city|town|city ?\/ ?town|city of residence|current city)$/],
  ['state', /^(state|province|state ?\/ ?province|state or province|region|state ?\/ ?region|state \/ province \/ region)$/],
  ['zip', /^(zip|zip code|zipcode|postal code|post code|postcode|zip ?\/ ?postal code|postal ?\/ ?zip code|zip \/ postal)$/],
  ['country', /^(country|country of residence|country ?\/ ?region|current country|country \/ territory)$/],
  ['phonecc', /^(country( calling)? code|phone country( code)?|dial(ing)? code|country code \(phone\))$/],
];
const AC_KEY = { 'given-name': 'first', 'family-name': 'last', 'name': 'name', 'email': 'email', 'tel': 'phone', 'tel-national': 'phone', 'address-line1': 'street', 'street-address': 'street', 'address-level2': 'city', 'address-level1': 'state', 'postal-code': 'zip', 'country': 'country', 'country-name': 'country' };
const NAME_KEY = [['first', /\b(first ?name|fname|given ?name|firstname)\b/], ['last', /\b(last ?name|lname|surname|family ?name|lastname)\b/], ['email', /\be ?mail( ?address)?\b|\bemailaddress\b/],
  ['phone', /\b(phone|mobile|cell ?phone|telephone|phone ?number)\b/], ['linkedin', /\blinked ?in\b/], ['github', /\bgithub\b/], ['zip', /\b(zip|zip ?code|postal ?code|postcode)\b/], ['city', /\bcity\b/]];
function labelKey(q) {   // a contact / profile field named by its label
  const l = (q || '').toLowerCase().replace(/[ ​]/g, ' ').replace(/\s+/g, ' ').trim();
  if (!l || l.length > 70 || NOT_SELF.test(l)) return '';
  for (const [k, re] of KEY_LABEL) if (re.test(l)) return k;
  return '';
}
function attrKey(el, q) {   // ... or by its autocomplete / name / id attributes (labels that say nothing useful)
  if (q && NOT_SELF.test(q)) return '';
  const ac = (el.getAttribute('autocomplete') || '').toLowerCase().trim().split(/\s+/).pop();
  if (AC_KEY[ac]) return AC_KEY[ac];
  const s = humanize((el.getAttribute('name') || '') + ' ' + (el.id || '')).toLowerCase();
  if (/\b(type|ext|extension|country|code|prefix|device|confirm(ation)? code|referr)/.test(s)) return '';
  for (const [k, re] of NAME_KEY) if (re.test(s)) return k;
  return '';
}

// ---------------- rules (the exported tables, same order and matching as core.js / apply.py) ----------------
function pickRule(label, kind) {   // the raw rule value (may hold {{email}} ...), undefined when no rule matches
  const l = (label || '').toLowerCase();
  const rules = kind === 'text' ? JOB.textRules.concat(L.TEXT) : JOB.choiceRules.concat(L.CHOICE);
  for (const [re, upper, v] of rules) {
    if (re.test(l) || (upper && re.test(label))) {
      if (JOB.why && typeof v === 'string' && v === R.WHY_US) return JOB.why;
      return v;
    }
  }
  return undefined;
}
function pickText(q) {   // a rule's text answer: string, '' (the rule says leave it empty) or null (no rule / not set up yet)
  const v = pickRule(q, 'text');
  if (v === undefined || v === null || typeof v !== 'string') return null;
  if (v === '') return '';
  const m = L.me() || {};
  for (const k of ['email', 'phone', 'street', 'zip']) if (v.indexOf('{{' + k + '}}') >= 0 && !m[k]) return null;   // Setup not done: never half an answer
  const s = L.sub(v);
  return /[a-z0-9]/i.test(s) ? s : null;
}
const RACE_LBL = /\brace\b|\braces\b|racial|\bethn|\bethin/i, CLEAR_LBL = /clearance|polygraph|\bsecret\b|\bts\/sci\b/i, LOC_Q = /location|city|where .{0,20}(based|live|located|reside)|residence/i;
const AUTH_LBL = /authori[sz]|sponsor|\bvisa\b|immigration|work permit|right to work|eligib\w* to work|citizenship|legally (able|eligible|permitted|allowed)/i;
const ASIAN_SUB = /\b(east|southeast|south-east|central|west|western|eastern)\s+asian\b/i, ASIAN_OURS = /\bsouth asian\b|\basian indian\b|\bindian\b(?! or alaska)/i;
function raceBad(t) {   // apply.py race_bad: never another race, 'Two or more', 'Other' or Hispanic / Latino (the applicant is Asian)
  const s = (t || '').replace(/\(\s*not\s+(hispanic|latin[aoxe]?)[^)]*\)|,?\s*\bnot\s+(hispanic|latin[aoxe]?)(\s+or\s+(latin[aoxe]?|hispanic))?\b|\(united states( of america)?\)/gi, '').toLowerCase();
  if (/\basian\b/.test(s)) return ASIAN_SUB.test(s) && !ASIAN_OURS.test(s);
  if (/\bnot\b|^\s*no\b|decline|wish|prefer|choose|rather|n\/a|undisclosed|self.?identify/.test(s)) return false;
  return /american indian|alaska|\bblack\b|african|hawaiian|pacific islander|\bwhite\b|caucasian|two or more|multi.?racial|\bmixed\b|middle eastern|north african|hispanic|latin[aoxe]|\bother\b/.test(s);
}
function clearanceClaim(t) {   // apply.py clearance_claim: an option claiming a clearance the applicant never held
  const s = (t || '').toLowerCase();
  if (/\b(do not|don.?t|never|no longer|not currently)\b.{0,30}\b(have|hold|held|had)\b|^\s*no\b|never had|none\b|\bno (active|current|existing)\b|\beligible\b|\bclearable\b|\bwithout\b/.test(s)) return false;
  return /already (have|hold)|currently (have|hold)|i (have|hold) (a|an|my) |^\s*yes,? ?(confidential|secret|top secret|ts)|^\s*(active|inactive|expired) clearance|\b(active|current) (secret|top secret|ts\/sci|clearance)\b/.test(s);
}
function sponsorClaim(t) {   // apply.py sponsor_claim: an option saying the applicant needs sponsorship / holds a temporary visa
  const s = (t || '').toLowerCase();
  if (/^\s*no\b|\b(do|does|will|would|shall)( not|n.?t)\b.{0,25}\b(need|require)|\bnever\b.{0,25}\b(need|require)|\bnot (need|require)|\bwithout\b|\bno (visa |employer |company |immigration )?sponsorship|\bnot (currently )?(on|hold\w*|hav\w*) (a |an |any )?(temporary|visa|h-?1)|\bnot required\b|\bnot applicable\b|^\s*n\/?a\b/.test(s)) return false;
  if (/\b(need|needs|needing|require|requires|requiring|may need|may require|would need|would require|with)\b.{0,30}\bsponsor|\bsponsorship (is )?(needed|required)\b/.test(s)) return true;
  return /\b(h-?1b?|f-?1|opt|stem opt|cpt|tn|l-?1|e-?3|j-?1|o-?1|h-?4)\b/.test(s) && !/citizen|green card|permanent/.test(s);
}
function mask(texts, q) {   // options the applicant's rules never pick (apply.py mask_hear and friends)
  return texts.map(t => {
    if (!t) return t;
    if (L.HEAR_Q.test(q) && L.HEAR_BAD.test(t)) return '';
    if (LOC_Q.test(q) && /santa clara/i.test(t) && !/california|\bca\b|united states|\busa?\b/i.test(t)) return '';
    if (RACE_LBL.test(q) && raceBad(t)) return '';
    if (CLEAR_LBL.test(q) && clearanceClaim(t)) return '';
    if (AUTH_LBL.test(q) && sponsorClaim(t)) return '';
    if (/\bcountry\b|nationality/i.test(q) && /minor outlying|virgin islands/i.test(t)) return '';
    return t;
  });
}
function choicePrefs(el, q, rep) {   // the preference list for a menu / radio / checkbox question, null when no rule answers it
  if (L.BOT_ASK.test(q)) { rep.ask.push(q + ' (the form asks bots not to answer)'); return null; }
  let p = pickRule(q, 'choice');
  if (p === undefined || p === null) { const k = labelKey(q) || (el ? attrKey(el, q) : ''); p = profilePrefs(k); }
  if (p === undefined || p === null) {   // no menu rule: a short text-rule answer ('LinkedIn', 'California', 'No') is the same answer
    const t = pickText(q);
    if (t && t.length <= 60) p = [t];
    else if (t && /^(yes|no)\b[.,:;]/i.test(t)) p = [t.match(/^(yes|no)/i)[1]];
  }
  if (!p) return null;
  if (!Array.isArray(p)) p = [p];
  if (p[0] === '__ASK__') { rep.ask.push(q); return null; }
  if (p[0] === '__MULTI__') p = p.slice(1);
  p = p.filter(x => typeof x === 'string' && x);
  if (L.HEAR_Q.test(q)) p = p.filter(x => !L.HEAR_BAD.test(x));
  return p.length ? p : null;
}
const NEVER_FILL = /leave (this |it )?(field |box )?(blank|empty)|do not (fill|enter|type|complete)|don'?t (fill|enter|type)|if you are (a )?human|password|passcode|pass code|verification code|one[- ]time|\botp\b|security (code|answer|question)|\bpin\b|\bssn\b|social security|date of birth|\bdob\b|birth ?date|driver'?s licen[cs]e|passport (number|no)|tax (id|identification)|national (id|insurance)|bank (account|routing|name)|routing number|account number|credit card|card number|\bcvv\b/i;
const NO_AI_CERT = /\b(no|not|without|never|did ?n[o']?t|have ?n[o']?t|has ?n[o']?t|was ?n[o']?t|were ?n[o']?t|free (of|from))\b.{0,60}\b(ai|a\.i\.|artificial intelligence|chat ?gpt|gpt|llms?|generative|gen ?ai|automated tools?|bots?)\b|\b(ai|artificial intelligence|chat ?gpt|llms?|generative ai|gen ?ai)\b.{0,60}\b(was|were|has|have)? ?(not|never) (been )?(used|utili[sz]ed|involved)|\b(solely|entirely|completely|only) (by )?(me|myself)\b|my own (work|words),? without/i;
const OPTIONAL_FLUFF = /^middle name|pronunciation|favou?rite|like (most|best) about|fun fact|hobb(y|ies)|nickname|^\s*if\s*['"“‘]?other\b|^\s*if you (selected|chose|answered|picked)\s*['"“‘]?(other|yes)\b|something you built with/i;   // core.js: optional and personal

// ---------------- the job (company / title, for the rules' "why us" answer) ----------------
function slugCompany() {
  const seg = location.pathname.split('/').filter(Boolean), nice = s => decodeURIComponent(s).replace(/[-_+]+/g, ' ').replace(/\s+\d+$/, '').trim();
  if (/greenhouse\.io$|smartrecruiters\.com$|workable\.com$|rippling\.com$|jobs\.gem\.com$|jobvite\.com$|comeet\.com$/.test(HOST)) {
    const s = seg.find(x => !/^(j|jobs?|embed|job_app|oneclick-ui|company|careers|publication|apply|en|en-us)$/i.test(x));
    return s ? nice(s) : '';
  }
  const sub = HOST.split('.')[0].replace(/^(us|global|uk|eu)?(careers?|jobs|apply|application|hire|recruiting)\d*[-.]?/i, '');
  return /^(www|app|ats|recruiting|careers?|jobs|fa-\w+|workforcenow|myjobs)$/i.test(sub) || /oraclecloud|ultipro|adp|successfactors|sapsf/.test(HOST) ? '' : nice(sub);
}
function jobInfo() {
  const meta = n => { const m = document.querySelector(`meta[property="${n}"], meta[name="${n}"]`); return m ? clean(m.getAttribute('content') || '') : ''; };
  const dt = clean(document.title || '');
  let title = '', company = '';
  const m = dt.match(/^job application for (.+?) at (.+?)$/i) || dt.match(/^(.+?) at (.+?)(?: [-|–] .*)?$/i);
  if (m) { title = m[1]; company = m[2]; }
  const h1 = document.querySelector('h1');
  if (!title) title = (h1 && txt(h1)) || meta('og:title') || dt.split(/\s+[-–|@]\s+/)[0];
  if (!company) company = meta('og:site_name') || slugCompany();
  title = clean(title).slice(0, 120); company = clean(company).replace(/\s*(careers?|jobs|job board|recruiting)$/i, '').slice(0, 60);
  if (/^(apply|application|careers?|jobs?|join us|job details|job description|smartrecruiters|bamboohr|workable|greenhouse|icims)\b/i.test(title) || (company && title.toLowerCase() === company.toLowerCase())) title = '';
  if (/^(smartrecruiters|bamboohr|workable|greenhouse|icims|jobvite|rippling|oracle|adp|ukg|paycor|jazzhr|teamtailor|pinpoint|comeet|dover|gem)$/i.test(company)) company = slugCompany();
  return { title, company, desc: clean(document.body ? document.body.innerText : '').slice(0, 6000) };
}
function setupJob() {
  const info = jobInfo();
  JOB.company = info.company; JOB.title = info.title; JOB.desc = info.desc;
  JOB.bay = /San Francisco|Bay Area|Palo Alto|Menlo Park|Mountain View|Sunnyvale|San Jose|Santa Clara|Redwood City|San Mateo|Oakland|Berkeley|Cupertino|Foster City|Burlingame|Fremont|Milpitas|Emeryville|Los Gatos|Campbell|Pleasanton|San Ramon|Walnut Creek|Hayward/.test(info.desc.slice(0, 1500));
  JOB.okOffice = JOB.bay || (/New York|NYC|Manhattan|Brooklyn/.test(info.desc.slice(0, 1500)) && /hybrid/i.test(info.desc));
  L.setJobRules([]);   // the same per-job rules as an Ashby form with no earlier application on record
  JOB.why = info.company && info.title ? L.whyFor(info.company, info.title, info.desc) : '';
  JOB.plan = {};
}

// ---------------- the fields on the page ----------------
const FIELD_SEL = 'input, select, textarea, [role="combobox"], [role="radio"], [role="checkbox"], button[aria-haspopup="listbox"]';
function kindOf(el) {
  const tag = el.tagName;
  if (tag === 'SELECT') return 'select';
  if (tag === 'TEXTAREA') return 'text';
  if (tag === 'INPUT') {
    const t = (el.getAttribute('type') || 'text').toLowerCase();
    if (t === 'radio') return 'radio';
    if (t === 'checkbox') return 'checkbox';
    if (t === 'file') return 'file';
    if (/^(hidden|submit|button|image|reset|password|search|color|range)$/.test(t)) return '';
    if (el.getAttribute('role') === 'combobox' || el.getAttribute('aria-autocomplete') === 'list' || el.getAttribute('aria-haspopup') === 'listbox') return 'combo';
    if (t === 'date') return 'date';
    return /^(text|email|tel|url|number)$/.test(t) ? 'text' : '';
  }
  const role = el.getAttribute('role');
  if (role === 'combobox' || (tag === 'BUTTON' && el.getAttribute('aria-haspopup') === 'listbox')) return el.querySelector('input') ? '' : 'combo';
  if (role === 'radio') return 'aradio';
  if (role === 'checkbox') return 'acheck';
  return '';
}
function comboBox(el) {   // the visible box around a combobox input (react-select's input is 2 px wide)
  const c = el.parentElement && el.parentElement.closest('[class*="__control"], [class*="-control"], [class*="Select-control"]');
  if (c && c.querySelectorAll('input:not([type="hidden"]), select, textarea').length <= 2) return c;
  let b = el;
  for (let i = 0; i < 5 && b.parentElement; i++) { b = b.parentElement; if (b.getBoundingClientRect().width >= 60) break; }
  return b;
}
function collect(rs) {
  const out = [], seen = new Set();
  for (const el of qsa(FIELD_SEL, rs)) {
    if (seen.has(el)) continue; seen.add(el);
    const k = kindOf(el); if (!k) continue;
    if (el.disabled || el.getAttribute('aria-disabled') === 'true' || offLimits(el)) continue;
    if (k === 'text' && el.readOnly) continue;
    if (k === 'radio' || k === 'checkbox') { const lab = (el.labels && el.labels[0]) || el.closest('label'); if (!shown(el) && !(lab && shown(lab))) continue; }
    else if (k === 'file') { if (!shown(el) && !shown(el.parentElement)) continue; }
    else if (k === 'select') { if (!shown(el) && !(el.parentElement && shown(el.parentElement) && labelOf(el))) continue; }
    else if (k === 'combo') { if (!shown(el) && !shown(comboBox(el))) continue; }
    else if (!shown(el) || !realBox(el)) continue;
    out.push({ el, kind: k });
  }
  return out;
}
const isOn = el => !!(el.checked || el.getAttribute('aria-checked') === 'true');
function optionLabel(inp) {   // the text of one radio / checkbox option
  if (inp.tagName !== 'INPUT') return tidy(labelOf(inp) || strip(inp));
  let t = labelOf(inp);
  if (!t && inp.nextElementSibling && !inp.nextElementSibling.querySelector('input')) t = strip(inp.nextElementSibling);
  if (!t && inp.nextSibling && inp.nextSibling.nodeType === 3) t = clean(inp.nextSibling.nodeValue);
  if (!t && inp.parentElement && inp.parentElement.querySelectorAll('input').length === 1) t = strip(inp.parentElement);
  return tidy(t || inp.value || '');
}
function groups(fields) {   // radios / checkboxes -> one entry per question
  const out = [], byKey = new Map();
  for (const f of fields) {
    if (!/^(radio|checkbox|aradio|acheck)$/.test(f.kind)) continue;
    const el = f.el, nm = el.getAttribute('name') || '';
    const box = el.closest('fieldset, [role="radiogroup"], [role="group"]');
    let k;
    if (nm && /radio/.test(f.kind)) k = [el.form || el.getRootNode(), 'n', nm];
    else if (nm && f.kind === 'checkbox') {
      const scope = el.form || el.getRootNode();
      let same = 0; try { same = scope.querySelectorAll('input[type="checkbox"][name="' + CSS.escape(nm) + '"]').length; } catch (e) {}
      k = same > 1 ? [scope, 'n', nm.replace(/\[\d*\]$/, '')] : (box && /select all|check all|all that apply|which of|hear about|race|ethnic|pronoun|gender|veteran|disab/i.test(groupLabel(el)) ? [box, 'b', ''] : [el, 'e', '']);
    }
    else k = box ? [box, 'b', f.kind] : [el, 'e', ''];
    let byScope = byKey.get(k[0]); if (!byScope) { byScope = new Map(); byKey.set(k[0], byScope); }
    const kk = k[1] + ':' + k[2];
    let g = byScope.get(kk);
    if (!g) { g = { kind: /radio/.test(f.kind) ? 'radio' : 'checkbox', members: [], el }; byScope.set(kk, g); out.push(g); }
    g.members.push(el);
  }
  return out;
}
function groupQuestion(g) {
  const m = g.members, first = m[0];
  const opts = m.map(optionLabel);
  let q = groupLabel(first);
  if (!q && m.length === 1) { q = optionLabel(first); const pre = prevText(first.closest('label') || first); if (pre && pre !== q && pre.length < 400) q = pre; }
  if (!q) {
    let box = first.parentElement;
    while (box && !m.every(x => box.contains(x))) box = box.parentElement;
    for (let p = box, i = 0; p && i < 5 && !q; p = p.parentElement, i++) {
      let t = strip(p); for (const o of opts) if (o) t = t.split(o).join(' ');
      t = clean(t); if (t.length >= 3 && t.length <= 400) q = t; else if (t.length > 400) break;
    }
    if (!q) q = prevText(first.closest('label') || first, false);
  }
  return { q: tidy(q), opts };
}

// ---------------- answering ----------------
const ST = new WeakMap();   // per element: { tries, done }
const st = el => { let s = ST.get(el); if (!s) { s = { tries: 0, done: false }; ST.set(el, s); } return s; };
let filledTotal = 0;
function textAnswer(el, q, req, rep) {
  if (NEVER_FILL.test(q) || NEVER_FILL.test(el.getAttribute('placeholder') || '')) return null;
  if (L.BOT_ASK.test(q)) { rep.ask.push(q + ' (the form asks bots not to answer)'); return null; }
  const isArea = el.tagName === 'TEXTAREA';
  const k = !isArea ? labelKey(q) : '';
  if (k) { const v = profileValue(k); if (v) return v; if (/^(email|phone|street|zip)$/.test(k)) { rep.setup = true; return null; } }
  if (L.AI_TEXT.test(q)) { const v = pickText(q); if (v && L.AI_YES.test(v)) return v; rep.ask.push(q); return null; }
  if (!req && OPTIONAL_FLUFF.test(q)) return null;
  if (/^\s*if you (selected|chose|answered|picked)\s*['"“‘]?other\b/i.test(q)) return 'N/A';
  let v = null;
  if (isArea && /cover letter/i.test(q)) v = L.coverText(JOB.company || 'your team', JOB.title || 'this', JOB.desc);
  if (v == null) { v = pickText(q); if (v === '') return null; }
  if (v == null) { const ph = clean(el.getAttribute('placeholder') || ''); if (ph && !WEAK.test(ph) && ph !== q) { v = pickText(ph); if (v === '') return null; } }
  if (v == null && !isArea) { const k2 = attrKey(el, q); if (k2) v = profileValue(k2) || null; }
  if (v == null && isArea && techOk(q, req)) { v = L.techAnswer(q); if (v) rep.tech.push(q); }
  return v;
}
function techOk(q, req) {   // a technical question with no rule: the applicant's technical answers (core.js / apply.py tech_answer)
  const l = q.toLowerCase();
  if (!req && /\b(link|url|website|github|portfolio|profile|handle|twitter|linkedin)\b|^\s*if (yes|so|applicable|other)\b|anything else|additional (info|comments?|notes?|details)|cover letter|message (to|for)|note (to|for)/.test(l)) return false;
  return !/\b(education|degree|diploma|school|university|college|gpa|graduat\w*|certification|contact|reach you|e-?mail|phone|address|name|pronoun|salary|pay|start|available|availability|zip|postal|references?)\b/.test(l);
}
const DATE_PH = /^(mm|dd|yyyy|m|d)[\/.\- ](mm|dd|yyyy|m|d)[\/.\- ](mm|dd|yyyy|yy)$/i;
function dateFor(q, fmt) {   // core.js answerDate: a start / availability date is two weeks out, a signature date is today
  const plus = /start|available|availability|join|begin|notice/i.test(q) ? 14 : (/today|date of application|signature|sign/i.test(q) ? 0 : null);
  if (plus == null) return null;
  const d = new Date(Date.now() + plus * 86400000), mm = String(d.getMonth() + 1).padStart(2, '0'), dd = String(d.getDate()).padStart(2, '0'), yy = String(d.getFullYear());
  if (fmt === 'iso') return `${yy}-${mm}-${dd}`;
  const f = fmt.toLowerCase(), sep = (f.match(/[\/.\- ]/) || ['/'])[0];
  return f.split(/[\/.\- ]/).map(p => p[0] === 'm' ? mm : p[0] === 'd' ? dd : (p.length === 2 ? yy.slice(2) : yy)).join(sep);
}
async function doText(f, rep) {
  const el = f.el, q = f.q;
  if (clean(el.value)) return 'had';
  const ph = clean(el.getAttribute('placeholder') || '');
  let v = DATE_PH.test(ph) ? dateFor(q, ph) : null;
  if (v == null) v = textAnswer(el, q, f.req, rep);
  if (v == null || v === '') return 'left';
  let val = String(v);
  const type = (el.getAttribute('type') || 'text').toLowerCase();
  if (type === 'number') { const n = val.replace(/[$,\s]/g, ''); if (!/^-?\d+(\.\d+)?$/.test(n)) return 'left'; val = n; }
  if (type === 'email' && !/@/.test(val)) return 'left';
  if (type === 'url' && !/^https?:\/\//i.test(val)) return 'left';
  if (el.maxLength > 0 && val.length > el.maxLength) val = val.slice(0, el.maxLength).trim();
  setText(el, val);
  await sleep(60);
  if (!clean(el.value)) return 'fail';
  rep.filled.push([q, val.slice(0, 70)]);
  return 'filled';
}
async function doDate(f, rep) {
  if (f.el.value) return 'had';
  const v = dateFor(f.q, 'iso'); if (!v) return 'left';
  setText(f.el, v); await sleep(60);
  if (!f.el.value) return 'fail';
  rep.filled.push([f.q, v]); return 'filled';
}
const placeholderOpt = o => !o || !clean(o.text) || /^(-+|—|–|select|choose|please (select|choose)|pick|\(?select|none selected|--)/i.test(clean(o.text)) || (o.value === '' && /select|choose|please/i.test(o.text));
async function doSelect(f, rep) {
  const sel = f.el, q = f.q;
  if (sel.selectedIndex >= 0 && !placeholderOpt(sel.options[sel.selectedIndex]) && !sel.multiple) return 'had';
  if (sel.multiple && [...sel.options].some(o => o.selected)) return 'had';
  const prefs = choicePrefs(sel, q, rep); if (!prefs) return 'left';
  const texts = [...sel.options].map(o => placeholderOpt(o) ? '' : clean(o.text));
  const i = bestIndex(mask(texts, q), prefs);
  if (i < 0) { rep.options[q] = texts.filter(Boolean).slice(0, 12); return 'left'; }
  setSelect(sel, i); await sleep(120);
  if (sel.selectedIndex !== i) return 'fail';
  rep.filled.push([q, texts[i]]);
  return 'filled';
}
function comboValue(el) {   // what a combobox shows as chosen ('' when nothing / a placeholder)
  for (let p = el.parentElement, i = 0; p && i < 5; p = p.parentElement, i++) {
    if (p.querySelectorAll('[role="combobox"]').length > 1) break;
    const sv = p.querySelector('[class*="single-value" i], [class*="singlevalue" i], [class*="multi-value" i], [class*="multivalue" i], [class*="selected-value" i]');
    if (sv && clean(sv.textContent)) return clean(sv.textContent);
  }
  if (el.tagName === 'INPUT') { const v = clean(el.value); return v && !WEAK.test(v) ? v : ''; }
  const t = strip(el) || clean(el.getAttribute('aria-label') || '').replace(clean(labelOf(el) || ''), '');
  return t && !WEAK.test(t) ? t : '';
}
function listFor(el) {
  for (const a of ['aria-controls', 'aria-owns']) { const lb = byId(el, el.getAttribute(a)); if (lb) return lb; }
  return null;
}
function optionsNow(el) {
  const lb = listFor(el);
  let opts = lb ? [...lb.querySelectorAll('[role="option"]')] : [];
  if (!opts.length) opts = qsa('[role="option"], [class*="select__option"]');
  return opts.filter(o => shown(o) && !o.closest('#' + PANEL_ID) && o.getAttribute('aria-disabled') !== 'true' && !o.closest(CAPTCHA_SEL));
}
async function waitOpts(el, ms, ok) {
  const t0 = Date.now(); let o = [];
  while (Date.now() - t0 < ms) { o = optionsNow(el); if (o.length && (!ok || ok(o))) return o; await sleep(150); }
  return o;
}
async function openList(el) {
  try { el.focus({ preventScroll: true }); } catch (e) {}
  const box = comboBox(el);
  const toggle = box && [...box.querySelectorAll('button')].find(b => /toggle|open|show|expand|arrow|caret|chevron|flyout/i.test((b.getAttribute('aria-label') || '') + ' ' + (b.className || '')) && canClick(b));
  if (canClick(el)) L.press(el); else if (toggle) L.press(toggle);
  let o = await waitOpts(el, 1500);
  if (!o.length) { key(el, 'ArrowDown'); o = await waitOpts(el, 1200); }
  return o;
}
function closeList(el) { key(el, 'Escape'); L.leave(el, false); }
async function doCombo(f, rep) {
  const el = f.el, q = f.q;
  if (comboValue(el)) return 'had';
  if (NEVER_FILL.test(q)) return 'left';
  const k = labelKey(q) || attrKey(el, q);
  const loc = (k === 'city' || /^(current |your |home )?location( \(city\))?$|^city\b|where (are you|do you) (currently )?(based|live|located)|location \(city\)|city,? state/i.test(q)) && !/countr|state of|province|relocat|willing|open to|office|prefer|commut/i.test(q);
  const want = loc ? /santa clara.{0,40}(california|\bca\b|united states|usa)/i : null;
  const prefs = loc ? ['Santa Clara, California, United States', 'Santa Clara, CA, USA', 'Santa Clara, California', 'Santa Clara, CA'] : choicePrefs(el, q, rep);
  if (!prefs) return 'left';
  const pickIn = texts => want ? texts.findIndex(t => t && want.test(t)) : bestIndex(texts, prefs);
  let opts = await openList(el);
  let texts = mask(opts.map(o => clean(o.textContent)), q), i = pickIn(texts);
  if (i < 0 && el.tagName === 'INPUT' && !el.readOnly) {   // long or searched lists: type the answer to narrow it
    setText(el, loc ? 'Santa Clara' : prefs[0].slice(0, 30), true);
    opts = await waitOpts(el, loc ? 7000 : 3500, o => pickIn(mask(o.map(x => clean(x.textContent)), q)) >= 0);
    texts = mask(opts.map(o => clean(o.textContent)), q); i = pickIn(texts);
  }
  if (i < 0 || !canClick(opts[i])) {
    if (el.tagName === 'INPUT' && clean(el.value)) setText(el, '', true);
    closeList(el);
    if (opts.length) rep.options[q] = texts.filter(Boolean).slice(0, 12);
    return opts.length ? 'left' : 'fail';
  }
  L.press(opts[i]); await sleep(450);
  if (deepActive() === el) L.leave(el, false);
  await sleep(100);
  const shownNow = comboValue(el);
  if (!shownNow) { closeList(el); return 'fail'; }
  rep.filled.push([q, texts[i].slice(0, 70)]);
  return 'filled';
}
async function tick(el) {
  if (isOn(el)) return true;
  const lab = el.tagName === 'INPUT' ? ((el.labels && el.labels[0]) || el.closest('label')) : null;
  const target = lab && canClick(lab) ? lab : el;
  if (!canClick(target)) return false;
  L.hover(target); target.click(); await sleep(150);
  if (!isOn(el) && target !== el && canClick(el)) { el.click(); await sleep(150); }
  if (isOn(el)) L.leave(el, false);
  return isOn(el);
}
async function doRadios(g, rep) {
  const ins = g.members, q = g.q;
  if (ins.some(isOn)) return 'had';
  if (L.BOT_ASK.test(q)) { rep.ask.push(q + ' (the form asks bots not to answer)'); return 'left'; }
  const opts = g.opts;
  const p1raw = pickRule(q, 'choice');
  if (Array.isArray(p1raw) && p1raw[0] === '__ASK__') { rep.ask.push(q); return 'left'; }
  const cands = [];
  const p1 = choicePrefs(ins[0], q, { ask: [] }); if (p1) cands.push(p1);
  const p2 = pickRule(opts.join(' '), 'choice'); if (Array.isArray(p2) && p2[0] !== '__ASK__') cands.push(p2.filter(x => typeof x === 'string' && x !== '__MULTI__'));
  const texts = mask(opts, q);
  let i = -1;
  for (const prefs of cands) { i = bestIndex(texts, prefs); if (i >= 0) break; }
  if (i < 0 && texts.length >= 2 && texts.every(t => /,\s*[A-Z]{2}\b|,\s*[A-Z][a-z]+|remote|hybrid/i.test(t))) {   // an office list with no question: the Bay Area office
    for (const re of L.BAY_OFFICE) { i = texts.findIndex(t => re.test(t)); if (i >= 0) break; }
  }
  if (i < 0) i = texts.findIndex(t => t && L.OPTION_TRUE.test(t) && !/\b(not|unable|outside|don't|do not)\b/i.test(t));
  if (i < 0) { rep.options[q] = opts.slice(0, 12); return 'left'; }
  if (!await tick(ins[i])) return 'fail';
  rep.filled.push([q, opts[i].slice(0, 70)]);
  return 'filled';
}
async function doChecks(g, rep) {
  const boxes = g.members, q = g.q, labs = g.opts;
  if (boxes.some(isOn)) return 'had';
  if (boxes.length === 1) {   // one box: a consent / acknowledgment (ticked) or a disclosure (never)
    const t = labs[0] || q, both = t + ' ' + q;
    if (NO_AI_CERT.test(both) || L.PERSONAL_CERT.test(both)) { rep.ask.push(t.slice(0, 90)); return 'left'; }
    if (/not a robot|i am (a )?human|captcha/i.test(both)) return 'left';
    if (!g.req && /marketing|newsletter|future (job )?opportunit|talent (community|pool|network)|keep me|stay in touch|text message|\bsms\b|job alerts|subscribe|promotional|similar (jobs|roles|positions)/i.test(both)) return 'left';
    if (/i understand.{0,100}((5|five) days?|fully on-?site|100% (in[- ]?office|on-?site)|every (week)?day in (the )?office)/i.test(both)) return 'left';
    if (L.DISCLOSE.test(t) && !L.ACK.test(q)) return 'left';
    let ok = L.ACK.test(t) || L.ACK.test(q);
    if (!ok && q && q !== t) { const p = choicePrefs(boxes[0], q, { ask: [] }); ok = !!(p && bestIndex([t], p) === 0); }
    if (!ok) return 'left';
    if (!await tick(boxes[0])) return 'fail';
    rep.filled.push([q || t, 'checked']); return 'filled';
  }
  if (NO_AI_CERT.test(q) || L.PERSONAL_CERT.test(q)) { rep.ask.push(q.slice(0, 90)); return 'left'; }
  const isSrc = L.HEAR_Q.test(q);
  let members = boxes.map((b, i) => [b, labs[i]]);
  if (isSrc) members = members.filter(m => !L.HEAR_BAD.test(m[1]));
  const raw = pickRule(q, 'choice');
  if (Array.isArray(raw) && raw[0] === '__ASK__') { rep.ask.push(q); return 'left'; }
  if (Array.isArray(raw) && raw[0] === '__MULTI__') {   // a rule listing every option true for the applicant: tick each one it names
    const ticked = [];
    for (const pv of raw.slice(1)) { const i = bestIndex(members.map(m => m[1]), [pv]); if (i >= 0 && !ticked.includes(members[i][1]) && await tick(members[i][0])) ticked.push(members[i][1]); }
    if (ticked.length) { rep.filled.push([q, ticked.join(', ').slice(0, 70)]); return 'filled'; }
    rep.options[q] = labs.slice(0, 12); return 'left';
  }
  if (/select all that apply|check all that apply|environments|best describes?|which (of the following )?(technolog|tools|languages|frameworks|services|platforms|types of|kinds of|practices|people-leadership|leadership)/i.test(q) && !/hear|learn|source|ethnic|race|gender|disab|veteran|pronoun|sanction|citizenship|countr/i.test(q)) {
    const ticked = [];
    for (const [b, l] of members) if ((L.ENV_TRUE.test(l) || L.STACK_TRUE.test(l)) && !/none of the above|not applicable|n\/a|prefer not|^other\b/i.test(l)) { if (await tick(b)) ticked.push(l.slice(0, 30)); }
    if (ticked.length) { rep.filled.push([q, ticked.join(', ').slice(0, 70)]); return 'filled'; }
  }
  let want = choicePrefs(boxes[0], q, { ask: [] }) || (isSrc ? ['LinkedIn', 'Job Board', 'Online Job Board', 'Social Media', 'Company Website', 'Careers page', 'Other'] : null);
  if (!want) { rep.options[q] = labs.slice(0, 12); return 'left'; }
  const texts = mask(members.map(m => m[1]), q);
  let i = bestIndex(texts, want);
  if (i < 0 && isSrc) i = members.findIndex(m => /^other\b/i.test(m[1]));
  if (i < 0) { rep.options[q] = labs.slice(0, 12); return 'left'; }
  if (!await tick(members[i][0])) return 'fail';
  rep.filled.push([q, members[i][1].slice(0, 70)]);
  return 'filled';
}
function fileShown(el) {   // the upload area already names a file
  let p = el.parentElement;
  for (let i = 0; i < 4 && p; i++, p = p.parentElement) {
    if (p.querySelectorAll('input[type="file"]').length > 1) break;
    const t = p.innerText || '';
    if (/[\w)\]-]\.(pdf|docx?|rtf|txt|odt)\b/i.test(t) && !/no file (selected|chosen)/i.test(t)) return true;
  }
  return false;
}
async function doFile(f, rep) {
  const el = f.el;
  if ((el.files && el.files.length) || fileShown(el)) return 'had';
  const s = f.q + ' ' + (el.id || '') + ' ' + (el.getAttribute('name') || '') + ' ' + (el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('data-testid') || '');
  const cover = /cover/i.test(s), resume = !cover && /resume|r[ée]sum[ée]|\bcv\b|curriculum/i.test(s);
  if (!cover && !resume) return 'left';
  const file = cover ? S.get('cover') : L.resumeFor(JOB.title);
  if (!file) { if (resume) rep.resume = 'not set up (open Setup in this panel and choose your resume once)'; return 'left'; }
  try {
    const dt = new DataTransfer(); dt.items.add(L.b64ToFile(file));
    el.files = dt.files;
    el.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
    el.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
  } catch (e) { return 'fail'; }
  await sleep(1500);
  if (resume) rep.resume = file.name;
  rep.filled.push([cover ? 'Cover letter' : 'Resume', file.name]);
  return 'filled';
}

// ---------------- one pass over the page ----------------
let busy = false, again = false, timer = 0, lastKey = 0, lastRep = null, runs = 0, lastSig = '';
const allLeft = new Map(), allAsk = new Set(), allFilled = [];
function looksLikeForm(fields) {
  let score = 0;
  for (const f of fields) {
    if (f.kind === 'file') score += 2;
    else if (/^(text|combo)$/.test(f.kind)) { const q = f.q != null ? f.q : (f.q = questionOf(f.el)); score += /^(first|last|name|email|phone)$/.test(labelKey(q) || attrKey(f.el, q)) ? 2 : 0.5; }
    else score += 0.25;
  }
  return score >= 3;
}
async function fill(opts = {}) {
  if (!pageOk()) return null;
  if (busy) { again = true; return null; }
  busy = true;
  const manual = !!opts.manual;
  const rep = { filled: [], ask: [], left: [], tech: [], options: {}, resume: '', setup: false, at: new Date().toISOString() };
  try {
    const rs = roots();
    let fields = collect(rs);
    if (!looksLikeForm(fields)) { busy = false; if (manual) status('No application form found on this page yet.'); return null; }
    setupJob();
    if (manual) for (const f of fields) { const s = st(f.el); s.done = false; s.tries = 0; }
    const active = deepActive();
    const skip = el => { const s = st(el); return !manual && (s.done || s.tries >= 2 || el === active); };
    const record = (el, r, q, req) => {
      const s = st(el); s.tries++;
      if (r === 'filled') { s.done = true; filledTotal++; allLeft.delete(q); }
      else if (r === 'had' || r === 'left') { s.done = true; if (r === 'left' && req && q) allLeft.set(q, el); else if (r === 'had') allLeft.delete(q); }
      else if (req && q) allLeft.set(q, el);
    };
    // 1) resume / cover letter first: a site that reads the resume fills fields from it
    let attached = false;
    for (const f of fields.filter(x => x.kind === 'file')) {
      if (skip(f.el)) continue;
      f.q = f.q || questionOf(f.el);
      const r = await doFile(f, rep); record(f.el, r, f.q, requiredOf(f.el));
      if (r === 'filled') attached = true;
    }
    if (attached) { await sleep(2500); fields = collect(roots()); }
    // 2) every other question, in page order
    for (const f of fields) {
      if (!/^(text|date|select|combo)$/.test(f.kind) || skip(f.el)) continue;
      if (!f.el.isConnected) continue;
      f.q = f.q != null ? f.q : questionOf(f.el); f.req = requiredOf(f.el);
      let r = 'left';
      try {
        if (f.kind === 'text') r = await doText(f, rep);
        else if (f.kind === 'date') r = await doDate(f, rep);
        else if (f.kind === 'select') r = await doSelect(f, rep);
        else r = await doCombo(f, rep);
      } catch (e) { r = 'fail'; }
      record(f.el, r, f.q, f.req);
    }
    for (const g of groups(collect(roots()))) {
      if (skip(g.members[0])) continue;
      const gq = groupQuestion(g); g.q = gq.q; g.opts = gq.opts; g.req = g.members.some(m => requiredOf(m, g.q));
      let r = 'left';
      try { r = g.kind === 'radio' ? await doRadios(g, rep) : await doChecks(g, rep); } catch (e) { r = 'fail'; }
      for (const m of g.members) record(m, r, '', false);
      if (r !== 'filled' && r !== 'had' && g.req && g.q) allLeft.set(g.q, g.members[0]); else allLeft.delete(g.q);
    }
    for (const q of rep.ask) allAsk.add(q.slice(0, 90));
    for (const x of rep.filled) allFilled.push(x);
    lastRep = rep; runs++;
    report(rep);
    return rep;
  } finally {
    busy = false;
    if (again) { again = false; schedule(1500); }
  }
}

// ---------------- panel ----------------
function el(tag, css, text) { const e = document.createElement(tag); if (css) e.style.cssText = css; if (text != null) e.textContent = text; return e; }
let P_ = null;
function panel() {
  if (P_ && P_.isConnected) return P_;
  const p = el('div', 'all:initial;position:fixed;right:14px;bottom:14px;z-index:2147483646;width:300px;max-height:60vh;overflow:auto;background:#0f172a;color:#e2e8f0;font:12.5px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.35);padding:10px 12px;box-sizing:border-box');
  p.id = PANEL_ID;
  const head = el('div', 'display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:4px');
  head.appendChild(el('b', 'font:600 13px system-ui,sans-serif;color:#e2e8f0', 'Job form filler'));
  const right = el('span', 'display:flex;gap:6px;align-items:center');
  right.appendChild(el('span', 'opacity:.6;font-size:10.5px', 'v' + L.VERSION));
  const min = el('button', 'all:initial;cursor:pointer;color:#e2e8f0;font:700 14px system-ui;padding:0 4px', '–'); min.type = 'button'; min.title = 'Minimize';
  right.appendChild(min); head.appendChild(right); p.appendChild(head);
  const body = el('div', ''); body.id = PANEL_ID + '-body';
  const stx = el('div', 'white-space:pre-wrap;word-break:break-word'); stx.id = PANEL_ID + '-status'; body.appendChild(stx);
  const btns = el('div', 'display:flex;gap:6px;flex-wrap:wrap;margin-top:8px');
  const bstyle = p2 => `all:initial;cursor:pointer;padding:5px 10px;border-radius:7px;font:600 12px system-ui,sans-serif;${p2 ? 'background:#22c55e;color:#052e16' : 'background:#334155;color:#e2e8f0'}`;
  const again_ = el('button', bstyle(true), 'Fill again'); again_.type = 'button'; again_.onclick = () => fill({ manual: true });
  const setupB = el('button', bstyle(false), 'Setup'); setupB.type = 'button';
  btns.appendChild(again_); btns.appendChild(setupB); body.appendChild(btns);
  const setup = el('div', 'display:none;margin-top:8px;gap:6px;flex-direction:column'); setup.id = PANEL_ID + '-setup';
  const m = L.me() || {};
  const inp = (label, k, type) => {
    const w = el('label', 'display:block;color:#e2e8f0;font:12px system-ui,sans-serif;margin-top:4px', label);
    const i = el('input', 'all:initial;display:block;box-sizing:border-box;width:100%;background:#fff;color:#0f172a;border-radius:5px;padding:3px 6px;font:12px system-ui,sans-serif;margin-top:2px');
    i.type = type || 'text'; if (k) i.value = m[k] || ''; i.dataset.k = k || ''; w.appendChild(i); setup.appendChild(w); return i;
  };
  const ie = inp('Email', 'email'), ip = inp('Phone', 'phone'), is = inp('Street address (optional)', 'street'), iz = inp('ZIP code (optional)', 'zip');
  const fr = inp('Resume (architect / engineer roles)', '', 'file'), fx = inp('Executive resume (CTO / VP / Head / Director)', '', 'file'), fc = inp('Cover letter file (optional)', '', 'file');
  [fr, fx, fc].forEach(x => { x.accept = '.pdf,.doc,.docx'; x.style.background = 'transparent'; x.style.color = '#e2e8f0'; });
  const save = el('button', bstyle(true) + ';margin-top:8px', 'Save'); save.type = 'button';
  const saved = el('div', 'opacity:.75;margin-top:4px;white-space:pre-wrap');
  const files = () => [['resume_main', 'Resume'], ['resume_exec', 'Executive resume'], ['cover', 'Cover letter']].map(([k, n]) => `${n}: ${(S.get(k) || {}).name || '-'}`).join('\n');
  saved.textContent = files();
  const readFile = i => new Promise(res => { const f = i.files && i.files[0]; if (!f) return res(null); const r = new FileReader(); r.onload = () => res({ name: f.name, type: f.type || 'application/pdf', b64: String(r.result).split(',')[1] }); r.readAsDataURL(f); });
  save.onclick = async () => {
    S.set('me', Object.assign({}, L.me() || {}, { email: ie.value.trim(), phone: ip.value.trim(), street: is.value.trim(), zip: iz.value.trim() }));
    for (const [i, k] of [[fr, 'resume_main'], [fx, 'resume_exec'], [fc, 'cover']]) { const f = await readFile(i); if (f && !S.set(k, f)) alert('Could not save ' + f.name + ' (too large for this browser storage).'); }
    saved.textContent = 'Saved.\n' + files();
  };
  setup.appendChild(save); setup.appendChild(saved); body.appendChild(setup);
  setupB.onclick = () => { setup.style.display = setup.style.display === 'none' ? 'flex' : 'none'; };
  p.appendChild(body);
  const setMin = on => { body.style.display = on ? 'none' : 'block'; p.style.width = on ? 'auto' : '300px'; min.textContent = on ? '+' : '–'; min.title = on ? 'Show' : 'Minimize'; S.set('gpanel_min', !!on); };
  min.onclick = () => setMin(body.style.display !== 'none');
  (document.body || document.documentElement).appendChild(p);
  setMin(!!S.get('gpanel_min', false));
  if (!(m.email && (S.get('resume_main') || S.get('resume_exec')))) setup.style.display = 'flex';
  P_ = p;
  return p;
}
function status(t) { try { panel().querySelector('#' + PANEL_ID + '-status').textContent = t; } catch (e) {} }
function stillEmpty() {   // required questions on the page that are still unanswered
  const out = [];
  for (const [q, e] of allLeft) {
    if (!e.isConnected || !(shown(e) || shown(e.parentElement))) { allLeft.delete(q); continue; }
    const answered = e.tagName === 'SELECT' ? (e.selectedIndex >= 0 && !placeholderOpt(e.options[e.selectedIndex])) : /radio|checkbox/.test(e.type || '') ? !!(e.name && [...(e.form || document).querySelectorAll('input[name="' + CSS.escape(e.name) + '"]')].some(isOn)) || isOn(e) : !!comboValue(e) || !!clean(e.value || '');
    if (answered) { allLeft.delete(q); continue; }
    out.push(q);
  }
  return out;
}
function report(rep) {
  const left = stillEmpty();
  const lines = [`Filled ${filledTotal} field${filledTotal === 1 ? '' : 's'} - review, answer the rest, then submit.`];
  if (rep.resume) lines.push('Resume: ' + rep.resume);
  if (rep.setup) lines.push('Email / phone not set up yet: open Setup below.');
  if (allAsk.size) lines.push('For you: ' + [...allAsk].slice(0, 4).map(x => x.slice(0, 70)).join('; '));
  if (left.length) lines.push('Still empty (required): ' + left.slice(0, 6).map(x => x.slice(0, 60)).join('; ') + (left.length > 6 ? ` (+${left.length - 6} more)` : ''));
  lines.push('Never submitted for you: CAPTCHA, sign-in and Submit stay with you.');
  status(lines.join('\n'));
  try { window.__AKF_GLAST = { filled: allFilled.slice(), filledTotal, left, ask: [...allAsk], tech: rep.tech, options: rep.options, resume: rep.resume, runs, version: L.VERSION }; } catch (e) {}
}

// ---------------- watching the page (multi-step forms, late fields, single-page apps) ----------------
let dueAt = 0;
function schedule(ms) {
  ms = ms || 1200;
  if (timer && dueAt <= Date.now() + ms) return;   // a run is already due sooner
  clearTimeout(timer); dueAt = Date.now() + ms;
  timer = setTimeout(async () => {
    timer = 0;
    const a = deepActive();
    const typing = Date.now() - lastKey < 1500 || (a && a !== document.body && a.matches && a.matches('input:not([type="checkbox"]):not([type="radio"]):not([type="file"]), textarea, [contenteditable="true"]') && !(P_ && P_.contains(a)) && !st(a).done);
    if (typing) return schedule(2000);   // the applicant is typing: wait
    await fill({ auto: true });
  }, ms);
}
function sig() { try { return location.href + '|' + collect(roots()).length; } catch (e) { return location.href; } }
function start() {
  window.addEventListener('keydown', e => { if (e.isTrusted) lastKey = Date.now(); }, true);
  const auto = L.HAS_GM ? S.get('autofill', true) !== false : true;
  if (window.__AKF_LOADED) window.__AKF_LOADED.run = () => fill({ manual: true });
  window.__AKF_GENERIC = { fill, last: () => lastRep, version: L.VERSION };
  if (!auto) {   // the applicant switched automatic filling off (Setup on an Ashby page): fill on request only
    const t = setInterval(() => { if (pageOk() && looksLikeForm(collect(roots()))) { clearInterval(t); status('Automatic filling is off. Click "Fill again" to fill this form.'); } }, 3000);
    return;
  }
  schedule(1200);
  const mo = new MutationObserver(muts => {   // new or newly shown questions -> fill them (our own panel does not count)
    for (const m of muts) {
      const t = m.target;
      if (!t || t.nodeType !== 1 || (t.closest && t.closest('#' + PANEL_ID))) continue;
      if (m.type === 'childList') { for (const n of m.addedNodes) if (n.nodeType === 1 && (n.matches(FIELD_SEL) || n.querySelector(FIELD_SEL))) { schedule(); return; } }
      else if (t.matches(FIELD_SEL) || t.querySelector('input, select, textarea')) { schedule(); return; }
    }
  });
  try { mo.observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['hidden', 'aria-hidden', 'style', 'class'] }); } catch (e) {}
  setInterval(() => { const s = sig(); if (s !== lastSig) { lastSig = s; schedule(600); } }, 2500);   // changes inside shadow roots / route changes
}
start();
}
