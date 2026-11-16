"""
Unstop Radar - the reading model.

No AI service, no API key: this is a rule engine that reads every listing sentence by
sentence. For each sentence that hints at an in-person stage it decides whether the
sentence is about *taking part* (and whether that is required or optional), or about
something else (a negation, the case topic, how judges work). The same approach types
each round (quiz / deck / presentation ...), finds internship offers that are actual
rewards, and scores "global" on evidence instead of on the word in the title.

Everything it decides is returned with the sentence it was based on, so the dashboard
can show its reasoning. All patterns live in config.json.
"""
import datetime as dt
import html
import json
import re

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
BLOCK = re.compile(r"</(p|div|li|h[1-6]|tr|ul|ol|table|blockquote|td)>|<br\s*/?>|<li[^>]*>", re.I)


def text_of(h, breaks=False):
    """HTML/markdown -> plain text. With breaks=True, block boundaries become newlines."""
    h = h or ""
    if breaks:
        h = BLOCK.sub("\n", h)
    t = html.unescape(re.sub(r"<[^>]+>", " ", h)).replace("\u200b", "").replace("\xa0", " ")
    if breaks:
        t = re.sub(r"[ \t\r\f\v]+", " ", t)
        t = re.sub(r"[#*_`>]{1,}", " ", t)  # markdown noise
        return re.sub(r"\s*\n\s*", "\n", t).strip()
    return re.sub(r"\s+", " ", t).strip()


SPLIT = re.compile(r"\n+|(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])|\s[•●▪◦|]\s|;\s+")


def sentences(t):
    out = []
    for p in SPLIT.split(t or ""):
        p = re.sub(r"\s+", " ", p or "").strip(" -–—:•\t")
        if len(p) > 2:
            out.append(p)
    return out


def rx(p, flags=re.I):
    return re.compile(p, flags)


def brand_regex(brands):
    """Short all-caps brands (EY, ITC, SAP...) match case-sensitively; the rest case-insensitively."""
    cs = [re.escape(b) for b in brands if len(b) <= 4 and b.upper() == b]
    ci = [re.escape(b) for b in brands if not (len(b) <= 4 and b.upper() == b)]
    wrap = lambda parts: r"(?<![A-Za-z0-9])(?:%s)(?![A-Za-z0-9])" % "|".join(parts)  # noqa: E731
    return (re.compile(wrap(cs)) if cs else None, re.compile(wrap(ci), re.I) if ci else None)


def parse_dt(s):
    if not s:
        return None
    s = str(s).strip()
    try:
        d = dt.datetime.fromisoformat(s.replace(" GMT+0530", "+05:30").replace(" +", "+"))
    except ValueError:
        m = re.match(r"(\d{4}-\d\d-\d\d)[ T](\d\d:\d\d:\d\d)", s)
        if not m:
            return None
        d = dt.datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}+05:30")
    return d if d.tzinfo else d.replace(tzinfo=IST)


AMOUNT = re.compile(
    r"(?:₹|rs\.?|inr)\s*([\d][\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|l\b|k\b|crores?|cr\b)?"
    r"|([\d][\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|crores?)\b", re.I)
PRIZE_CTX = re.compile(r"prize|worth|pool|cash|reward|win\b|winner", re.I)


def amounts_in(text, need_context=False):
    out = []
    for m in AMOUNT.finditer(text or ""):
        num, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        try:
            v = float(num.replace(",", ""))
        except ValueError:
            continue
        u = (unit or "").lower()
        if u.startswith(("lakh", "lac")) or u == "l":
            v *= 1e5
        elif u.startswith("cr"):
            v *= 1e7
        elif u == "k":
            v *= 1e3
        if not 500 <= v <= 5e7:
            continue
        if need_context and not PRIZE_CTX.search(text[max(0, m.start() - 70): m.end() + 50]):
            continue
        out.append(int(v))
    return out


COURSE_CATS = ["engineering", "bSchools", "arts", "medicine", "law"]


def parse_eligibility(raw):
    """Unstop's eligibility JSON -> compact descriptor the dashboard checks your profile against."""
    try:
        e = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return None
    if not isinstance(e, dict):
        return None
    sec = [s for s in (e.get("sector") or []) if isinstance(s, str)]
    cr = {}
    for cat in COURSE_CATS:
        v = e.get(cat) or []
        if not isinstance(v, list):
            continue
        if "allCourses" in v or "all" in v:
            cr["*" + cat] = 0
        for x in v:
            if isinstance(x, dict) and x.get("course"):
                yrs = [int(y) for y in (x.get("passoutYear") or []) if str(y).isdigit()]
                cr[x["course"]] = yrs or 0
    yrs = [int(y) for y in (e.get("studentPassoutYearsSelected") or []) if str(y).isdigit()]
    return {"sec": sec, "all": not cr, "cr": cr, "py": yrs or None,
            "sum": text_of(e.get("eligibilitySummery"))[:300] or None}


class Model:
    def __init__(self, cfg):
        self.cfg = cfg
        h = cfg["home"]
        self.home_delhi, self.home_ncr = rx(h["delhi"]), rx(h["ncr"])
        self.not_delhi = rx(h["not_delhi"]) if h.get("not_delhi") else None
        self.groups = [{**g, "_m": [rx(p) for p in g["match"]],
                        "_b": [(rx(b["match"]), b["score"]) for b in g.get("boost", [])]} for g in cfg["groups"]]
        c = cfg["corporate"]
        self.college_like = rx(c["college_like"])
        self.brand_cs, self.brand_ci = brand_regex(c["brands"])
        self.families = [{**f, "_m": rx(f["match"])} for f in c.get("families", [])]

        m = cfg["mode_model"]
        self.cue = rx("|".join(f"(?:{p})" for p in m["cues"]))
        self.venue_online = rx(m["venue_online"])
        self.must_attend = rx(m["must_attend"])
        self.negation = rx(m["negation"])
        self.online_only = rx(m["online_only"])
        self.topic_after = rx(r"^\W{0,3}(?:%s)\b" % m["topic_after"])
        self.topic_pair = rx(r"\bonline\s*(?:and|&|or|/|as well as|,|to|-to-|\+)\s*$")
        self.pair_exempt = rx(r"^\W{0,3}(?:%s)\b" % m["topic_pair_exempt"])
        self.evaluation = rx(m["evaluation"])
        self.optional = rx(m["optional"])
        self.participation = rx(r"\b(?:%s)" % m["participation"])
        self.travel_paid = rx(m["travel_paid"])
        self.places = rx(r"\b(?:%s)\b" % "|".join(m["places"]))
        self.mode_words = rx(r"\b(hybrid|mode|format|participat\w*|conducted|held|simultaneously|rounds?|present|pitch|attend|join|appear|compete|finalists?)\b")
        self.stage_words = rx(r"\b(round|finale|finals?|semi[- ]?finals?|shortlisted teams will (present|pitch|compete))\b")
        self.online_word = rx(r"\b(online|virtual(ly)?|remote(ly)?|google meet|zoom|ms teams|microsoft teams|on unstop)\b")

        self.round_types = [{**t, "_t": rx(t["title"]), "_x": rx(t["text"]) if t.get("text") else None} for t in cfg["round_types"]]

        g = cfg["global"]
        self.g_title, self.g_excl = rx(g["title"]), rx(g["title_exclude"])
        self.g_open, self.g_stage, self.g_org, self.g_india = rx(g["open_worldwide"]), rx(g["world_stage"]), rx(g["org"]), rx(g["india_only"])

        i = cfg["internship"]
        self.i_reward = [rx(p.replace("{CUE}", "(?:%s)" % i["cue"])) for p in i["reward_patterns"]]
        self.i_not = rx(i["not_reward"])
        self.i_strong = rx(i["strong"])

        self.niches = [{**n, "_re": rx(n["re"]), "_title": rx(n["title"]) if n.get("title") else None} for n in cfg["niches"]]
        self.fmt_strong = rx(cfg["format"]["strong"]["re"])
        self.coding_title = rx(cfg["format"].get("coding_title") or r"hackathon")

    # ------------------------------------------------------------------ helpers
    def brand_hit(self, s):
        for r in (self.brand_cs, self.brand_ci):
            if r:
                m = r.search(s or "")
                if m:
                    return m.group(0)
        return None

    def place(self, s):
        """'delhi' / 'ncr' / None for a venue, organiser or sentence."""
        if not s:
            return None
        if self.home_ncr.search(s):
            return "ncr"
        if self.home_delhi.search(s) and not (self.not_delhi and self.not_delhi.search(s)):
            return "delhi"
        return None

    # ------------------------------------------------------- in-person reading
    def read_sentence(self, s):
        """
        Classify one sentence. Returns None when it has no in-person cue, else
        {"label": required | optional | negated | topic | evaluation | venue_online, "kw", "place"}.
        """
        best = None
        rank = {"required": 5, "optional": 4, "weak": 3, "negated": 2, "evaluation": 1, "topic": 1, "venue_online": 1}
        short = len(s.split()) <= 6
        for m in self.cue.finditer(s):
            kw, before, after = m.group(0), s[:m.start()], s[m.end():]
            near = before[-60:] + " " + kw + " " + after[:60]
            is_off = bool(re.match(r"off[- ]?line", kw, re.I))
            is_venue = kw.lower().startswith("venue")
            if is_venue and self.venue_online.search(s[m.start():m.start() + 60]):
                label = "venue_online"
            elif self.must_attend.search(before[-60:] + kw + after[:20]):
                label = "required"
            elif self.negation.search(before[-45:]) or self.online_only.search(s):
                label = "negated"
            elif is_off and (self.topic_after.search(after) or
                             (self.topic_pair.search(before) and re.match(r"\W{0,3}[a-z]+", after, re.I)
                              and not self.pair_exempt.search(after) and not self.mode_words.search(near))):
                label = "topic"
            elif is_off and self.evaluation.search(s):
                label = "evaluation"
            elif self.travel_paid.search(s) and not self.stage_words.search(s):
                label = "optional"  # a sponsored trip as a reward, not a round
            elif self.optional.search(s):
                label = "optional"
            elif is_venue:
                # "venue" alone proves little: only "Venue: <place>" / "at the venue" count
                label = "required" if re.search(r"\bvenue\b\s*[:\-–]\s*\S|\b(at|to) the venue\b", s, re.I) else "weak"
            elif short or self.participation.search(near):
                label = "required"
            else:
                label = "weak"
            if best is None or rank[label] > rank[best["label"]]:
                pm = self.places.search(s)
                best = {"label": label, "kw": kw, "place": pm.group(0) if pm else None}
        return best

    def read_mode(self, segments):
        """segments: [(source label, text)]. Returns verdict + evidence sentences."""
        ev, verdict, where = [], "none", None
        order = {"none": 0, "unclear": 1, "required": 2}
        for src, t in segments:
            for s in sentences(t):
                r = self.read_sentence(s)
                if not r:
                    continue
                v = {"required": "required", "optional": "unclear", "weak": "unclear"}.get(r["label"], "none")
                if order[v] > order[verdict]:
                    verdict, where = v, None
                if v == verdict and v != "none" and r["place"] and not where:
                    where = r["place"]
                snip = s if len(s) <= 230 else self._window(s, r["kw"])
                ev.append({"src": src, "kw": r["kw"], "label": r["label"], "snip": snip, "place": r["place"]})
        # most decisive evidence first; keep a few
        pri = {"required": 0, "optional": 1, "weak": 1, "negated": 2, "evaluation": 3, "topic": 3, "venue_online": 3}
        ev.sort(key=lambda e: pri[e["label"]])
        return verdict, where, ev[:5]

    @staticmethod
    def _window(s, kw, pad=100):
        i = s.lower().find(kw.lower())
        a, b = max(0, i - pad), min(len(s), i + len(kw) + pad)
        return ("…" if a else "") + s[a:b].strip() + ("…" if b < len(s) else "")

    # ------------------------------------------------------------- round typing
    def round_type(self, title, text, entity, subtype, has_file):
        t = title or ""
        for rt in self.round_types:  # ordered: first title match wins
            if rt["_t"].search(t):
                return rt["id"]
        ent = (entity or "").split("\\")[-1]
        if subtype and str(subtype).lower() == "session":
            return "info"
        if ent == "AssessmentRound":
            return "quiz"
        if ent == "SimulationGame":
            return "sim"
        head = (text or "")[:260]
        for rt in self.round_types:
            if rt["_x"] and rt["_x"].search(head):
                return rt["id"]
        if has_file:
            return "deck"
        return "other"

    # --------------------------------------------------------------- classify
    def classify(self, it, det, now=None):
        cfg, sc = self.cfg, self.cfg["scoring"]
        det = det or {}
        now = now or dt.datetime.now(IST)
        org = it.get("organisation") or det.get("organisation") or {}
        org_name = (org.get("name") or "").strip()
        fest = it.get("festival") or {}
        fest_org = ((fest.get("organisation") or {}).get("name") or "")
        org_blob = " | ".join(x for x in [org_name, fest_org] if x)
        title = (it.get("title") or "").strip()
        raw_body = it.get("details") or det.get("details")
        body, body_br = text_of(raw_body), text_of(raw_body, breaks=True)
        why = []

        # rounds ----------------------------------------------------------
        rounds = []
        for r in det.get("rounds") or []:
            if r.get("is_hidden"):
                continue
            dl = r.get("details")
            dl = dl if isinstance(dl, list) else [dl] if dl else []
            for d in dl:
                rt = (d.get("title") or "").strip()
                rx_ = text_of((d.get("display_text") or "") + "\n" + (d.get("description") or ""), breaks=True)
                s, e = parse_dt(d.get("start_date")), parse_dt(d.get("end_date"))
                rounds.append({
                    "t": rt, "x": rx_,
                    "ty": self.round_type(rt, rx_, r.get("entity_type"), r.get("subtype"), bool(r.get("submission_types"))),
                    "s": s.isoformat() if s else None, "e": e.isoformat() if e else None,
                })
        round_blob = " ".join(r["t"] + " " + r["x"] for r in rounds)
        dates_blob = "\n".join((d.get("title") or "") for d in det.get("datesToshow") or [])
        real_rounds = [r for r in rounds if r["ty"] != "info"]
        n_rounds = len(real_rounds) or None

        # organiser groups ------------------------------------------------
        cats, prestige, prestige_label = [], 0, None
        for g in self.groups:
            if any(u in cats for u in g.get("unless", [])):
                continue
            if any(m.search(org_blob) for m in g["_m"]):
                s = g["score"]
                for br, bs in g["_b"]:
                    if br.search(org_blob):
                        s = max(s, bs)
                cats.append(g["id"])
                if s > prestige:
                    prestige, prestige_label = s, g["label"]

        cc = cfg["corporate"]
        tier = org.get("tier")
        is_college = bool(cats) or bool(self.college_like.search(org_name)) or str((det.get("organisation") or {}).get("organisation_type")) in ("2", "3", "5", "7")
        org_brand = None if is_college else self.brand_hit(org_name)
        title_brand = self.brand_hit(title)
        if title_brand and not cats:
            tb = re.escape(title_brand)
            if not re.search(r"(\bby|\bx|×|\bwith|presents|powered by|sponsored by|association with)\s+(the\s+)?%s|%s\s+(x\b|×|presents)" % (tb, tb), title, re.I):
                title_brand = None
        org_is_brand = (not is_college) and bool(org_brand or tier in (1, 2))
        small_org = (not is_college) and not org_is_brand
        if not is_college:
            if org_brand or tier == 1:
                cats.append("corp")
                if cc["score_brand"] > prestige:
                    prestige, prestige_label = cc["score_brand"], "Corporate brand"
            elif tier == 2:
                cats.append("corp")
                if cc["score_tier2"] > prestige:
                    prestige, prestige_label = cc["score_tier2"], "Corporate (Unstop tier 2)"
            else:
                cats.append("org")
                s = cc["score_other"]["tier3" if tier == 3 else "none"]
                if s > prestige:
                    prestige, prestige_label = s, "Small company / community"
        elif title_brand:
            cats.append("corp")
            if prestige:
                prestige += cc["cobrand_bonus"]
                prestige_label = f"{prestige_label} × {title_brand}"
            else:
                prestige, prestige_label = 18, f"Brand-backed ({title_brand})"

        # brand families (consulting, Big 4, finance): their own filter tag and score
        if "corp" in cats and (org_brand or title_brand):
            src = org_name if org_brand else title
            for f in self.families:
                if f["_m"].search(src):
                    cats.append(f["id"])
                    if org_brand and f["score"] > prestige:
                        prestige, prestige_label = f["score"], f["label"]
                    break

        # global: evidence points, not just the word in the title ------------
        prizes = it.get("prizes") or det.get("prizes") or []
        addr = it.get("address_with_country_logo") or det.get("address_with_country_logo") or {}
        country = ((addr.get("country") or {}).get("name") or "")
        gl, g_pts, g_ev = cfg["global"], 0, []

        def gadd(p, label):
            nonlocal g_pts
            g_pts += p
            g_ev.append(label)

        if any((p.get("currencyCode") or "INR") != "INR" and p.get("cash") for p in prizes):
            gadd(3, "prize in foreign currency")
        if country and country != "India":
            gadd(3, f"based in {country}")
        if self.g_org.search(org_name):
            gadd(3, "international organiser")
        if det.get("eligible_countries") or det.get("opportunityCountries"):
            gadd(2, "country list in eligibility")
        mo = self.g_open.search(body)
        if mo:
            gadd(2, f"“{mo.group(0)}”")
        ms = self.g_stage.search(body + " " + round_blob)
        if ms:
            gadd(3, f"“{ms.group(0)}”")
        if self.g_title.search(title) and not self.g_excl.search(title):
            gadd(1, "“global / international” in title")
        mi = self.g_india.search(title + " " + body)
        if mi and g_pts:
            gadd(-2, f"but “{mi.group(0)}”")
        is_global = g_pts >= gl["tag_at"]
        if is_global:
            cats.append("global")
            base = gl["score"] if g_pts >= gl["strong_at"] else gl["score_weak"]
            if prestige >= 20:
                prestige += gl["bonus_on_top"]
                prestige_label = f"{prestige_label} + global"
            elif base > prestige:
                prestige, prestige_label = base, "Global (" + g_ev[0] + ")"
        prestige = min(prestige, 44)

        # where it happens: read every sentence ----------------------------
        region = (it.get("region") or det.get("region") or "").lower() or "online"
        segs = [("description", title + "\n" + body_br)] + \
               [(f"round “{r['t'] or 'untitled'}”", r["t"] + "\n" + r["x"]) for r in rounds] + \
               [("important dates", dates_blob)]
        verdict, ev_place, ev = self.read_mode(segs)
        for r in rounds:  # per-round mode, for the tracker
            v, _, _ = self.read_mode([("r", r["t"] + "\n" + r["x"])])
            r["m"] = "inperson" if v == "required" else "unclear" if v == "unclear" else \
                     "online" if (region == "online" or self.online_word.search(r["t"] + " " + r["x"][:300])) else None
        city = (addr.get("city") or "").strip()
        state = (addr.get("state") or "").strip()
        if region == "offline" or (region == "hybrid" and verdict != "unclear"):
            need = "required"
        elif region == "hybrid":
            need = "unclear"
        else:
            need = verdict
        # where would you have to go: sentence place > listed venue > organiser
        home = self.place(ev_place) if ev_place else self.place(f"{city} {state}") if city else self.place(org_blob)
        in_city = ev_place or city or None
        if need == "none":
            loc = "online"
        elif home:
            loc = home
        elif need == "unclear":
            loc = "check"
        elif org_is_brand:
            loc = "corp"
        else:
            loc = "travel" if region in ("offline", "hybrid") else "flag"
        # strict groups (IIMs): any in-person wording at all rejects the comp, even when it reads as optional or off-topic
        strict = False
        if loc in ("online", "check") and set(cats) & set(cfg["mode_model"].get("strict_groups", [])) \
                and any(e["label"] not in ("negated", "venue_online") for e in ev):
            strict, loc = True, "flag"
        tp = self.travel_paid.search(body + " " + round_blob)
        travel_paid = self._window(body + " " + round_blob, tp.group(0), 70) if tp else None
        mode_conf = "high" if (need == "none" and not ev) or (need == "required" and (region != "online" or any(e["label"] == "required" for e in ev))) else "medium"

        # niche ----------------------------------------------------------
        tag_items = [w.get("name") or "" for w in it.get("workfunction") or []]
        tag_items += [f.get("name") or "" for f in it.get("filters") or [] if f.get("type") == "category"]
        tags_no_quiz = " | ".join(t for t in tag_items if "Quizzes" not in t)
        niche_scores = []
        for n in self.niches:
            t_hits = {m.group(0).lower() for m in n["_re"].finditer(title)}
            if n["_title"]:
                t_hits |= {m.group(0).lower() for m in n["_title"].finditer(title)}
            g_hits = set() if n.get("skip_tags") else {m.group(0).lower() for m in n["_re"].finditer(tags_no_quiz)}
            b_hits = set() if n.get("body") is False else {m.group(0).lower() for m in n["_re"].finditer(body + " " + round_blob)}
            s = min(6, 3 * len(t_hits)) + min(4, 2 * len(g_hits)) + min(3, len(b_hits))
            if s >= 3:
                niche_scores.append((s, n))
        niche_scores.sort(key=lambda x: -x[0])
        top = niche_scores[0][0] if niche_scores else 0
        niche_scores = [x for x in niche_scores if x[0] >= max(3, top - 4)][:4]
        niches = [n["id"] for _, n in niche_scores]
        biz = max([n.get("business", 0) for _, n in niche_scores] or [0])
        if biz:
            why.append(["Business niche: " + next(n["label"] for _, n in niche_scores if n.get("business", 0) == biz), biz])

        # format: prestige only counts in full for substantive comps --------
        fmt, mult, mult_label = 0, 1.0, None
        soft = {"creative", "culture", "debate"}
        fc = cfg["format"]
        if niches and set(niches) <= soft:
            mult, mult_label = fc["soft_prestige_mult"], "creative / cultural format"
        elif re.search(fc["light_re"], title, re.I) or set(niches) == {"quiz"}:
            mult, mult_label = fc["light_prestige_mult"], "quiz / article format"
        elif self.fmt_strong.search(title) or it.get("subtype") == "case_competition":
            fmt = fc["strong"]["score"]
        if prestige:
            if mult < 1:
                prestige = int(round(prestige * mult))
                prestige_label = f"{prestige_label} (×{mult:g}: {mult_label})"
            why.insert(0, [prestige_label, prestige])
        if fmt:
            why.append(["Case / pitch / challenge format", fmt])

        # internship: only when it is a reward, read per sentence ------------
        prize_text = " ".join(" ".join(str(p.get(k) or "") for k in ("rank", "others")) for p in prizes)
        overall = text_of(det.get("overall_prizes"))
        intern, intern_note = 0, None
        if any(p.get("pre_placement_internship") for p in prizes):
            intern, intern_note = 2, "PPI flagged in the prize list"
        elif any(p.get("pre_placement_opportunity") for p in prizes):
            intern, intern_note = 2, "PPO flagged in the prize list"
        else:
            m = self.i_strong.search(prize_text + " " + overall)
            if m and not self.i_not.search(prize_text + " " + overall):
                intern, intern_note = 2, f"“{m.group(0)}” in the prize list"
            else:
                for s in sentences(title + "\n" + body_br):
                    if any(r.search(s) for r in self.i_reward) and not self.i_not.search(s):
                        intern, intern_note = 1, s[:220]
                        break
        i_pts = 0
        if intern:
            i_pts = cfg["internship"]["score_confirmed" if intern == 2 else "score_mentioned"]
            if small_org:
                i_pts = int(round(i_pts * cfg["internship"]["small_org_mult"]))
            why.append(["Internship / PPI / PPO " + ("in prizes" if intern == 2 else "as a reward") + (" (small organiser)" if small_org else ""), i_pts])

        # prize money ----------------------------------------------------
        fx = cfg.get("usd_to_inr", 88)
        cash = 0
        for p in prizes:
            c = p.get("cash") or 0
            try:
                c = float(c)
            except (TypeError, ValueError):
                c = 0
            cash += c * (fx if (p.get("currencyCode") or "INR") == "USD" else 1)
        cash, prize_est = int(cash), False
        if not cash:
            found = amounts_in(overall) or amounts_in(body, need_context=True)
            if found:
                cash, prize_est = max(found), True
        p_pts = next((pts for floor, pts in sc["prize"] if cash >= floor), 0) if cash else 0
        if p_pts:
            why.append(["Prize money", p_pts])

        # effort ---------------------------------------------------------
        reg = it.get("registerCount") or det.get("registerCount") or 0
        r_pts = 0
        if n_rounds:
            r_pts = sc["rounds"].get(str(n_rounds) if n_rounds <= 5 else "6+", 0)
            if r_pts:
                why.append([f"{n_rounds} competitive round{'s' if n_rounds > 1 else ''}", r_pts])
        g_reg = next(pts for ceil, pts in sc["registrations"] if reg < ceil) if reg else 0
        if g_reg:
            why.append([f"{reg:,} registered so far", g_reg])

        # eligibility ----------------------------------------------------
        emap = {"Undergraduate": "ug", "Postgraduate": "pg", "Management": "mba", "Engineering Students": "engg",
                "Arts, Commerce, Sciences & Others": "acs", "School Students": "school", "Fresher": "fresher",
                "Experienced Professionals": "pro", "All": "all", "Law": "law", "Medical": "med"}
        elig = sorted({emap[f["name"]] for f in (it.get("filters") or det.get("filters") or []) if f.get("type") == "eligible" and f.get("name") in emap})
        rr = det.get("regnRequirements") or {}
        lr = it.get("regnRequirements") or rr
        el = parse_eligibility(rr.get("eligibility") or lr.get("eligibility"))
        gender = [g for g in (rr.get("gender") or lr.get("gender") or []) if g in ("F", "M")]
        allowed = [o.get("name") for o in rr.get("allowed_organisations") or [] if o.get("name")]
        pen = 0
        school_only = (el and el["sec"] and set(el["sec"]) <= {"school"}) or (elig and set(elig) <= {"school"})
        if school_only:
            pen += sc["school_only_penalty"]
            why.append(["School students only", sc["school_only_penalty"]])

        score = max(0, min(100, prestige + biz + fmt + i_pts + p_pts + r_pts + g_reg + pen))
        tier_lbl = "high" if score >= sc["tiers"]["high"] else "medium" if score >= sc["tiers"]["medium"] else "low"

        deadline = parse_dt(lr.get("end_regn_dt") or it.get("end_date") or det.get("end_date"))
        reg_start = parse_dt(lr.get("start_regn_dt") or det.get("start_date"))
        listed = parse_dt(it.get("approved_date") or det.get("publish_at"))
        fee = None
        if it.get("isPaid") or det.get("paid"):
            amts = [p.get("amount") for p in (it.get("payment_services") or det.get("payment_services") or []) if p.get("amount")]
            fee = min(amts) if amts else -1

        return {
            "id": it["id"], "t": title, "url": it.get("seo_url") or det.get("seo_url") or "https://unstop.com/" + (it.get("public_url") or ""),
            "org": org_name, "fest": (fest.get("name") or "").strip() or None,
            "cats": cats, "loc": loc, "mode": region, "city": ", ".join(x for x in [city, state] if x) or None,
            "need": need, "inCity": in_city, "conf": mode_conf, "strict": strict, "ev": ev, "travelPaid": travel_paid,
            "gEv": g_ev if g_pts > 0 else [], "gPts": g_pts,
            "niches": niches, "intern": intern, "internNote": intern_note,
            "prize": cash, "prizeEst": prize_est,
            "prizeTxt": overall[:140] if re.search(r"\d", overall) or len(overall) > 40 else None,
            "rounds": n_rounds, "rd": [{"t": r["t"], "ty": r["ty"], "s": r["s"], "e": r["e"], "m": r["m"]} for r in rounds][:12],
            "reg": reg, "views": it.get("viewsCount") or det.get("viewsCount") or 0,
            "tmin": lr.get("min_team_size"), "tmax": lr.get("max_team_size"), "sameOrg": bool(rr.get("same_organisation") or lr.get("same_organisation")),
            "fee": fee, "dl": deadline.isoformat() if deadline else None, "rs": reg_start.isoformat() if reg_start else None,
            "listed": listed.isoformat() if listed else None,
            "elig": elig, "el": el, "g": gender[0] if len(gender) == 1 else None, "restr": allowed[:60], "restrN": len(allowed),
            "score": int(round(score)), "tier": tier_lbl, "why": why, "sub": it.get("subtype") or None, "case": bool(fmt),
            "logo": it.get("logoUrl2") or (it.get("organisation") or {}).get("logoUrl2") or (it.get("organisation") or {}).get("logoUrl") or None,
            "code": bool(("tech" in niches and not biz) or (self.coding_title.search(title) and ("tech" in niches or not biz))),
        }
