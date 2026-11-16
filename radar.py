#!/usr/bin/env python3
"""
MyStop: pulls every open competition from Unstop, reads and scores each one
(model.py + config.json), tracks changes between runs, checks your flagship watchlist,
and writes a self-contained dashboard.html.

    python radar.py --serve      # recommended: http://localhost:8000, saves your tracker to my/state.json
    python radar.py              # fetch + rebuild dashboard.html once
    python radar.py --offline    # rebuild from cache only (after editing config.json)
    python radar.py --open       # rebuild, then open dashboard.html

Needs only Python 3.8+ (standard library, nothing to install, no API keys).
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from model import IST, Model, parse_dt, text_of

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
DETAIL = CACHE / "detail"
EXTRA = CACHE / "extra"
MY = ROOT / "my"
STATE = MY / "state.json"
API = "https://unstop.com/api/public"
LIST_URL = API + "/opportunity/search-result?opportunity=competitions&oppstatus=open&per_page={pp}&page={p}"
SEARCH_URL = API + "/opportunity/search-result?opportunity=competitions&per_page=30&searchTerm={q}"
DETAIL_URL = API + "/competition/{id}"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
RUN_LOCK = threading.Lock()


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def now_ist():
    return dt.datetime.now(IST)


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text("utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, obj, **kw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, **kw), "utf-8")
    tmp.replace(path)


# ----------------------------------------------------------------------------
# Fetch
# ----------------------------------------------------------------------------
def http_get(url, tries=4, accept="application/json", timeout=40):
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - retry on anything
            err = e
            time.sleep(1.5 * (i + 1))
    raise err


def http_json(url, tries=4):
    return json.loads(http_get(url, tries))


def fetch_detail(cid):
    return (http_json(DETAIL_URL.format(id=cid)).get("data") or {}).get("competition")


def fetch_all(cfg):
    """Returns (list_items, details_by_id). Details are cached per id + updated_at."""
    DETAIL.mkdir(parents=True, exist_ok=True)
    fc = cfg.get("fetch", {})
    items, page = {}, 1
    while True:
        d = http_json(LIST_URL.format(pp=fc.get("per_page", 100), p=page))["data"]
        for it in d["data"]:
            items[it["id"]] = it
        log(f"  list page {page}/{d['last_page']}  ({len(items)} comps)")
        if page >= d["last_page"]:
            break
        page += 1
        time.sleep(fc.get("pause", 0.25))
    items = list(items.values())

    def one(it):
        f = DETAIL / f"{it['id']}.json"
        old = read_json(f, None)
        if old and old.get("_stamp") == it.get("updated_at"):
            return it["id"], old.get("competition"), False
        try:
            comp = fetch_detail(it["id"])
        except Exception as e:  # noqa: BLE001
            log(f"  ! detail {it['id']} failed: {e}")
            return it["id"], (old or {}).get("competition"), True
        write_json(f, {"_stamp": it.get("updated_at"), "competition": comp})
        return it["id"], comp, True

    details, fetched = {}, 0
    with cf.ThreadPoolExecutor(fc.get("workers", 6)) as ex:
        for cid, comp, was_fetched in ex.map(one, items):
            details[cid] = comp
            fetched += was_fetched
    log(f"  details: {fetched} fetched, {len(items) - fetched} from cache")
    live = {str(it["id"]) for it in items}
    for f in DETAIL.glob("*.json"):
        if f.stem not in live:
            f.unlink()
    write_json(CACHE / "list.json", items)
    return items, details


def load_cached():
    items = read_json(CACHE / "list.json", [])
    details = {it["id"]: (read_json(DETAIL / f"{it['id']}.json", {}) or {}).get("competition") for it in items}
    return items, details


def get_extra(cid, offline=False):
    """Detail for a comp that is not in the open list any more (tracked comps, past flagship editions)."""
    f = EXTRA / f"{cid}.json"
    if not offline:
        try:
            comp = fetch_detail(cid)
            if comp:
                write_json(f, comp)
                return comp
        except Exception as e:  # noqa: BLE001
            log(f"  ! could not fetch comp {cid}: {e}")
    return read_json(f, None)


def comp_id_from(s):
    """'https://unstop.com/competitions/some-name-1764253' or '1764253' -> 1764253"""
    m = re.findall(r"(\d{5,9})(?=$|[/?#\s])", str(s).strip())
    return int(m[-1]) if m else None


# ----------------------------------------------------------------------------
# History -> events (new listings, deadline extensions, round date changes)
# ----------------------------------------------------------------------------
def _snap(r):
    return {"t": r["t"], "org": r["org"], "url": r["url"], "dl": r["dl"], "prize": r["prize"],
            "rd": [[x["t"], x["s"], x["e"]] for x in r["rd"]]}


def _moved(a, b, hours=1):
    da, db = parse_dt(a), parse_dt(b)
    if not da or not db:
        return False
    return abs((db - da).total_seconds()) >= hours * 3600


def update_history(recs, now, cfg):
    hist = read_json(CACHE / "history.json", {})
    events = read_json(CACHE / "events.json", [])
    first_run = not hist
    stamp = now.isoformat()
    new_days = max(14, cfg.get("new_within_days", 3))
    added = []

    def ev(kind, r, **kw):
        added.append({"k": kind, "id": r["id"], "t": r["t"], "org": r["org"], "url": r["url"], "ts": stamp, **kw})

    for r in recs:
        key, cur = str(r["id"]), _snap(r)
        old = hist.get(key)
        if old is None:
            listed = parse_dt(r.get("listed"))
            if not r.get("closed"):
                if first_run:
                    if listed and (now - listed).days <= new_days:
                        ev("new", r, ts=listed.isoformat())
                else:
                    ev("new", r, ts=(listed.isoformat() if listed and (now - listed).days <= 2 else stamp))
        else:
            if old.get("dl") and cur["dl"] and _moved(old["dl"], cur["dl"]):
                ev("deadline", r, old=old["dl"], new=cur["dl"])
            ord_, crd = old.get("rd") or [], cur["rd"]
            if len(ord_) == len(crd):
                for i, (o, c) in enumerate(zip(ord_, crd)):
                    if _moved(o[1], c[1], 6) or _moved(o[2], c[2], 6):
                        ev("round", r, ri=i, rt=c[0], old=[o[1], o[2]], new=[c[1], c[2]])
            elif ord_ or crd:
                ev("rounds", r, old=len(ord_), new=len(crd))
            if old.get("prize") and cur["prize"] and abs(cur["prize"] - old["prize"]) >= 0.1 * old["prize"]:
                ev("prize", r, old=old["prize"], new=cur["prize"])
        cur["first"] = (old or {}).get("first", stamp)
        cur["seen"] = stamp
        hist[key] = cur

    cutoff = (now - dt.timedelta(days=90)).isoformat()
    hist = {k: v for k, v in hist.items() if v.get("seen", stamp) >= cutoff}
    write_json(CACHE / "history.json", hist)
    return events, added


def save_events(events, added, now):
    seen = {(e["k"], e.get("id"), e.get("name"), json.dumps(e.get("new"), sort_keys=True), e.get("ri")) for e in events}
    for e in added:
        key = (e["k"], e.get("id"), e.get("name"), json.dumps(e.get("new"), sort_keys=True), e.get("ri"))
        if key not in seen:
            events.append(e)
            seen.add(key)
    cutoff = (now - dt.timedelta(days=45)).isoformat()
    events = sorted((e for e in events if e["ts"] >= cutoff), key=lambda e: e["ts"], reverse=True)
    write_json(CACHE / "events.json", events)
    return events


# ----------------------------------------------------------------------------
# Flagship watchlist
# ----------------------------------------------------------------------------
PAGE_OPEN = r"register now|apply now|registrations? (are |is )?(now )?(open|live)|applications? (are |is )?(now )?(open|live)|submit your (application|entry|idea)|enrol+ now|sign up now"


def _words_regex(name):
    words = [re.escape(w) for w in re.findall(r"[A-Za-z0-9&']+", name) if len(w) > 1]
    return "".join(f"(?=.*\\b{w})" for w in words) or re.escape(name)


def _edition(x):
    rr = x.get("regnRequirements") or {}
    return {"id": x["id"], "t": (x.get("title") or "").strip(), "org": (x.get("organisation") or {}).get("name") or "",
            "url": x.get("seo_url") or "https://unstop.com/" + (x.get("public_url") or ""),
            "rs": rr.get("start_regn_dt"), "re": rr.get("end_regn_dt"), "st": rr.get("reg_status")}


def check_watchlist(cfg, state, now, offline, open_items=()):
    entries = list(read_json(ROOT / "watchlist.json", {}).get("comps", []))
    names = {e["name"].lower() for e in entries}
    for e in (state.get("watch") or []):
        if e.get("name") and e["name"].lower() not in names:
            entries.append({**e, "mine": True})
    cache = read_json(CACHE / "watch.json", {})
    wc = cfg.get("watch", {})
    out, added, extra_ids = [], [], []
    stamp = now.isoformat()

    for e in entries:
        name = e["name"]
        prev = cache.get(name, {})
        fresh = prev.get("checked") and (now - parse_dt(prev["checked"])).total_seconds() < wc.get("recheck_hours", 6) * 3600
        res = dict(prev)
        title_re = re.compile(e.get("match") or _words_regex(name), re.I)
        org_re = re.compile(e["org"], re.I) if e.get("org") else None

        def hit(x):
            return bool(title_re.search(x.get("title") or "")) and (
                not org_re or bool(org_re.search((x.get("organisation") or {}).get("name") or "")))

        if not offline and not fresh:
            res = {"checked": stamp, "editions": prev.get("editions", []), "page": prev.get("page")}
            # 1. Unstop search: every edition, open or closed
            try:
                data = http_json(SEARCH_URL.format(q=urllib.parse.quote(e.get("search") or name)), tries=2)["data"]["data"]
                res["editions"] = [_edition(x) for x in data if hit(x)]
                res["unstop_ok"] = True
            except Exception as ex:  # noqa: BLE001
                res["unstop_ok"] = False
                log(f"  ! watchlist search failed for {name}: {ex}")
            # 2. official page (optional)
            if e.get("url"):
                page = {"ok": False, "open": None, "hash": (prev.get("page") or {}).get("hash"), "changed": (prev.get("page") or {}).get("changed")}
                try:
                    raw = http_get(e["url"], tries=2, accept="text/html,*/*", timeout=25).decode("utf-8", "replace")
                    txt = text_of(re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw))
                    page["ok"] = len(txt) > 200
                    if page["ok"]:
                        m = re.search(e.get("open_regex") or PAGE_OPEN, txt, re.I)
                        page["open"] = txt[max(0, m.start() - 60): m.end() + 60].strip() if m else False
                        h = hashlib.sha1(re.sub(r"[\d\s]+", " ", txt).encode()).hexdigest()[:16]
                        if page["hash"] and h != page["hash"]:
                            page["changed"] = stamp
                            added.append({"k": "watch", "name": name, "url": e["url"], "ts": stamp, "sub": "page",
                                          "msg": "The official page changed since the last check."})
                        prev_open = (prev.get("page") or {}).get("open")
                        if page["open"] and prev_open is False:
                            added.append({"k": "watch", "name": name, "url": e["url"], "ts": stamp, "sub": "pageopen",
                                          "msg": "The official page now shows registration wording."})
                        page["hash"] = h
                except Exception as ex:  # noqa: BLE001
                    page["err"] = str(ex)[:120]
                res["page"] = page
            cache[name] = res

        # the open list we already downloaded is the most reliable source for a live edition
        eds = {x["id"]: x for x in (res.get("editions") or [])}
        for x in open_items:
            if hit(x):
                eds[x["id"]] = _edition(x)
        eds = sorted(eds.values(), key=lambda z: z.get("re") or "", reverse=True)[:8]
        open_ed = next((x for x in eds if x.get("st") == "STARTED" and (parse_dt(x.get("re")) or now) > now), None)
        if open_ed and not prev.get("was_open"):
            added.append({"k": "watch", "name": name, "url": open_ed["url"], "ts": stamp, "sub": "open", "id": open_ed["id"],
                          "msg": f"{open_ed['t']} is open on Unstop."})
        if name in cache:
            cache[name]["was_open"] = bool(open_ed)
        if eds:
            extra_ids.append(eds[0]["id"])
        out.append({"name": name, "by": e.get("by"), "note": e.get("note"), "url": e.get("url"), "mine": bool(e.get("mine")),
                    "editions": eds, "open": open_ed["id"] if open_ed else None, "last": eds[0]["id"] if eds else None,
                    "page": res.get("page"), "checked": res.get("checked"), "unstop_ok": res.get("unstop_ok")})
    if not offline:
        write_json(CACHE / "watch.json", cache)
    return out, added, extra_ids


# ----------------------------------------------------------------------------
# Build
# ----------------------------------------------------------------------------
def build(cfg, items, details, now, offline=False):
    model = Model(cfg)
    state = read_json(STATE, {})
    comps = []
    for it in items:
        try:
            comps.append(model.classify(it, details.get(it["id"]), now))
        except Exception as e:  # noqa: BLE001 - one odd record must not kill the run
            log(f"  ! could not read comp {it.get('id')}: {e}")
    comps.sort(key=lambda c: -c["score"])
    open_ids = {c["id"] for c in comps}

    watch, watch_events, watch_ids = check_watchlist(cfg, state, now, offline, items)

    # tracked comps and last flagship editions that are no longer in the open list
    want = [int(k) for k in (state.get("tracked") or {}) if str(k).isdigit()] + watch_ids
    extra = []
    for cid in dict.fromkeys(want):
        if cid in open_ids:
            continue
        det = get_extra(cid, offline)
        if not det:
            continue
        try:
            r = model.classify(dict(det), det, now)
            r["closed"] = True
            extra.append(r)
        except Exception as e:  # noqa: BLE001
            log(f"  ! could not read tracked comp {cid}: {e}")

    events, added = update_history(comps + extra, now, cfg)
    events = save_events(events, added + watch_events, now)

    meta = {
        "generated": now.isoformat(), "count": len(comps), "newDays": cfg.get("new_within_days", 3),
        "groups": [{"id": g["id"], "label": g["label"], "always": bool(g.get("always"))} for g in cfg["groups"] + cfg["corporate"].get("families", [])]
                  + [{"id": "corp", "label": "Corporate (any known brand)"}, {"id": "global", "label": "Global / international"},
                     {"id": "org", "label": "Small company / community"}],
        "profile": {k: v for k, v in (cfg.get("profile") or {}).items() if not k.startswith("_")},
        "niches": [{"id": n["id"], "label": n["label"], "biz": bool(n.get("business"))} for n in cfg["niches"]],
        "roundTypes": {t["id"]: t["label"] for t in cfg["round_types"]},
        "tiers": cfg["scoring"]["tiers"], "preAlertDays": cfg.get("watch", {}).get("pre_alert_days", 14),
    }
    data = {"meta": meta, "comps": comps, "extra": extra, "events": events, "watch": watch}
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    tpl = (ROOT / "template.html").read_text("utf-8")
    fonts = ROOT / "fonts.css"  # Inter, embedded so the dashboard needs no network
    art = ROOT / "assets.css"  # banner photos, embedded for the same reason
    tpl = tpl.replace("/*__FONTS__*/", (fonts.read_text("utf-8") if fonts.exists() else "") + (art.read_text("utf-8") if art.exists() else ""))
    (ROOT / "dashboard.html").write_text(tpl.replace("/*__DATA__*/null", payload), "utf-8")
    write_json(ROOT / "data.json", data, indent=1)
    return comps, added + watch_events


def run(offline=False):
    with RUN_LOCK:
        cfg = json.loads((ROOT / "config.json").read_text("utf-8"))
        now = now_ist()
        if offline:
            log("Rebuilding from cache…")
            items, details = load_cached()
        else:
            log("Fetching open competitions from Unstop…")
            items, details = fetch_all(cfg)
        comps, added = build(cfg, items, details, now, offline)
        safe = [c for c in comps if c["loc"] in ("online", "delhi", "ncr")]
        log(f"Done: {len(comps)} open comps, {len(safe)} reachable, "
            f"{sum(1 for c in safe if c['tier'] == 'high')} high priority, {len(added)} new notification(s). -> dashboard.html")
        return comps


# ----------------------------------------------------------------------------
# Local server: dashboard + saved tracker + refresh
# ----------------------------------------------------------------------------
def serve(port, auto_hours):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    status = {"running": False, "error": None, "last": None}
    state_lock = threading.Lock()

    def refresh():
        try:
            run()
            status["error"] = None
        except Exception as e:  # noqa: BLE001
            status["error"] = str(e)
            log("  ! refresh failed:", e)
        finally:
            status["last"] = now_ist().isoformat()
            status["running"] = False

    def start_refresh():
        if not status["running"]:
            status["running"] = True
            threading.Thread(target=refresh, daemon=True).start()

    def auto():
        while True:
            time.sleep(auto_hours * 3600)
            start_refresh()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype="application/json"):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html", "/dashboard.html"):
                f = ROOT / "dashboard.html"
                if not f.exists():
                    return self.send(503, b"No dashboard yet - first refresh in progress, reload in a minute.", "text/plain")
                return self.send(200, f.read_bytes(), "text/html; charset=utf-8")
            if path == "/status":
                return self.send(200, status)
            if path == "/api/state":
                with state_lock:
                    return self.send(200, read_json(STATE, {}))
            self.send(404, {"error": "not found"})

        def do_PUT(self):
            if self.path.split("?")[0] != "/api/state":
                return self.send(404, {"error": "not found"})
            try:
                new = self.body()
                if not isinstance(new, dict):
                    raise ValueError("state must be an object")
            except Exception as e:  # noqa: BLE001
                return self.send(400, {"error": str(e)})
            with state_lock:
                if STATE.exists():
                    (MY / "state.backup.json").write_bytes(STATE.read_bytes())
                write_json(STATE, new, indent=1)
            self.send(200, {"ok": True})

        def do_POST(self):
            path = self.path.split("?")[0]
            if path == "/refresh":
                start_refresh()
                return self.send(202, status)
            if path == "/api/track":
                try:
                    cid = comp_id_from(self.body().get("url") or "")
                    if not cid:
                        return self.send(400, {"error": "That does not look like an Unstop competition link."})
                    det = get_extra(cid)
                    if not det:
                        return self.send(404, {"error": "Unstop did not return that competition."})
                    cfg = json.loads((ROOT / "config.json").read_text("utf-8"))
                    rec = Model(cfg).classify(dict(det), det, now_ist())
                    return self.send(200, rec)
                except Exception as e:  # noqa: BLE001
                    return self.send(500, {"error": str(e)})
            self.send(404, {"error": "not found"})

    MY.mkdir(exist_ok=True)
    if not (ROOT / "dashboard.html").exists():
        run(offline=(CACHE / "list.json").exists())
    if auto_hours > 0:
        threading.Thread(target=auto, daemon=True).start()
    log(f"Serving on http://localhost:{port}  (Ctrl+C to stop)" + (f", refreshing every {auto_hours:g} h" if auto_hours > 0 else ""))
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="MyStop, a personal competition dashboard built on Unstop")
    ap.add_argument("--offline", action="store_true", help="rebuild from cache, no network")
    ap.add_argument("--serve", action="store_true", help="serve the dashboard; saves your tracker to my/state.json")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--auto", type=float, default=6, help="with --serve: refresh every N hours (0 = never)")
    ap.add_argument("--open", action="store_true", help="open the dashboard in your browser")
    a = ap.parse_args()
    if a.serve:
        serve(a.port, a.auto)
    else:
        run(offline=a.offline)
        if a.open:
            import webbrowser
            webbrowser.open((ROOT / "dashboard.html").as_uri())
