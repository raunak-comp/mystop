# MyStop

Finds the competitions on Unstop that are worth your time, hides the ones you can't enter or can't reach, tracks the ones you registered for, and tells you when something changes.

Everything is free. It needs only Python 3.8+ (standard library, nothing to install), no account, no API key and no AI service. The "reading" is done by rules in `model.py` and `config.json`.

## Run it

```bash
cd unstop-radar
python radar.py --serve        # then open http://localhost:8000
```

Leave it running. It refreshes from Unstop every 3 hours (`--auto 6` to change, `--auto 0` to turn off) and whenever you press **Refresh from Unstop**. A refresh takes about a minute; the first one a little longer.

Other ways to run it:

| Command | What it does |
| --- | --- |
| `python radar.py` | Fetch once and write `dashboard.html` |
| `python radar.py --open` | Same, then open the file in your browser |
| `python radar.py --offline` | Rebuild from the cache, no network. Use after editing `config.json` |

Opening `dashboard.html` directly works too, but then your tracker lives only in that browser, closed comps can't be followed, and names you add to the watchlist are not checked. Use `--serve` for the full thing.

## What is in the dashboard

The dashboard is called **MyStop**: Unstop, filtered and tracked for one person. It opens on the light theme; the sun / moon button at the top right switches to dark. On a phone or a tablet held upright the sections move to a bar at the bottom, and the layout is checked at 21 screen sizes from a 320 px phone to a 2560 px monitor. The search box at the top works from every section.

### Home
- **My Registrations.** The first thing on Home, because keeping track of what you signed up for is the point of MyStop. One line says how many registrations are active and how many have something due in the next 7 days. Under it, up to five comps you are in, soonest first, each with the date, the next step (quiz closes, deck due, round opens), your team name and a Today / Tomorrow / In N Days tag. Click a row to open that comp in My Registrations. Only comps you tracked appear here: starred comps and top picks never do. With nothing tracked yet, it shows a button to find comps.
- **Your Top Picks.** Lower down the page: the four highest-scoring open comps you have not registered for, each with its score, tags, prize and days left. Click a card and it opens in Competitions with the score breakdown.
- **Rotating banner.** One comp per angle, sliding every few seconds: the open flagship, best ROI (prize and internship against rounds and registrations), most reachable (fully online with the fewest rounds and registrations), closing soon, biggest prize, internship on offer, least crowded and new this week. A comp appears once, hovering pauses it, and the arrows or a swipe move it by hand.
- **At a Glance.** Four counts you can tap: your registrations, comps closing within 7 days, internship chances, case comps.
- A strip under the banner asks you to sign in or set up your profile while either is missing.
- The card at the bottom of the sidebar shows when the data was last synced and has the **Refresh now** button.

Labels, buttons, chips and short facts are written in Title Case, and full sentences keep sentence case. Once sign-in is on, the top right holds your account.

Organiser logos load from Unstop's servers, so they need internet; without it each comp shows its initials instead. The two banner photos are AI-generated and embedded in `assets.css`.

### Discover
Every open comp as a card, scored 0 to 100. One card per row, and every card has the same blocks at the same widths, so the columns line up down the page: organiser, time left and the bookmark on top, then the title, then one line of tags (internship chance first, why you can't enter, fits your course), then a single strip with the prize band and entry fee, Registered, Score, Details, Hide, Apply and Track. A long title takes a second line and the card grows by that one line, nothing else moves. Team size and the stages sit under Details.

**Views.** A block of 14 one-tap views sits above the list, in rows of even length that fill the width: Open to Me, High Priority, your main comp type (Case Competitions on the business list), IIM Online, IIT Online & your city, Top B-Schools, Other B-Schools, DU & New-Age, Consulting & Finance, Low-Effort Corporate, Internship & PPO, ₹1 Lakh+ Prizes, Closing This Week and All Listings. Hover a view to read exactly what it covers, and a view with nothing in it is dimmed. The first and the last choose the pool. The twelve between them can be lit together: a chip above the list then offers **Any** (a comp that fits at least one lit view) or **All** (a comp that fits every lit view, with the organiser views counted as one). The side filters narrow whatever the views show. On a phone the views are one row that scrolls sideways. A small copy button in the corner of every card copies the comp's name, organiser, deadline, prize, team size and link as plain text, ready to paste in a chat.

**Ranked for each person.** Signed out, everyone sees the same general list. After the first sign-in a person answers three short questions: course, comp types and city. Business types keep the business ranking described below. Someone who picks mostly tech types gets a tech ranking instead (IITs, NITs, IIITs and BITS on top, tech domains count), where business case comps rank lower and are never hidden, and coding contests are no longer hidden by default. A picked type adds a few points. Comps run only by other B-schools (MDI, Great Lakes, IMT, IMI and similar) stay out of the main list unless a company brand or another known organiser is behind them. The Other B-Schools view brings them in, and search finds them too. NIT, IIIT and Delhi tech campuses count on the business list only for a case, B-plan or simulation comp.

Every filter applies together, and each one that is on shows as a chip above the list that you can remove on its own. **Sort By** orders by score, deadline, prize, fewest or most registered, fewest rounds, internship first or newest.

- **My List.** Three switches that use your own marks: Only Starred, Hide Registered, Show Hidden.
- **Prize & Internship.** A minimum prize pool, and internship chances: any, confirmed in the prizes, PPI (interview) or PPO (job offer). A solid amber flag on a card means the chance is written into the prize list, an outlined one means it is only mentioned in the description.
- **Participants & Rounds.** Registrations at most and at least, and a cap on rounds.
- **Circuits.** DU Circuit, IIMs IITs & Premier, Corporate & Global, Others.
- **Categories.** The comp type, the same one shown as a tag on each card: simulations & mock stock, case & strategy, B-plan & pitch, hackathons, cybersecurity & CTF, data & AI, coding contests, robotics, design, research, quizzes, debates & MUNs, writing, sports & gaming, arts & culture.
- **Participation** (solo OK or team) and **Entry Fee** (free or paid).
- **Fits My Course.** The course in your profile maps to domains (BBA to marketing, finance, consulting and so on, B.Tech to tech, product and analytics). Matching comps carry a Fits flag, and the profile dialog lists the domains for the course you pick.

- **Eligibility.** On your own computer the profile is filled in from `config.json`. On the public link everyone sets their own under Profile. Comps you can't enter disappear from every view: wrong course or batch, school-only, women-only, MBA-only, limited to a list of colleges that does not include yours, or same-college teams if you said you cannot form one.
- **Where it happens.** The reader labels every sentence that has in-person wording: must attend, optional, vague, negated ("no travel needed"), about offline as a case topic, or only the judging being offline. The verdict and the sentences are under "Why NN?" on each card.
  - IIM comps are strict: any in-person wording at all rejects them.
  - In-person comps in your own city are kept (Delhi NCR counts Delhi, Gurugram, Noida and the rest of NCR). Anything else must be fully online. One switch under "Where It Happens" chooses between **Online and Nearby** and **Everything**, and **Fine Tune** under it holds the separate tick-boxes.
  - "Unclear" and "brand-run with an in-person stage" are separate buckets, switched off by default. Tick them under "Where it happens" to see them.
- **Organiser.** One tick-box per group: IIM, IIT, FMS Delhi, ISB, top B-schools (XLRI, SPJIMR, MDI, IIFT …), NMIMS & Christ, DU top colleges, St. Xavier's, BITS Pilani, Ashoka & liberal-arts universities, Masters' Union, strategy firms (McKinsey / Bain / BCG …), Big 4 & Accenture, banks and finance firms, any other known brand. A group with nothing open shows 0.
- **Format.** Coding contests, hackathons and pure-tech comps (robotics, CTFs, data-science contests) are hidden by default. A business comp that only touches tech (an AI-themed case, a fintech pitch) stays. Untick "Hide coding contests & hackathons" to see them. "Case, strategy and pitch comps only" narrows further by removing quizzes and cultural events. The title words that mark a comp as coding are in `config.json` under `format.coding_title`.
- **Hide.** The eye button hides a comp for now. The line above the list shows how many are hidden, with **Show them** and **Unhide all**.
  - If the listing says travel or stay is covered, the card says so.
- **Round 1 asks for.** Quiz, deck, video, code, live presentation. Each card also lists every stage with its type and dates.
- **Star** a comp (the bookmark on the card) and it waits under **Starred** in the sidebar (the Starred tab on a phone). **Track** moves it to your tracker, and from then on its dates show in My Registrations on Home.

### My registrations
Replaces the spreadsheet. Dates come from Unstop on every refresh, so you never type one.

- Each comp shows its stages (quiz, deck, presentation …) with dates. A stage reads **N/A** and is locked until it opens on Unstop (its start date arrives; if a stage has no date, when the stage before it is done). From then on you set its status: Pending, Done / submitted, Cleared, Not cleared, Skipped. Plus an outcome, your team name and an optional note.
- **Team name.** Type it once and it locks: it turns into a label with no text box, and it also shows beside the organiser at the top of the comp. Only the pencil on its right unlocks it, then Save (or Enter) locks it again and Cancel (or Esc) keeps the old name. It syncs with the rest of your registrations.
- **Calendar.** One row per comp, one horizontal bar per stage, coloured by type (quiz, deck, presentation …). Stages that have not opened yet are drawn hatched. The glowing line is today, the diamond at the end of a bar is its deadline, and a day where two comps have something due is highlighted as a clash. Click a bar to jump to that comp.
- **High / Normal / Low** is your own priority. **Hide for now** takes a comp out of the list, the calendar and the reminders without deleting anything. It waits under **Hidden**, where you can unhide it or press **Unhide all**. **Remove** is the one that deletes.
- Paste an Unstop link to add something you registered for earlier, including comps whose registration has already closed.

### Flagship watchlist
Big annual comps followed by name all year, in two sections: Indian flagships (Tata Imagination Challenge, HUL L.I.M.E., Reliance T.U.P. …) and international ones (Brandstorm, Hult Prize, CFA Research Challenge, Global Case Competition at Harvard, Undergrad Case Competition World Cup, Schneider Go Green, HSBC Business Case Programme, CME Trading Challenge, Red Bull Basement). For each one you see whether it is open, when the last edition ran, when the next is expected, and whether you could have entered the last edition. Comps that run on their own site show their usual window and a link. Add your own by name in the tab, or edit `watchlist.json`.

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
2. On the empty repository page choose "uploading an existing file", drag in everything from this folder, and commit.
3. Open Settings, then Pages, and set Source to **GitHub Actions**.
4. Check that `.github/workflows/refresh.yml` reached the repository. Drag and drop often skips folders whose name starts with a dot. If it is missing, choose Add file, then Create new file, type `.github/workflows/refresh.yml` as the name, paste the contents of that file and commit.

That commit starts the first run. About four minutes later the dashboard is live at `https://YOUR-USERNAME.github.io/mystop/`.

After that `.github/workflows/refresh.yml` pulls fresh data from Unstop every three hours (6 am, 9 am, noon and so on, IST) and after every change to the repository, then republishes. If Unstop cannot be reached, it publishes the `dashboard.html` stored in the repository instead.

What is different on the GitHub link:

- Until sign-in is switched on (next section), your registrations, stars and hidden comps are saved in the browser you use, so your phone and your laptop each keep their own list.
- There is no Refresh button, the schedule does it. For an extra refresh press Run workflow on the Actions tab.
- A comp can be added to the tracker by link only while it is open on Unstop.
- To follow another flagship comp, add it to `watchlist.json` in the repository.
- The profile in `config.json` is only the default on your own computer. On the public link a visitor who is not signed in sees one general list: every comp that can be done online, scored, with nothing assumed about course or city. Right after the first sign-in MyStop asks three short questions (course, comp types, city) and ranks the list for that person. Each question can be skipped.

GitHub pauses scheduled runs after 60 days without a commit and emails you first. One click on the Actions tab turns them back on.

## Sign-in on every device

Sign-in is optional. It uses Google sign-in through Firebase (free). Once it is on, anyone can sign in with their own Google account, a college account included, and gets their own registrations, stars, hidden comps and profile on every device. Signed out, MyStop works as before and keeps everything in the browser.

Set it up once, all in the browser:

1. Open `console.firebase.google.com`, sign in, press **Create a project**, name it `mystop`, switch Google Analytics off, press **Create project**. If a college account is refused here, use a personal Gmail. This only decides who owns the project, not who can sign in to MyStop.
2. In the left menu open **Build**, then **Authentication**, press **Get started**, choose **Google**, switch **Enable** on, pick your email as the support email, press **Save**.
3. Still in Authentication open the **Settings** tab, then **Authorized domains**, press **Add domain**, type `YOUR-USERNAME.github.io`, press **Add**.
4. In the left menu open **Build**, then **Firestore Database**, press **Create database**, pick the Mumbai location (`asia-south1`), choose **Start in production mode**, press **Create**.
5. Open the **Rules** tab of Firestore, delete what is there, paste the rules below, press **Publish**.
6. Press the gear next to **Project Overview**, then **Project settings**. Under **Your apps** press the `</>` icon, type `mystop` as the nickname, leave Hosting unticked, press **Register app**. Firebase shows a block that starts with `const firebaseConfig = {`. Copy that block.
7. On GitHub open `signin.txt` in the repository, press the pencil, paste the block under the comment lines, press **Commit changes**.

About four minutes later the link shows a **Sign In** button top right.

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /users/{uid} {
      allow read, delete: if request.auth != null && request.auth.uid == uid;
      allow create, update: if request.auth != null && request.auth.uid == uid
        && request.resource.data.keys().hasOnly(['state', 'ts', 'name'])
        && request.resource.data.state is string
        && request.resource.data.state.size() < 300000;
    }
    match /tracked/{uid} {
      allow read: if true;
      allow delete: if request.auth != null && request.auth.uid == uid;
      allow create, update: if request.auth != null && request.auth.uid == uid
        && request.resource.data.keys().hasOnly(['ids'])
        && request.resource.data.ids is list
        && request.resource.data.ids.size() <= 80;
    }
    match /public/tracked {
      allow read: if true;
      allow write: if false;
    }
  }
}
```

What the rules mean:

- `users`: each person can read, change and delete only their own record, and a record cannot grow past a fixed size.
- `tracked`: each person has their own short list of competition numbers (80 at most) that only they can change. It holds nothing else, and anyone can read it, so the scheduled refresh can keep a registered comp up to date after it leaves Unstop's open list. The refresh ignores anything that is not a plain number and stops at 300 numbers in total.
- `public/tracked`: the shared list used before version 13. Nobody can write to it any more. It is only read until the new lists exist.

Keep these three settings as they are, they are what stops misuse:

1. **Authorized domains** (Authentication, Settings): only `YOUR-USERNAME.github.io` and the two `firebaseapp.com` / `web.app` entries Firebase adds itself. Remove `localhost` if it is listed.
2. **Plan**: stay on the free Spark plan and do not add a card. With no card, heavy use can only pause sign-in for the day, it can never cost money.
3. **Rules**: whenever this README changes the rules above, paste the new ones and press **Publish**.

## Terms, privacy and deleting data

- **Terms and Privacy** opens from the foot of every page and from the account menu. Before the first sign-in a person ticks that they are 18 or older and accept the terms. Using MyStop without signing in needs no agreement, because nothing leaves the browser.
- **Delete My Data** in the account menu erases the account record, the tracked list and the sign-in itself. **Erase This Browser's Data** on the Terms page clears a browser that never signed in.
- The page carries a Content Security Policy: only its own script and Google's sign-in files may run, so text from a listing can never run as code.
- The refresh identifies itself to Unstop as `MyStop/1.0` with a link to this repository, and reads only the public listing pages that Unstop's `robots.txt` allows.
- MyStop is unofficial. If Unstop or an organiser asks for a listing to be removed, do it promptly.

Good to know:

- The values in `signin.txt` are meant to be public. Every Firebase website ships them to the browser. The rules above are what protect the data. GitHub may still email a "secret detected" notice about the API key, which you can close as "used in tests" or ignore.
- The first sign-in on a device moves whatever that device already had into the account. Signing out empties the device and leaves the account untouched.
- With sign-in on, a comp that has already closed can be added by link in Registrations. Its details arrive at the next refresh.

## Other sources

- **InsideKampus** is switched off from version 13 (`sources.insidekampus` in `config.json`). MyStop reads Unstop only.
- **Official pages** of corporate and international challenges do not share a format, so they are watched instead of listed: give a watchlist entry a `url` and each refresh checks that page for registration wording and for changes. `group` set to `global` puts the entry in the International section and `when` is the one line shown about its usual window.

## Files

| File | Purpose |
| --- | --- |
| `radar.py` | Fetching, change tracking, watchlist checks, the local server |
| `model.py` | The reader: location, stage types, global evidence, internship, eligibility, score |
| `config.json` | All rules and weights: college lists, brands, sentence patterns, niches, scoring |
| `watchlist.json` | The flagship list |
| `signin.txt` | The Firebase web config that switches Google sign-in on. Empty means no sign-in |
| `template.html` | The dashboard. `dashboard.html` is this plus the data and the font |
| `fonts.css` | The Inter and Plus Jakarta Sans typefaces, embedded so the dashboard needs no internet. Delete it and the dashboard falls back to your system font |
| `assets.css`, `assets/` | The two banner photos, embedded, and their originals |
| `my/state.json` | Your profile, stars, hidden comps, tracker and read marks. Back this up. `my/state.backup.json` is the previous save |
| `cache/` | Downloaded listings, the previous snapshot (`history.json`) and the notification log (`events.json`). Safe to delete; it rebuilds |
| `data.json` | The same data the dashboard uses, for your own scripts |

## Scoring in one paragraph

Organiser prestige (IIM, IIT, FMS, ISB, top B-schools, top DU colleges, Masters' Union, strategy firms, Big 4, banks, other known brands) up to 44; business niche up to 10; case or pitch format 5, and the same 5 for a simulation, mock stock or trading format (the words that count are in `config.json` under `format.sim`); internship 15 if it is in the prize list, 7 if a sentence offers it to winners; prize money up to 15; fewer rounds and fewer registrations add points, many rounds and thousands of registrations subtract. High is 55 and above, medium 35 and above. Every card shows its own breakdown. Change any of it in `config.json`, then run `python radar.py --offline`.

## Limits worth knowing

- The reader works from the listing text. Organisers who write nothing about the finale get the benefit of the doubt when Unstop lists the comp as online. Open the listing before you commit.
- Expected opening dates on the watchlist are last edition's date plus a year. Treat them as a rough guide.
- A comp is matched to the watchlist by name. If a brand renames its competition, add the new name.
- College matching compares the words in your college name with Unstop's list. If a restricted comp you can enter is hidden, check the spelling against Unstop's name for your college.
