# MyStop

Finds the competitions on Unstop that are worth your time, hides the ones you can't enter or can't reach, tracks the ones you registered for, and tells you when something changes.

Everything is free. It needs only Python 3.8+ (standard library, nothing to install), no account, no API key and no AI service. The "reading" is done by rules in `model.py` and `config.json`.

## Run it

```bash
cd unstop-radar
python radar.py --serve        # then open http://localhost:8000
```

Leave it running. It refreshes from Unstop every 6 hours (`--auto 3` to change, `--auto 0` to turn off) and whenever you press **Refresh from Unstop**. A refresh takes about a minute; the first one a little longer.

Other ways to run it:

| Command | What it does |
| --- | --- |
| `python radar.py` | Fetch once and write `dashboard.html` |
| `python radar.py --open` | Same, then open the file in your browser |
| `python radar.py --offline` | Rebuild from the cache, no network. Use after editing `config.json` |

Opening `dashboard.html` directly works too, but then your tracker lives only in that browser, closed comps can't be followed, and names you add to the watchlist are not checked. Use `--serve` for the full thing.

## What is in the dashboard

The dashboard is called **MyStop**: Unstop, filtered and tracked for one person. It opens on the light theme; the sun / moon button at the top right switches to dark. On a phone the sections move to a bar at the bottom. The search box at the top works from every section.

### Home
- **Your Top Picks.** The three highest-scoring open comps you have not registered for. The arrow opens the full card with the score breakdown.
- **Your Progress.** Of the stages that have opened in your tracked comps, the share you have marked done, plus the next things to do.
- **Upcoming Events.** The next dates from your tracker and your starred comps. If there are fewer than four, registration deadlines of your top picks fill the list.
- **Rotating banner.** One comp per angle, sliding every few seconds: the open flagship, best ROI (prize and internship against rounds and registrations), most reachable (fully online with the fewest rounds and registrations), closing soon, biggest prize, internship on offer, least crowded and new this week. A comp appears once, hovering pauses it, and the arrows or a swipe move it by hand.
- **Quick Links.** Your registrations, starred comps, comps closing this week, case comps.
- The card at the bottom of the sidebar shows when the data was last synced and has the **Refresh now** button.

Labels, buttons, chips and short facts are written in Title Case, and full sentences keep sentence case. The top right shows the SSCBS crest while the profile college is SSCBS, and initials for any other college.

Organiser logos load from Unstop's servers, so they need internet; without it each comp shows its initials instead. The two banner photos are AI-generated and embedded in `assets.css`.

### Discover
Every open comp, scored 0 to 100 and sorted. Filters combine as AND across groups; inside Organiser and Niche you can switch between "any" and "all".

- **Eligibility.** Your profile (SSCBS, BBA, graduating 2029) is already filled in from `config.json`; the button at the top right edits it. Comps you can't enter disappear from every view: wrong course or batch, school-only, women-only, limited to a list of colleges that does not include yours, or same-college teams if you said you can't form one. "Everything, incl. rejected" shows them again with the reason.
- **Where it happens.** The reader labels every sentence that has in-person wording: must attend, optional, vague, negated ("no travel needed"), about offline as a case topic, or only the judging being offline. The verdict and the sentences are under "Why NN?" on each card.
  - IIM comps are strict: any in-person wording at all rejects them.
  - Delhi, Gurugram, Noida and the rest of NCR are kept. Anything else must be fully online.
  - "Unclear" and "brand-run with an in-person stage" are separate buckets, switched off by default. Tick them under "Where it happens" to see them.
- **Organiser.** One tick-box per group: IIM, IIT, FMS Delhi, ISB, top B-schools (XLRI, SPJIMR, MDI, IIFT …), NMIMS & Christ, DU top colleges, St. Xavier's, BITS Pilani, Ashoka & liberal-arts universities, Masters' Union, strategy firms (McKinsey / Bain / BCG …), Big 4 & Accenture, banks and finance firms, any other known brand. A group with nothing open shows 0.
- **Format.** Coding contests, hackathons and pure-tech comps (robotics, CTFs, data-science contests) are hidden by default. A business comp that only touches tech (an AI-themed case, a fintech pitch) stays. Untick "Hide coding contests & hackathons" to see them. "Case, strategy and pitch comps only" narrows further by removing quizzes and cultural events. The title words that mark a comp as coding are in `config.json` under `format.coding_title`.
- **Hide.** The eye button hides a comp for now. The line above the list shows how many are hidden, with **Show them** and **Unhide all**.
  - If the listing says travel or stay is covered, the card says so.
- **Round 1 asks for.** Quiz, deck, video, code, live presentation. Each card also lists every stage with its type and dates.
- **Star** a comp to keep its registration deadline in Upcoming Events on Home. **Track** moves it to your tracker.

### My registrations
Replaces the spreadsheet. Dates come from Unstop on every refresh, so you never type one.

- Each comp shows its stages (quiz, deck, presentation …) with dates. A stage reads **N/A** and is locked until it opens on Unstop (its start date arrives; if a stage has no date, when the stage before it is done). From then on you set its status: Pending, Done / submitted, Cleared, Not cleared, Skipped. Plus an outcome and an optional note.
- **Calendar.** One row per comp, one horizontal bar per stage, coloured by type (quiz, deck, presentation …). Stages that have not opened yet are drawn hatched. The glowing line is today, the diamond at the end of a bar is its deadline, and a day where two comps have something due is highlighted as a clash. Click a bar to jump to that comp.
- **High / Normal / Low** is your own priority. **Hide for now** takes a comp out of the list, the calendar and the reminders without deleting anything. It waits under **Hidden**, where you can unhide it or press **Unhide all**. **Remove** is the one that deletes.
- Paste an Unstop link to add something you registered for earlier, including comps whose registration has already closed.

### Flagship watchlist
Big annual comps followed by name all year (Tata Imagination Challenge, HUL L.I.M.E., Reliance T.U.P., Brandstorm …). For each one you see whether it is open, when the last edition ran, when the next is expected, and whether you could have entered the last edition. Add your own by name in the tab, or edit `watchlist.json`. Entries with an official `url` outside Unstop are also checked for registration wording and page changes.

### Notifications (bell, top right)

Only comps in **My Registrations** raise a notification. New listings, starred comps and the flagship watchlist never do.

- Reminders 3 days before, 1 day before and on the day of every pending stage
- Deadline extensions and deadlines pulled earlier
- Stage date changes, stage list changes and prize changes

A comp you put under Hidden stays silent until you unhide it. Flagship openings show on the Watchlist tab, its sidebar badge and the Home banner instead.

Changes are found by comparing each refresh with the previous one, so they start appearing from the second refresh onward.

## Publish on GitHub

The folder is ready to go on GitHub as it is. `.gitignore` keeps `cache/` and `my/` out, so your tracker never leaves your computer.

1. Create a new repository on github.com, for example `mystop`. It has to be Public for a free GitHub Pages link.
2. On the empty repository page choose "uploading an existing file", drag in everything from this folder (including `.github`), and commit.
3. Open Settings, then Pages, and set Source to **GitHub Actions**.
4. Open the Actions tab, pick **Refresh MyStop** and press **Run workflow**. About three minutes later the dashboard is live at `https://YOUR-USERNAME.github.io/mystop/`.

After that `.github/workflows/refresh.yml` pulls fresh data from Unstop four times a day (6 am, noon, 6 pm, midnight IST) and republishes. If Unstop cannot be reached, it publishes the `dashboard.html` stored in the repository instead.

What is different on the GitHub link:

- Your registrations, stars and hidden comps are saved in the browser you use, so your phone and your laptop each keep their own list.
- There is no Refresh button, the schedule does it. For an extra refresh press Run workflow on the Actions tab.
- A comp can be added to the tracker by link only while it is open on Unstop.
- To follow another flagship comp, add it to `watchlist.json` in the repository.
- A public repository shows the profile in `config.json` (college, course, batch, gender) to anyone who has the link.

GitHub pauses scheduled runs after 60 days without a commit and emails you first. One click on the Actions tab turns them back on.

## Files

| File | Purpose |
| --- | --- |
| `radar.py` | Fetching, change tracking, watchlist checks, the local server |
| `model.py` | The reader: location, stage types, global evidence, internship, eligibility, score |
| `config.json` | All rules and weights: college lists, brands, sentence patterns, niches, scoring |
| `watchlist.json` | The flagship list |
| `template.html` | The dashboard. `dashboard.html` is this plus the data and the font |
| `fonts.css` | The Inter and Plus Jakarta Sans typefaces, embedded so the dashboard needs no internet. Delete it and the dashboard falls back to your system font |
| `assets.css`, `assets/` | The two banner photos and the college crest shown top right, embedded, and their originals |
| `my/state.json` | Your profile, stars, hidden comps, tracker and read marks. Back this up. `my/state.backup.json` is the previous save |
| `cache/` | Downloaded listings, the previous snapshot (`history.json`) and the notification log (`events.json`). Safe to delete; it rebuilds |
| `data.json` | The same data the dashboard uses, for your own scripts |

## Scoring in one paragraph

Organiser prestige (IIM, IIT, FMS, ISB, top B-schools, top DU colleges, Masters' Union, strategy firms, Big 4, banks, other known brands) up to 44; business niche up to 10; case or pitch format 5; internship 15 if it is in the prize list, 7 if a sentence offers it to winners; prize money up to 15; fewer rounds and fewer registrations add points, many rounds and thousands of registrations subtract. High is 55 and above, medium 35 and above. Every card shows its own breakdown. Change any of it in `config.json`, then run `python radar.py --offline`.

## Limits worth knowing

- The reader works from the listing text. Organisers who write nothing about the finale get the benefit of the doubt when Unstop lists the comp as online. Open the listing before you commit.
- Expected opening dates on the watchlist are last edition's date plus a year. Treat them as a rough guide.
- A comp is matched to the watchlist by name. If a brand renames its competition, add the new name.
- College matching compares the words in your college name with Unstop's list. If a restricted comp you can enter is hidden, check the spelling against Unstop's name for your college.
