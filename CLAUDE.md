# Banya Press Sauna Finder

## What this is
A map-based directory of US saunas, embedded as a page on banyapress.com.
- banyapress.com is a **Squarespace** site run by Banya Press (sauna-themed books and merch). The finder must match its look: logo, fonts and colors come from the live site, so pull them from there.
- Layout reference is the Bachan's store locator (https://bachans.com/pages/find-us): address search bar on top, tabs to switch between **List** and **Map**, simple result cards (name, address, distance, phone, one accent link), logo-style map pins on a light, low-contrast basemap. Copy the layout, not their branding.

## Who you're working with
John is building this and is new to web development. Explain each step in plain language: what a file is for, what a command does, and why. No unexplained jargon. Before any step that touches the live Squarespace site, stop and say exactly what will change.

## Scope
- **Include** these venue types: `bathhouse`, `banya`, `korean_spa`, `sauna_studio`, `contrast_therapy`, `mobile_or_floating_sauna`, `day_spa_day_pass` (only spas that sell a sauna-access day pass).
- **The rule (John, 2026-10-27): if you can't sit in a heated room, it's out.** Infrared sauna cabins count, including at wellness and recovery clinics (Restore Hyper Wellness, iCRYO and similar). Infrared blankets, capsules, pods and domes with your head outside do not. Places not open yet are out.
- **Exclude hotels.** Do not store them.
- **Gyms are parked, not discarded.** `gym` is a valid `venue_type` that the public page filters out. Write gym candidates found by the pipeline to `data/parked/gyms.json` so they can be added later without redoing the pipeline.

## Architecture
- `site/` holds the finder: one HTML/CSS/JS page with no build step. It gets pasted into a Squarespace **Code Block**, which requires a Squarespace plan that allows custom JavaScript. Confirm the plan first.
- `data/venues.json` is the published dataset. It is hosted outside Squarespace (GitHub Pages) and fetched by the page. All filtering runs in the browser.
- Map: MapLibre GL JS with OpenFreeMap tiles (free, no API key; chosen 2026-10-27). If we ever switch to a keyed provider, the key is public in front-end code, so restrict it to banyapress.com and localhost.
- Later, accounts and reviews will move the data to a backend (likely Supabase). Keep the page's data loading in one function so that swap is small.

## Banya Press styling (read from banyapress.com, 2026-10-27)
- Background (sand): `#EBCEAD` (Squarespace `--siteBackgroundColor`, hsl 32 61% 80%).
- Card/panel (light stone): `#E4DBCE` (hsl 37 29% 85%), used for forms and summary blocks.
- Text, links and buttons: black `#000000`; secondary gray `#3E3E3E`. Buttons are black with sand text.
- Headings: `etna` (Adobe Fonts, weight 300, slight negative letter-spacing). It is loaded by Squarespace and licensed for banyapress.com only, so the finder should not load it itself; inherit it on the live page and fall back to a sans-serif locally.
- Body and nav: `Labrada` weight 300 (Google Font, OK to load).
- Logo: handwritten "Banya Press" wordmark, https://images.squarespace-cdn.com/content/v1/6936dad043a4ac5e3ffeba44/35d71dd8-a3d9-4372-bc89-4783a04a8c0b/Banya-Logo-03.png (1359x335). There is no icon-only version; map pins need one designed.
- Feel: warm, minimal, lots of space, hand-drawn line illustrations, black-and-white photos.

## Venue schema (one object per venue in venues.json)
```
id                 string   stable slug, e.g. "atl-fuse-bathhouse"
name               string
venue_type         enum     see Scope
lat, lng           number
address, city, state, zip
phone, website     string|null
hours              OSM opening_hours syntax|null
heat_types         array    traditional | wood_fired | infrared | steam | smoke | banya
                            (traditional = dry Finnish-style sauna, heater unstated or electric)
cold_plunge        enum     none | tub | pool | natural_water | yes_unspecified | unknown
outdoor            true|false|null    outdoor sauna or outdoor bathing area
access             enum     walk_in | reservation_required | membership_only | unknown
session_type       enum     communal | private | both | unknown
gender_policy      enum     coed | segregated | both | women_only | men_only | unknown
banya_approved     true|false|null    editorial; null = not yet reviewed
banya_approved_notes, banya_approved_date
# collected later, not filters at launch:
day_pass_price_usd number|null
attire             enum     swimsuit | towel | nude | mixed | unknown
extras             array    aufguss | venik | massage | food
# provenance (required on every venue):
sources            array    e.g. ["overture:<id>", "website", "manual"]
last_verified      date
```
Never store data from the Google Places API except place_id. Google's terms forbid caching other fields beyond 30 days.

## Launch filters (decided 2026-10-27)
Built around three visitor questions: can I go today, what kind of heat, what's the experience.
- **Quick toggles, always visible:** Open now · Walk-ins (`access = walk_in`) · Cold plunge (any value except none/unknown) · Wood-fired · Outdoor · Banya Approved.
- **"More filters" panel:** Type · Heat · Private or social (`session_type`).
- **Later, once data exists:** women-only hours, clothing-optional, rituals (aufguss, venik), price. Gender policy and attire are collected but are not launch filters; websites rarely state them clearly.
- A filter only ships once its field is filled (not `unknown`) for at least 90% of published venues. `scripts/coverage.py` reports this.
- **Banya Approved** criteria are TBD by the owner. The filter is controlled by `SHOW_BANYA_APPROVED` in the site config and stays hidden until enough venues are reviewed.

## Data pipeline (`scripts/`)
Plan chosen 2026-10-27 after reviewing other US sauna finders. The careful ones list about 1,000-1,700 real venues nationally; bigger counts include gyms, massage and pools. Target about 1,500 good venues, not raw volume.
1. `pull_candidates.py`: query the open datasets for US places with sauna-related categories or names (sauna, banya, bathhouse, bath house, spa, hammam, jjimjilbang, contrast therapy, cold plunge). Output goes to `data/raw/` (git-ignored, re-creatable). It writes `data/raw/category_report.txt`; show it to John before filtering.
   - Seed lists: names from curated sources (city "best saunas" articles, North American Sauna Society, Finlandia Foundation public sauna list) go in `data/seeds/` as leads only. Look each one up ourselves; never copy another directory's listings.
   - Overture Maps Places (CDLA-Permissive-2.0): DuckDB over the public S3 bucket. Use the latest release.
   - Foursquare OS Places (Apache 2.0): gated download on Hugging Face, so John must accept the terms.
   - OpenStreetMap via Overpass (`leisure=sauna`, `sauna=*`). ODbL is share-alike, so keep OSM-derived rows flagged in `sources`; their license is a decision for later.
2. `prefilter.py`: cheap rules, no AI. Drop obvious non-venues (nail, med spa, hotel, apartments, stores, contractors) and keep anything whose name clearly says sauna/banya/bathhouse.
3. `dedupe.py`: merge records with similar names within about 150 m.
4. `check_websites.py` (replaces separate classify and enrich steps): fetch each candidate's own website and ask Claude (Anthropic API) one question first: does this business sell sauna access to the public? Fails are dropped cheaply. Passes get `venue_type` and the schema fields, each with the URL and a short quote as evidence. Gyms go to `data/parked/`, hotels are dropped. Anything not clearly stated becomes `unknown`; never guess. Needs John's Anthropic API key in a git-ignored `.env` file, with a spending limit he sets.
   - Model: Claude Haiku 5.5, run as a batch job (decided 2026-10-27). In a 45-venue test it agreed with Opus 5.5 on 42/45 yes/no answers, its proof quotes were real, and it cost about 0.16 cents per site versus about 5 cents for Opus. Full US run estimated at about $3.
5. `validate.py`: check required fields, enum values, US bounding box, and duplicate ids. This runs before every publish.
6. `coverage.py`: fill rate per filter field.
7. Later: a "Submit your sauna / Suggest a fix" form so owners and visitors fill the unknowns (British Sauna Society model).
- Competitor counts (e.g. SaunaPals per city) may be used only as a recall check to find gaps in our own sources.

## Testing workflow
- Work locally first: the `finder` entry in `.claude/launch.json` runs `py -m http.server 8000` from the repo root; open http://localhost:8000/site/ in the browser pane.
- Use `data/sample_sf.json` as the fixture while building the UI: 7 San Francisco venues, fields filled only from each venue's own website (2026-10-27). It is test data and must never be published. John has no special local knowledge, so it is not hand-verified; real checking is `enrich.py`'s job.
- Test the real embed on a hidden or password-protected Squarespace page before linking it publicly.
- Commit to git after every working change, with messages in plain English.

## Status
- [x] Data sources chosen; scope and filters decided
- [x] Squarespace plan confirmed: Core, which allows JavaScript in Code Blocks
  - Code Block limit is 400 KB, so load the JS/CSS and data from GitHub Pages and keep the block a small loader snippet.
  - Code Block mode must be HTML, with scripts wrapped in script tags.
  - The code may not show while logged in to Squarespace. Test logged out, or use Preview in Safe Mode.
  - Don't put the finder on a page inside an index page, and turn Ajax loading off if it breaks rendering.
- [x] GitHub account exists (username `JWC-iv`). Use GitHub Pages to host `site/` assets and `data/venues.json`.
- [x] Git 2.56 and GitHub CLI (`gh`) 2.103 installed via winget (2026-10-27). Python 3.13 is installed (`py`). The project folder is a Git repo on branch `main`.
- [x] John is signed in to `gh` as JWC-iv. Commits in this repo use name "John" and the GitHub noreply email (set in the repo's own Git settings) so the personal email isn't published.
- [x] Public GitHub repo created: https://github.com/JWC-iv/banya-sauna-finder (remote `origin`, branch `main`). Push after each commit.
- [x] GitHub Pages is on (2026-10-27), serving the `main` branch root. Prototype: https://jwc-iv.github.io/banya-sauna-finder/site/ . Every push updates it within a minute or two.
  - Because Pages serves the whole repo, `data/sample_sf.json` is publicly reachable too. It is public-website facts only and the real finder never loads it, but keep anything private out of this repo.
- [x] Sample dataset: `data/sample_sf.json` (San Francisco, 7 venues; Atlanta dropped)
  - Schema gaps found: no `heat_types` value for a dry sauna whose heater type isn't stated (Kabuki, Onsen, Archimedes' Finnish room, Vital Ice), no `cold_plunge` value for "has one, type unknown", and no `gender_policy` value for women-only (Pearl is stored as `segregated`). Decide before `enrich.py`.
  - The Overpass (OpenStreetMap) API timed out from this PC on 2026-10-27; retry or use a different mirror for the national pull.
- [x] UI prototype (2026-10-27): `site/index.html` (local test page), `site/finder.js`, `site/finder.css`
  - finder.js loads its own CSS, the Labrada font and MapLibre 4.7.1, so the Code Block only needs a div, a config script and one script tag.
  - Filters are the `FILTERS` list at the top of finder.js. A filter hides itself below 90% coverage unless `showAllFilters: true` (set on the local test page).
  - Address search uses OpenStreetMap's free Nominatim geocoder. Fine for testing; revisit before real traffic (their policy limits heavy use).
  - "Open now" understands simple OSM hours like `Mo,We-Fr 12:00-23:00` and uses each venue's state to pick its time zone.
  - Map pin is a placeholder black drop with steam lines; owner may replace it.
- Other sauna directories checked 2026-10-27 (sauna-directory.pages.dev, saunaorplunge.pages.dev): they show Google ratings, which points to scraped Google Maps data, and they say "All rights reserved". Do not copy their data. SaunaTimes' public sauna map and the North American Sauna Society ambassador reviews are curated sources worth contacting about a partnership.
- [ ] National candidate pull (running 2026-10-27; Python needed the `truststore` package to trust Windows' certificates)
- [ ] Enrichment and coverage report
- [ ] Banya Approved criteria (owner decides)
