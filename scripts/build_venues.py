"""
Step 5 of the data pipeline: turn Claude's website answers into the published dataset.

Reads data/raw/checked.json (from check_websites.py collect). Writes:
  data/venues.json        venues the finder shows
  data/parked/gyms.json   gyms with public sauna access, kept for later
  data/evidence.json      the page URL and quote behind every filled field, by venue id
Hotels, places that don't sell sauna access and places that aren't open are dropped.

Run from the project folder:  py scripts/build_venues.py
"""
import datetime
import json
import re
import time
import urllib.request
from pathlib import Path

import truststore

truststore.inject_into_ssl()

USER_AGENT = "banya-sauna-finder/0.1 (github.com/JWC-iv/banya-sauna-finder)"
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
PUBLIC_TYPES = {"bathhouse", "banya", "korean_spa", "sauna_studio", "contrast_therapy",
                "mobile_or_floating_sauna", "day_spa_day_pass"}
FIELDS = ["heat_types", "cold_plunge", "outdoor", "access", "session_type", "gender_policy", "hours",
          "day_pass_price_usd", "attire", "extras"]


US_STATES = {"AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
             "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM",
             "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
             "WV", "WI", "WY", "PR"}
STATE_CODES = {"Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
               "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC",
               "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN",
               "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
               "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO",
               "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ",
               "New Mexico": "NM", "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH",
               "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
               "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
               "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI",
               "Wyoming": "WY", "Puerto Rico": "PR"}


def reverse_geocode(lat, lng, cache):
    """City, state and country for a point, from OpenStreetMap's free Nominatim service (1 request a second)."""
    key = f"{lat:.5f},{lng:.5f}"
    if key not in cache:
        url = (f"https://nominatim.openstreetmap.org/reverse?format=json&zoom=14&lat={lat}&lon={lng}")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as r:
            a = json.load(r).get("address", {})
        cache[key] = {"city": a.get("city") or a.get("town") or a.get("village") or a.get("hamlet") or a.get("suburb") or a.get("municipality") or a.get("county"),
                      "state": STATE_CODES.get(a.get("state")), "country": a.get("country_code")}
        time.sleep(1.1)
    return cache[key]


def slug(*parts):
    s = "-".join(p for p in parts if p)
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:80]


def clean_website(url):
    if not url:
        return None
    return url if "://" in url else "https://" + url


def to_venue(item, today):
    p, a = item["place"], item["answer"]
    v = {
        "id": slug(p.get("state"), p.get("city"), p["name"]),
        "name": p["name"],
        "venue_type": a["venue_type"],
        "lat": round(p["lat"], 6), "lng": round(p["lng"], 6),
        "address": p.get("address"), "city": p.get("city"), "state": (p.get("state") or "").upper()[:2] or None,
        "zip": (p.get("zip") or "")[:5] or None,
        "phone": p.get("phone") or a.get("phone"),
        "website": clean_website(p.get("website")),
    }
    for f in FIELDS:
        v[f] = a.get(f)
    v.update({"banya_approved": None, "banya_approved_notes": None, "banya_approved_date": None,
              "sources": p["sources"] + [f"website:{u}" for u in item["pages"][:5]],
              "last_verified": today})
    return v


if __name__ == "__main__":
    today = datetime.date.today().isoformat()
    checked = json.loads((RAW / "checked.json").read_text(encoding="utf-8"))
    geo_path = RAW / "reverse_geocode.json"
    geo_cache = json.loads(geo_path.read_text(encoding="utf-8")) if geo_path.exists() else {}
    venues, gyms, evidence, dropped = [], [], {}, {}
    seen = set()
    for item in checked:
        a = item["answer"]
        if "error" in a or not item.get("place"):
            dropped["error"] = dropped.get("error", 0) + 1
            continue
        if not a["sells_public_sauna_access"]:
            dropped["no public sauna"] = dropped.get("no public sauna", 0) + 1
            continue
        v = to_venue(item, today)
        if v["state"] not in US_STATES or not v["city"]:
            # Fill in a missing city or state from the map position, and catch places outside the US.
            g = reverse_geocode(v["lat"], v["lng"], geo_cache)
            if g["country"] != "us" or not g["state"]:
                dropped["outside the US"] = dropped.get("outside the US", 0) + 1
                continue
            v["state"] = g["state"]
            v["city"] = v["city"] or g["city"]
            v["id"] = slug(v["state"], v["city"], v["name"])
        base, n = v["id"], 2
        while v["id"] in seen:  # same name in the same city: number them
            v["id"] = f"{base}-{n}"
            n += 1
        seen.add(v["id"])
        if v["venue_type"] in PUBLIC_TYPES:
            venues.append(v)
            evidence[v["id"]] = a.get("evidence", [])
        elif v["venue_type"] == "gym":
            gyms.append(v)
        else:
            dropped[v["venue_type"]] = dropped.get(v["venue_type"], 0) + 1
    geo_path.write_text(json.dumps(geo_cache, indent=1), encoding="utf-8")
    venues.sort(key=lambda v: (v["state"] or "", v["city"] or "", v["name"]))
    (DATA / "parked").mkdir(exist_ok=True)
    (DATA / "venues.json").write_text(json.dumps(
        {"generated": today, "count": len(venues), "venues": venues}, indent=1, ensure_ascii=False), encoding="utf-8")
    (DATA / "parked" / "gyms.json").write_text(json.dumps(gyms, indent=1, ensure_ascii=False), encoding="utf-8")
    (DATA / "evidence.json").write_text(json.dumps(evidence, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(venues)} venues, {len(gyms)} gyms parked. Dropped: {dropped}")
