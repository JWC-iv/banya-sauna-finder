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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
PUBLIC_TYPES = {"bathhouse", "banya", "korean_spa", "sauna_studio", "contrast_therapy",
                "mobile_or_floating_sauna", "day_spa_day_pass"}
FIELDS = ["heat_types", "cold_plunge", "outdoor", "access", "session_type", "gender_policy", "hours",
          "day_pass_price_usd", "attire", "extras"]


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
    venues.sort(key=lambda v: (v["state"] or "", v["city"] or "", v["name"]))
    (DATA / "parked").mkdir(exist_ok=True)
    (DATA / "venues.json").write_text(json.dumps(
        {"generated": today, "count": len(venues), "venues": venues}, indent=1, ensure_ascii=False), encoding="utf-8")
    (DATA / "parked" / "gyms.json").write_text(json.dumps(gyms, indent=1, ensure_ascii=False), encoding="utf-8")
    (DATA / "evidence.json").write_text(json.dumps(evidence, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(venues)} venues, {len(gyms)} gyms parked. Dropped: {dropped}")
