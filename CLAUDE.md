# Banya Press Sauna Finder

## What this is
A map-based directory of US saunas, embedded as a page on banyapress.com.
- banyapress.com is a **Squarespace** site run by Banya Press (sauna-themed books and merch). The finder must match its look: logo, fonts and colors come from the live site, so pull them from there.
- Layout reference is the Bachan's store locator (https://bachans.com/pages/find-us): address search bar on top, tabs to switch between **List** and **Map**, simple result cards (name, address, distance, phone, one accent link), logo-style map pins on a light, low-contrast basemap. Copy the layout, not their branding.

## Who you're working with
John is building this and is new to web development. Explain each step in plain language: what a file is for, what a command does, and why. No unexplained jargon. Before any step that touches the live Squarespace site, stop and say exactly what will change.

## Scope
- **Include** these venue types: `bathhouse`, `banya`, `korean_spa`, `sauna_studio`, `contrast_therapy`, `mobile_or_floating_sauna`, `day_spa_day_pass` (only spas that sell a sauna-access day pass).
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
heat_types         array    traditional_electric | wood_fired | infrared | steam | smoke | banya
cold_plunge        enum     none | tub | pool | natural_water | unknown
access             enum     walk_in | reservation_required | membership_only | unknown
gender_policy      enum     coed | segregated | both | unknown
session_type       enum     communal | private | both | unknown
banya_approved     true|false|null    editorial; null = not yet reviewed
banya_approved_notes, banya_approved_date
# collected later, not filters at launch:
day_pass_price_usd number|null
attire             enum     swimsuit | towel | nude | mixed | unknown
extras             array    aufguss | venik | massage | food | outdoor
# provenance (required on every venue):
sources            array    e.g. ["overture:<id>", "website", "manual"]
last_verified      date
```
Never store data from the Google Places API except place_id. Google's terms forbid caching other fields beyond 30 days.

## Launch filters
Venue type, heat type, cold plunge, access, gender policy, session type, open now, **Banya Approved**.
- A filter only ships once its field is filled (not `unknown`) for at least 90% of published venues. `scripts/coverage.py` reports this.
- **Banya Approved** criteria are TBD by the owner. The filter is controlled by `SHOW_BANYA_APPROVED` in the site config and stays hidden until enough venues are reviewed.

## Data pipeline (`scripts/`)
1. `pull_candidates.py`: query the open datasets for US places with sauna-related categories or names (sauna, banya, bathhouse, bath house, spa, hammam, jjimjilbang, contrast therapy, cold plunge). Output `data/raw/candidates.json`. First list the distinct matching category values and show them to John before filtering.
   - Overture Maps Places (CDLA-Permissive-2.0): DuckDB over the public S3 bucket. Use the latest release.
   - Foursquare OS Places (Apache 2.0): gated download on Hugging Face, so John must accept the terms.
   - OpenStreetMap via Overpass (`leisure=sauna`, `sauna=*`). ODbL is share-alike, so keep OSM-derived rows flagged in `sources`; their license is a decision for later.
2. `dedupe.py`: merge records with similar names within about 150 m.
3. `classify.py`: assign `venue_type`, route gyms to `data/parked/`, and drop hotels.
4. `enrich.py`: fetch each venue's own website and extract the schema fields. Record the source URL per field. Anything not clearly stated becomes `unknown`; never guess.
5. `validate.py`: check required fields, enum values, US bounding box, and duplicate ids. This runs before every publish.
6. `coverage.py`: fill rate per filter field.

## Testing workflow
- Work locally first: serve `site/` with a local web server and test in the browser pane.
- Use `data/sample_atlanta.json` as the fixture while building the UI. It does not exist yet: no Atlanta list has been collected, so it has to be built (candidates drafted, then checked by John).
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
- [ ] Create the GitHub repo and turn on Pages (name and public/private not decided yet).
- [ ] Atlanta sample dataset
- [ ] UI prototype (Bachan's layout, Banya Press styling)
- [ ] National candidate pull
- [ ] Enrichment and coverage report
- [ ] Banya Approved criteria (owner decides)
