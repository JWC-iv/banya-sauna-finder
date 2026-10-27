"""
Step 2 of the data pipeline: cheap rules (no AI, no web requests) that throw out obvious non-saunas.

Reads data/raw/overture_us.parquet and data/raw/osm_us.json from step 1.
Writes data/raw/prefiltered.json: one record per place, in a common shape, each with a
"why" note saying which rule kept it. Rejected places go to data/raw/rejected_sample.json
(a sample, for spot-checking the rules).

Run from the project folder:  py scripts/prefilter.py
"""
import json
import random
import re
from collections import Counter
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

# A name that says this outright is kept no matter what its category is.
STRONG_NAME = re.compile(
    r"\bsaunas?\b|\bbanyas?\b|bath ?house|\bhammam|\bhamam\b|jjimjil|jimjil|\bonsen\b|\bsento\b|"
    r"contrast therap|cold plunge|korean spa|social wellness|thermal spa|steam bath|steam room|bathing club",
    re.I)

# Categories that can be a sauna venue. Places in other categories need a strong name.
KEEP_CATEGORIES = {
    # hot_springs is left out on purpose: a hot spring is not a sauna unless its name says so.
    "sauna", "public_bath_house", "health_spa", "day_spa", "spa",
    "korean_spa", "bath_house", "cryotherapy", "float_spa", "wellness_center",
}

# Words that mean "not a sauna venue" even when the category is spa-like.
NOISE = re.compile(
    r"\bnails?\b|lash|brow|wax|threading|salon|barber|hair|tanning|tattoo|"
    r"med ?spa|medspa|medical spa|aesthetic|botox|injectable|laser|dermatolog|cosmetic|plastic surg|"
    r"\bfacial|skin ?care|skin ?clinic|beauty|massage envy|hand ?& ?stone|"
    r"\bdogs?\b|\bpets?\b|grooming|\bpaws?\b|car ?wash|auto spa|"
    r"pool ?(and|&) ?spa (supply|service)|hot tub (store|sales|repair)|spa (store|supply|covers|repair|service)|"
    r"sauna (store|sales|builder|install)|plumbing|remodel|bathroom|kitchen|cabinet|"
    r"apartment|condo|residence|senior living|"
    r"inn\b|hotel|resort|motel|suites\b|lodge\b",
    re.I)

# Strong names that are still noise (sauna makers and dealers, adult venues).
STRONG_NOISE = re.compile(r"sauna (store|sales|builder|supply|kits?|install|direct|depot|world|shop|center|co\b)|"
                          r"infrared sauna (store|sales)|hot tubs?|swim spas?|saunas? (&|and) (spas|cellars|woodwork)|"
                          r"\bdogs?\b|\bpets?\b|\bpaws?\b|groom|cabin|cottage|chalet|condo|rental|retreat w|"
                          r"realty|real estate|capital|apartments?", re.I)
NOISE_CATEGORIES = {"pet_groomer", "animal_or_pet_service", "holiday_rental_home", "cabin", "apartment", "hotel",
                    "hot_tub_and_pool_store", "pool_cleaning", "furniture_store", "contractor", "real_estate_agent",
                    "real_estate_service", "lodging", "resort", "motel", "bed_and_breakfast"}


def overture_rows():
    path = (RAW / "overture_us.parquet").as_posix()
    con = duckdb.connect()
    cur = con.execute(f"SELECT * FROM '{path}' WHERE coalesce(operating_status, 'open') <> 'permanently_closed'")
    cols = [d[0] for d in cur.description]
    for r in cur.fetchall():
        r = dict(zip(cols, r))
        yield {
            "source": f"overture:{r['id']}",
            "name": r["name"], "category": r["category"],
            "lat": r["lat"], "lng": r["lng"],
            "address": r["address"], "city": r["city"], "state": r["state"], "zip": r["zip"],
            "website": r["website"], "phone": r["phone"],
            "confidence": r["confidence"],
        }


def osm_rows():
    path = RAW / "osm_us.json"
    if not path.exists():
        return
    for el in json.loads(path.read_text(encoding="utf-8")):
        t = el.get("tags", {})
        if t.get("access") in ("private", "no") or not t.get("name"):
            continue  # private saunas (homes, apartment buildings) and unnamed ones are not venues
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lng = el.get("lon") or el.get("center", {}).get("lon")
        yield {
            "source": f"osm:{el['type']}/{el['id']}",
            "name": t.get("name"), "category": "osm_" + (t.get("leisure") or t.get("amenity") or "sauna"),
            "lat": lat, "lng": lng,
            "address": " ".join(x for x in [t.get("addr:housenumber"), t.get("addr:street")] if x) or None,
            "city": t.get("addr:city"), "state": t.get("addr:state"), "zip": t.get("addr:postcode"),
            "website": t.get("website") or t.get("contact:website"), "phone": t.get("phone") or t.get("contact:phone"),
            "confidence": None, "osm_hours": t.get("opening_hours"),
        }


def judge(row):
    """Return (keep, reason)."""
    name = row["name"] or ""
    cat = row["category"] or ""
    if not name or row["lat"] is None:
        return False, "no name or location"
    if STRONG_NOISE.search(name) or cat in NOISE_CATEGORIES:
        return False, "seller, builder, rental, hotel or pet business"
    if STRONG_NAME.search(name):
        return True, "name says sauna/bathhouse"
    if cat.startswith("osm_"):
        return True, "tagged as sauna in OpenStreetMap"
    if cat not in KEEP_CATEGORIES:
        return False, f"category {cat}"
    if NOISE.search(name):
        return False, "name looks like salon, med spa, hotel or store"
    if not row["website"]:
        return False, "spa-type place with no website to check"
    return True, f"category {cat} with website"


if __name__ == "__main__":
    kept, rejected = [], []
    reasons = Counter()
    for row in list(overture_rows()) + list(osm_rows()):
        keep, why = judge(row)
        reasons[("kept: " if keep else "dropped: ") + why.split(" with ")[0]] += 1
        row["why"] = why
        (kept if keep else rejected).append(row)
    (RAW / "prefiltered.json").write_text(json.dumps(kept, indent=1, default=str), encoding="utf-8")
    random.seed(1)
    sample = random.sample(rejected, min(300, len(rejected)))
    (RAW / "rejected_sample.json").write_text(json.dumps(sample, indent=1, default=str), encoding="utf-8")
    print(f"Kept {len(kept)}, dropped {len(rejected)}")
    for k, n in reasons.most_common(25):
        print(f"  {n:7d}  {k}")
