"""rows.py: the applicant-file row store (rebuilt 2026-11-28 after the container reset).

rows.json (repository, no personal data) holds every role routed to the applicant's files:
  route "one_click" (Ashby / Lever), "apply_myself" (everything without a bot), or "bot_hold" (a bot lane that
  cannot submit yet; listed in the Apply Myself file under "Waiting for a bot" so nothing goes stale unseen).
Each row: id, route, ats, company, title, url, apply_url, note, added (UTC ISO), sent (list of UTC ISO stamps),
optional dropped (reason: the row is left out of every later file).

  rows.py add <rows.json-like file>   add rows (list of dicts with route / company / title / url ...); duplicates skipped
  rows.py status                      unsent counts per route
  rows.py build new|all [days=7]      write ONE_CLICK_<stamp>.html and APPLY_MYSELF_<stamp>.html in the scratchpad:
                                      new = rows never sent (the 5+ rows send); all = rows added in the last <days>
                                      days (the 9 PM send). Rows whose role is already in the Gmail ledger are left out.
                                      Prints the paths and the row ids written to <scratchpad>/last_build.json.
  rows.py mark-sent                   stamp the rows of the last build as sent (run after SendUserFile succeeds)

The Apply Myself file stays contact-free: rows carry only public posting facts."""
import hashlib, html, json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
SC = "/tmp/claude-0/-home-user-goExchange/8d20ffb7-2488-5f8f-a666-35334b9e3ba6/scratchpad"
ROWS = os.path.join(HERE, "rows.json"); LAST = os.path.join(SC, "last_build.json")
NOW = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def load():
    try: return json.load(open(ROWS))
    except Exception: return []
def save(r): json.dump(r, open(ROWS, "w"), indent=1, ensure_ascii=True)
def rid(x): return hashlib.sha1(((x.get("url") or "") + "|" + (x.get("company") or "") + "|" + (x.get("title") or "")).lower().encode()).hexdigest()[:12]

def applied(x):
    import gates as g
    return any(g.same_role(x.get("title"), r) for r in g.prior(x.get("company"))["roles"])

CSS = ("body{font:15px/1.45 system-ui,sans-serif;margin:16px;color:#111;background:#fff}table{border-collapse:collapse;width:100%}"
       "td,th{border:1px solid #ccc;padding:8px;vertical-align:top;text-align:left}th{background:#f3f3f3}a{color:#0b57d0}"
       "p.note{color:#444}h2{margin-top:28px}@media (max-width:600px){table,tbody,tr,td{display:block;width:100%;box-sizing:border-box}tr{border:1px solid #ccc;border-radius:8px;margin:0 0 12px;padding:8px 10px}thead{display:none}td{border:none;padding:3px 0}td:first-child{display:none}}@media (prefers-color-scheme:dark){body{background:#111;color:#eee}th{background:#222}td,th{border-color:#444}a{color:#8ab4f8}p.note{color:#bbb}}")
def page(title, intro, sections):
    e = html.escape
    out = [f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title><style>{CSS}</style></head><body>',
           f"<h1>{e(title)}</h1><p class=\"note\">{e(intro)}</p>"]
    for head, rows, link_text in sections:
        if not rows: continue
        out.append(f"<h2>{e(head)} ({len(rows)})</h2><table><thead><tr><th>#</th><th>Role</th><th>Link</th><th>Notes</th></tr></thead><tbody>")
        for i, x in enumerate(rows, 1):
            u = x.get("apply_url") or x.get("url") or ""
            a = f'<a href="{e(u)}" target="_blank" rel="noopener">{e(link_text)}</a>' if u else "-"
            out.append(f"<tr><td>{i}</td><td><b>{e(x['company'])}</b><br>{e(x['title'])}</td><td>{a}</td><td>{e(x.get('note') or '')}</td></tr>")
        out.append("</tbody></table>")
    out.append("</body></html>")
    return "\n".join(out)

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    R = load()
    if cmd == "add":
        new = json.load(open(sys.argv[2])); ids = {x["id"] for x in R}; n = 0
        for x in new:
            x = dict(x); x["id"] = x.get("id") or rid(x); x.setdefault("added", NOW); x.setdefault("sent", []); x.setdefault("ats", ""); x.setdefault("apply_url", "")
            if x["route"] not in ("one_click", "apply_myself", "bot_hold"): raise SystemExit(f"bad route {x['route']}")
            if x["id"] in ids: continue
            R.append(x); ids.add(x["id"]); n += 1
        save(R); print(f"added {n} (store {len(R)})")
    elif cmd == "status":
        for rt in ("one_click", "apply_myself", "bot_hold"):
            live = [x for x in R if x["route"] == rt and not x.get("dropped")]
            print(f"{rt}: {sum(1 for x in live if not x['sent'])} unsent / {len(live)} total ({sum(1 for x in R if x['route'] == rt and x.get('dropped'))} dropped)")
    elif cmd == "build":
        mode = sys.argv[2] if len(sys.argv) > 2 else "new"; days = float(sys.argv[3]) if len(sys.argv) > 3 else 7
        cut = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * 86400))
        pick = [x for x in R if not x.get("dropped") and (not x["sent"] if mode == "new" else x["added"] >= cut) and not applied(x)]
        stamp = time.strftime("%Y-%m-%d_%H%MZ", time.gmtime()); paths = []
        oc = [x for x in pick if x["route"] == "one_click"]; am = [x for x in pick if x["route"] == "apply_myself"]; bh = [x for x in pick if x["route"] == "bot_hold"]
        what = "New roles since the last file" if mode == "new" else f"Open roles from the last {days:g} days"
        if oc:
            p = os.path.join(SC, f"ONE_CLICK_{stamp}.html")
            open(p, "w").write(page(f"One-click roles, {stamp[:10]}", what + " (Ashby / Lever: open the application and submit).", [("One-click", oc, "Open the application")])); paths.append(p)
        if am or bh:
            p = os.path.join(SC, f"APPLY_MYSELF_{stamp}.html")
            open(p, "w").write(page(f"Apply Myself, {stamp[:10]}", what + ". Roles waiting for a bot are listed last; the bots resume once the private files are back.",
                                    [("Apply myself", am, "Open the posting"), ("Waiting for a bot (or apply yourself)", bh, "Open the posting")])); paths.append(p)
        json.dump({"at": NOW, "mode": mode, "ids": [x["id"] for x in pick], "paths": paths}, open(LAST, "w"))
        print(f"build {mode}: one_click {len(oc)} | apply_myself {len(am)} | bot_hold {len(bh)}")
        for p in paths: print(p)
    elif cmd == "mark-sent":
        b = json.load(open(LAST)); ids = set(b["ids"]); n = 0
        for x in R:
            if x["id"] in ids: x["sent"].append(NOW); n += 1
        save(R); print(f"marked {n} rows sent ({b['mode']} build of {b['at']})")
    else: raise SystemExit(__doc__)

if __name__ == "__main__": main()
