"""
Step 1 of the data pipeline: find every US place that might be a sauna venue.

Pulls from two free, open datasets and saves the raw results to data/raw/:
  - Overture Maps Places (CDLA-Permissive-2.0), read straight from Overture's public S3 bucket with DuckDB.
  - OpenStreetMap via the Overpass API (ODbL, share-alike: rows stay flagged "osm:" in sources).

It also writes data/raw/category_report.txt, the list of place categories that matched, so John can
decide which categories to keep before anything is filtered out.

Run from the project folder:  py scripts/pull_candidates.py
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

import duckdb
import truststore

# Use Windows' own certificate store; Python's bundled one rejected these sites as expired.
truststore.inject_into_ssl()

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OVERTURE_RELEASE_CATALOG = "https://stac.overturemaps.org/catalog.json"
USER_AGENT = "banya-sauna-finder/0.1 (github.com/JWC-iv/banya-sauna-finder)"

# Words in a place's name that suggest sauna access.
NAME_PATTERN = (
    r"sauna|banya|bathhouse|bath house|hammam|hamam|jjimjil|jimjil|onsen|sento|"
    r"contrast therap|cold plunge|thermal|hot spring|soak|steam room|sweat ?lodge|"
    r"korean spa|day spa|\bspa\b|wellness club|bathing"
)
# Words in a place's category that suggest sauna access.
CATEGORY_PATTERN = r"sauna|spa|bath|hot_spring|plunge|cryo|float|thermal|onsen"


def latest_overture_release():
    with urllib.request.urlopen(OVERTURE_RELEASE_CATALOG) as r:
        return json.load(r)["latest"]


def pull_overture():
    release = latest_overture_release()
    print(f"Overture release {release}: scanning US places (this reads a few GB and takes a while)...")
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; SET s3_region='us-west-2';")
    src = (f"read_parquet('s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*', "
           "hive_partitioning=1)")
    out = RAW / "overture_us.parquet"
    con.execute(f"""
        COPY (
          SELECT id, names.primary AS name, taxonomy.primary AS category, taxonomy.alternates AS alt_categories,
                 basic_category, addresses[1].freeform AS address, addresses[1].locality AS city,
                 addresses[1].region AS state, addresses[1].postcode AS zip,
                 websites[1] AS website, phones[1] AS phone, socials,
                 ST_Y(geometry) AS lat, ST_X(geometry) AS lng, confidence, operating_status
          FROM {src}
          WHERE bbox.xmin BETWEEN -180 AND -65 AND bbox.ymin BETWEEN 17 AND 72
            AND addresses[1].country = 'US'
            AND (regexp_matches(lower(names.primary), '{NAME_PATTERN}')
                 OR regexp_matches(lower(coalesce(taxonomy.primary, '') || ' ' ||
                    array_to_string(coalesce(taxonomy.alternates, []), ' ')), '{CATEGORY_PATTERN}'))
        ) TO '{out.as_posix()}' (FORMAT parquet)
    """)
    n = con.execute(f"SELECT count(*) FROM '{out.as_posix()}'").fetchone()[0]
    print(f"Overture: {n} rows saved to {out}")
    return release


def pull_osm():
    # US split into boxes so each Overpass request stays small enough not to time out.
    boxes = []
    for south in range(24, 50, 6):
        for west in range(-125, -66, 10):
            boxes.append((south, west, min(south + 6, 50), min(west + 10, -66)))
    boxes += [(51, -180, 72, -129), (18, -161, 23, -154)]  # Alaska, Hawaii
    elements = {}
    for i, (s, w, n, e) in enumerate(boxes, 1):
        bbox = f"{s},{w},{n},{e}"
        query = (f'[out:json][timeout:180];('
                 f'nwr["leisure"="sauna"]({bbox});nwr["sauna"]({bbox});'
                 f'nwr["amenity"="public_bath"]({bbox});nwr["bath:type"]({bbox}););out center tags;')
        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    "https://overpass-api.de/api/interpreter",
                    data=urllib.parse.urlencode({"data": query}).encode(),
                    headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=240) as r:
                    for el in json.load(r)["elements"]:
                        elements[f"{el['type']}/{el['id']}"] = el
                break
            except Exception as err:
                print(f"  OSM box {i}/{len(boxes)} attempt {attempt + 1} failed: {err}")
                time.sleep(30)
        print(f"  OSM box {i}/{len(boxes)} done, {len(elements)} places so far")
        time.sleep(5)  # be polite to the free Overpass server
    out = RAW / "osm_us.json"
    out.write_text(json.dumps(list(elements.values()), indent=1), encoding="utf-8")
    print(f"OSM: {len(elements)} places saved to {out}")


def category_report(release):
    con = duckdb.connect()
    path = (RAW / "overture_us.parquet").as_posix()
    rows = con.execute(f"SELECT name, category FROM '{path}'").fetchall()
    strong = re.compile(r"sauna|banya|bathhouse|bath house|hammam|jjimjil|jimjil|onsen|sento|cold plunge|contrast therap")
    all_counts = Counter(c or "(none)" for _, c in rows)
    strong_counts = Counter(c or "(none)" for n, c in rows if n and strong.search(n.lower()))
    lines = [f"Overture release {release}. {len(rows)} US places matched a sauna-related name or category.", "",
             "Categories of places whose NAME clearly says sauna/banya/bathhouse/etc:",
             *[f"  {c:45s} {k}" for c, k in strong_counts.most_common()], "",
             "All matched categories (top 80):",
             *[f"  {c:45s} {k}" for c, k in all_counts.most_common(80)]]
    out = RAW / "category_report.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Category report saved to {out}")


if __name__ == "__main__":
    RAW.mkdir(parents=True, exist_ok=True)
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    release = None
    if which in ("all", "overture"):
        release = pull_overture()
        category_report(release)
    if which in ("all", "osm"):
        pull_osm()
