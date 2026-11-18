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
import base64
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import re
import sys
import threading
import time
import unicodedata
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
# Says plainly who is asking. Unstop's robots.txt allows /api/public/ and this reads nothing else.
UA = "MyStop/1.0 (personal competition tracker; +https://github.com/raunak-comp/mystop)"
TRACK_PER_USER, TRACK_TOTAL = 80, 300  # how many tracked comp numbers one account, and all accounts together, can ask the refresh to follow
IK_API = "https://api.insidekampus.com/graphql"
IK_QUERY = """query Q($input: CompetitionMasterPaginatedListInput!) { getFilteredCompetitions(CompetitionMasterPaginatedListInput: $input) { total data {
 _id slug title description eligibility timelines rewards registrationStart registrationEnd noOfParticipants externalLink
 teamSize { type size } cardImage { url } organization { name featuredImage } campuses { campus { name } } } } }"""
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


# ----------------------------------------------------------------------------
# Second source: InsideKampus (InsideIIM's competition board)
# ----------------------------------------------------------------------------
def _iso(s):
    """InsideKampus dates look like 2026-11-11T17:29:00.000Z."""
    return re.sub(r"\.\d+", "", str(s)).replace("Z", "+00:00") if s else None


def fetch_insidekampus(offline=False):
    f = CACHE / "ik.json"
    if offline:
        return read_json(f, [])
    try:
        body = json.dumps({"query": IK_QUERY, "variables": {"input": {"filters": {"sortBy": "CLOSING_SOON"}, "limit": 200, "page": 1}}}).encode()
        req = urllib.request.Request(IK_API, data=body, headers={"Content-Type": "application/json", "User-Agent": UA, "Origin": "https://insidekampus.com"})
        with urllib.request.urlopen(req, timeout=40) as r:
            data = ((json.loads(r.read()).get("data") or {}).get("getFilteredCompetitions") or {}).get("data") or []
        write_json(f, data)
        return data
    except Exception as e:  # noqa: BLE001 - a second source must never break the run
        log(f"  ! InsideKampus could not be read: {e}")
        return read_json(f, [])


PG_ONLY = re.compile(r"\bMBA\b|\bPGDM\b|\bPGP\b|post[- ]?graduat|b-?school students|management students|\bPG students", re.I)
UG_TOO = re.compile(r"under[- ]?graduat|\bUG\b|\bBBA\b|\bB\.?Com\b|any (degree|stream|course|college student)|open to all (college )?students", re.I)


def insidekampus_records(model, raw, now):
    """Turns InsideKampus listings that are still open into the same record shape as Unstop ones."""
    out = []
    for c in raw:
        try:
            end, start = parse_dt(_iso(c.get("registrationEnd"))), parse_dt(_iso(c.get("registrationStart")))
            if not end or end <= now or (start and start > now + dt.timedelta(days=3)):
                continue
            org = c.get("organization") or {}
            ts = c.get("teamSize") or {}
            size = int(ts.get("size") or 1)
            tmin, tmax = (1, 1) if ts.get("type") == "SOLO" else (size, size) if ts.get("type") == "STRICT" else (1, size)
            rewards = " ".join(c.get("rewards") or [])
            it = {
                "id": "ik-" + str(c["_id"]), "title": c.get("title") or "", "region": "online",
                "details": " ".join(x for x in [c.get("description"), c.get("eligibility"), c.get("timelines"), rewards] if x),
                "organisation": {"name": org.get("name") or "", "logoUrl2": org.get("featuredImage")},
                "seo_url": c.get("externalLink") or "https://insidekampus.com/competitions/" + str(c.get("slug") or ""),
                "registerCount": int(c.get("noOfParticipants") or 0),
                "regnRequirements": {"end_regn_dt": end.isoformat(), "start_regn_dt": start.isoformat() if start else None,
                                     "min_team_size": tmin, "max_team_size": tmax},
                "approved_date": start.isoformat() if start else None,
            }
            r = model.classify(it, {"overall_prizes": rewards}, now)
            r["src"] = "ik"
            who = text_of(c.get("eligibility")) or text_of(c.get("description"))[:600]
            r["pgOnly"] = bool(PG_ONLY.search(who + " " + r["t"]) and not UG_TOO.search(who))
            camp = [(x.get("campus") or {}).get("name") for x in c.get("campuses") or []]
            camp = [x for x in camp if x]
            if camp:
                r["restr"], r["restrN"] = camp[:60], len(camp)
            out.append(r)
        except Exception as e:  # noqa: BLE001
            log(f"  ! could not read InsideKampus comp {c.get('slug')}: {e}")
    return out


# ----------------------------------------------------------------------------
# One comp, one card. Unstop always wins: an InsideKampus listing is kept only when Unstop does not have that comp.
# ----------------------------------------------------------------------------
_T_STOP = set("the a an of and for by in at on to with from presents presented powered edition season chapter version vol volume part".split())
_T_GENERIC = set("challenge competition contest case study quiz business national international annual fest event championship league "
                 "cup series program programme campus student students india indian indias school college institute round online".split())
_O_STOP = set("the of and for limited ltd pvt private india indian company co corporation corp group inc llp institute institution "
              "management technology university college school business studies department society club cell committee engineering "
              "science sciences arts commerce research education academy foundation global services solutions technologies systems".split())
_O_WEAK = set("iim iit nit bits delhi mumbai bangalore bengaluru calcutta kolkata lucknow indore ahmedabad kozhikode chennai hyderabad pune "
              "gurgaon gurugram noida kanpur kharagpur roorkee madras bombay national".split())
_O_HOST = {"insideiim", "insidekampus", "unstop", "dare2compete"}  # the platform itself named as organiser tells us nothing
_UNSTOP_HOSTS = ("unstop.com", "dare2compete.com")                 # Dare2Compete is the old name of Unstop
_ROMAN = {"ii": "2", "iii": "3", "iv": "4", "vi": "6", "vii": "7", "viii": "8", "ix": "9", "xi": "11", "xii": "12", "xiii": "13", "xiv": "14", "xv": "15"}


def _roman(w):
    val, total = {"i": 1, "v": 5, "x": 10}, 0
    for a, b in zip(w, w[1:] + " "):
        total += -val[a] if b in val and val[b] > val[a] else val[a]
    return total if 0 < total < 40 else 0


def _toks(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"['`\u2019]", "", s)                                                    # India's -> indias
    s = re.sub(r"\b(?:[a-z]\.){2,}[a-z]?", lambda m: m.group(0).replace(".", ""), s)   # E.P.I.C -> epic
    s = re.sub(r"\b(class|season|edition|chapter|phase|part|volume|vol|version|round)\s+([ivx]{1,5})\b",
               lambda m: m.group(1) + " " + str(_roman(m.group(2)) or m.group(2)), s)   # Class X -> class 10
    return re.findall(r"[a-z]+|\d+(?:\.\d+)?", s)


def _title_parts(t):
    """Words that name the comp, and the numbers that name its edition (2026, 7.0, Season 6, Class VII)."""
    toks = _toks(t)
    words = {w for w in toks if w[0].isalpha() and w not in _T_STOP and w not in _ROMAN and len(w) > 1}
    nums = {w[:-2] if w.endswith(".0") else w for w in toks if w[0].isdigit()} | {_ROMAN[w] for w in toks if w in _ROMAN}
    return words, nums


def _org_parts(r):
    o = {w for w in _toks(" ".join(str(r.get(k) or "") for k in ("org", "fest"))) if w[0].isalpha() and w not in _O_STOP and len(w) > 1}
    return set() if o & _O_HOST else o


def _same_org(oa, ob, ta, tb):
    hit = oa & ob
    if hit and (len(hit) / min(len(oa), len(ob)) >= .6 or any(len(w) >= 5 and w not in _O_WEAK for w in hit)):
        return True
    # the brand of one listing sits inside the title of the other ("Cummins" and "Cummins Redefine 2026")
    return any(o and (o - _O_WEAK) and o <= t for o, t in ((oa, tb), (ob, ta)))


def same_comp(a, b):
    """How sure we are that record a (InsideKampus) and record b (Unstop) are one comp. 0 means they are different.

    The words that name the comp must be the same, or one title must be the other plus a few words. Filler words
    ("Challenge", "Case", "Competition") never count. Two different edition numbers (2025 and 2026, Test 3 and
    Test 5) always mean different comps. The organiser, or failing that the registration deadline, has to agree.
    """
    (ta, na), (tb, nb) = _title_parts(a.get("t")), _title_parts(b.get("t"))
    if na and nb and not (na <= nb or nb <= na):
        return 0
    sa, sb = ta - _T_GENERIC, tb - _T_GENERIC
    if not sa or not sb or not (sa <= sb or sb <= sa):
        return 0
    oa, ob = _org_parts(a), _org_parts(b)
    org = _same_org(oa, ob, ta, tb)
    clash = bool(oa and ob) and not org                              # two known organisers that are not the same
    da, db = parse_dt(a.get("dl")), parse_dt(b.get("dl"))
    near = bool(da and db and abs((da - db).total_seconds()) <= 3 * 86400)
    small = min(len(sa), len(sb))
    if sa == sb:
        if org:
            return 1
        if clash:
            return .8 if near and small >= 2 else 0
        return .9 if small >= 2 or near else 0                       # one side does not say who runs it
    extra = (sa | sb) - (sa & sb)                                    # what the longer title adds
    if org:
        return .9 if small >= 2 or extra <= (oa | ob) else 0         # "Moves 2026" and "Axis Bank Moves 2026", not "Ops Quiz" and "Ops Hunt"
    if clash:
        return 0
    return .7 if (near and small >= 2) or small >= 3 else 0          # one side does not say who runs it


def only_new_to_unstop(ik, unstop):
    """Splits InsideKampus records into the ones Unstop does not have (kept) and the ones it does (left out)."""
    keep, dupes = [], []
    for r in ik:
        host = urllib.parse.urlparse(r.get("url") or "").netloc.lower()
        if any(host == h or host.endswith("." + h) for h in _UNSTOP_HOSTS):
            dupes.append({"t": r["t"], "same": "its link opens Unstop", "id": None})
            continue
        best, twin = 0, None
        for u in unstop:
            sc = same_comp(r, u)
            if sc > best:
                best, twin = sc, u
        if twin:
            dupes.append({"t": r["t"], "same": twin["t"], "id": twin["id"]})
        else:
            keep.append(r)
    return keep, dupes


# ----------------------------------------------------------------------------
# Sign-in (optional): signin.txt holds the Firebase web config, pasted as Firebase shows it
# ----------------------------------------------------------------------------
def read_signin():
    f = ROOT / "signin.txt"
    if not f.exists():
        return None
    txt = "\n".join(ln for ln in f.read_text("utf-8").splitlines() if not ln.strip().startswith("#"))
    got = dict(re.findall(r"[\"']?(apiKey|authDomain|projectId|storageBucket|messagingSenderId|appId)[\"']?\s*:\s*[\"']([^\"']+)[\"']", txt))
    return got if got.get("apiKey") and got.get("projectId") else None


def cloud_tracked(signin):
    """Comp numbers that signed-in people track, so a comp stays up to date after it leaves the open list.
    Each account keeps its own short list (tracked/<uid>), which nobody else can write to. Only plain comp numbers are accepted."""
    if not signin:
        return []
    base = "https://firestore.googleapis.com/v1/projects/%s/databases/(default)/documents/" % urllib.parse.quote(signin["projectId"])
    key = "key=" + urllib.parse.quote(signin["apiKey"])
    ok = lambda v: isinstance(v, str) and v.isdigit() and 4 <= len(v) <= 9  # noqa: E731
    ids, seen = [], set()

    def take(values, cap):
        n = 0
        for v in values or []:
            v = v.get("stringValue") if isinstance(v, dict) else None
            if ok(v) and n < cap:
                n += 1
                if v not in seen:
                    seen.add(v)
                    ids.append(int(v))

    try:
        doc = json.loads(http_get(base + "tracked?pageSize=300&" + key, tries=2, timeout=20))
        for d in (doc.get("documents") or [])[:300]:
            take((((d.get("fields") or {}).get("ids") or {}).get("arrayValue") or {}).get("values"), TRACK_PER_USER)
    except Exception as e:  # noqa: BLE001
        log(f"  ! tracked lists not read: {str(e)[:80]}")
    if not ids:
        # the shared list used before v13, read only until every account has written its own
        try:
            doc = json.loads(http_get(base + "public/tracked?" + key, tries=1, timeout=20))
            take(((((doc.get("fields") or {}).get("ids") or {}).get("arrayValue") or {}).get("values") or [])[-TRACK_TOTAL:], TRACK_TOTAL)
        except Exception:  # noqa: BLE001
            pass
    return ids[:TRACK_TOTAL]


def csp_for(html, signin):
    """The browser rule list for the page. Only the page's own script may run (named by its fingerprint), plus Google's sign-in files.
    Anything else that tries to run as code, such as text slipped into a listing, is refused by the browser."""
    hashes = " ".join("'sha256-%s'" % base64.b64encode(hashlib.sha256(m.encode("utf-8")).digest()).decode()
                      for m in re.findall(r"<script>(.*?)</script>", html, re.S))
    auth = signin.get("authDomain") if signin else None
    frames = "https://*.firebaseapp.com https://*.web.app https://accounts.google.com" + (" https://" + auth if auth and re.fullmatch(r"[A-Za-z0-9.-]+", auth) else "")
    return "; ".join([
        "default-src 'none'",
        "script-src " + hashes + " https://www.gstatic.com https://apis.google.com",
        "style-src 'unsafe-inline'",
        "img-src https: data:",
        "font-src data:",
        "connect-src 'self' https://*.googleapis.com https://www.gstatic.com",
        "frame-src " + frames,
        "base-uri 'none'", "form-action 'none'", "object-src 'none'",
    ])


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
        out.append({"name": name, "by": e.get("by"), "note": e.get("note"), "url": e.get("url"), "mine": bool(e.get("mine")), "group": e.get("group") or "india", "when": e.get("when"),
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
    signin = read_signin()
    use_ik = (cfg.get("sources") or {}).get("insidekampus", True)
    dupes = []
    if use_ik:
        ik, dupes = only_new_to_unstop(insidekampus_records(model, fetch_insidekampus(offline), now), comps)
        comps += ik
        log(f"  InsideKampus: {len(ik)} open that Unstop does not have" + (f", {len(dupes)} left out because Unstop lists them" if dupes else ""))
        for d in dupes:
            log(f"    = {d['t']}  (Unstop: {d['same']})")
    comps.sort(key=lambda c: -c["score"])
    open_ids = {c["id"] for c in comps}

    watch, watch_events, watch_ids = check_watchlist(cfg, state, now, offline, items)

    # tracked comps and last flagship editions that are no longer in the open list
    want = [int(k) for k in (state.get("tracked") or {}) if str(k).isdigit()] + watch_ids + ([] if offline else cloud_tracked(signin))
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
        "signin": signin, "dupes": dupes,
        "types": [{"id": t["id"], "label": t["label"], "tag": t.get("tag") or t["label"], "fam": t.get("fam", "gen")} for t in cfg.get("types", [])],
        "typeScore": (cfg.get("tech_track") or {}).get("type_score", 5),
        "regions": (cfg.get("regions") or {}).get("list", []), "homeRegion": (cfg.get("regions") or {}).get("home", "delhi-ncr"),
        "sources": [{"id": "unstop", "label": "Unstop"}] + ([{"id": "ik", "label": "InsideKampus"}] if use_ik else []),
    }
    data = {"meta": meta, "comps": comps, "extra": extra, "events": events, "watch": watch}
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    tpl = (ROOT / "template.html").read_text("utf-8")
    fonts = ROOT / "fonts.css"  # Inter, embedded so the dashboard needs no network
    art = ROOT / "assets.css"  # banner photos, embedded for the same reason
    tpl = tpl.replace("/*__FONTS__*/", (fonts.read_text("utf-8") if fonts.exists() else "") + (art.read_text("utf-8") if art.exists() else ""))
    html = tpl.replace("/*__DATA__*/null", payload)
    with open(ROOT / "dashboard.html", "w", encoding="utf-8", newline="\n") as f:
        f.write(html.replace("__CSP__", csp_for(html, signin)))
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
    ap.add_argument("--auto", type=float, default=3, help="with --serve: refresh every N hours (0 = never)")
    ap.add_argument("--open", action="store_true", help="open the dashboard in your browser")
    a = ap.parse_args()
    if a.serve:
        serve(a.port, a.auto)
    else:
        run(offline=a.offline)
        if a.open:
            import webbrowser
            webbrowser.open((ROOT / "dashboard.html").as_uri())
