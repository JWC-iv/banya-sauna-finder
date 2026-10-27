"""
Step 6 of the data pipeline: check data/venues.json before publishing. Run this before every publish.

Checks required fields, allowed values, that every venue is inside the US, and that ids are unique.
Exits with an error (and lists the problems) if anything is wrong.

Run from the project folder:  py scripts/validate.py [path]   (default: data/venues.json)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ENUMS = {
    "venue_type": {"bathhouse", "banya", "korean_spa", "sauna_studio", "contrast_therapy",
                   "mobile_or_floating_sauna", "day_spa_day_pass"},
    "cold_plunge": {"none", "tub", "pool", "natural_water", "yes_unspecified", "unknown"},
    "access": {"walk_in", "reservation_required", "membership_only", "unknown"},
    "session_type": {"communal", "private", "both", "unknown"},
    "gender_policy": {"coed", "segregated", "both", "women_only", "men_only", "unknown"},
    "attire": {"swimsuit", "towel", "nude", "mixed", "unknown"},
}
LISTS = {
    "heat_types": {"traditional", "wood_fired", "infrared", "steam", "smoke", "banya"},
    "extras": {"aufguss", "venik", "massage", "food"},
}
REQUIRED = ["id", "name", "venue_type", "lat", "lng", "sources", "last_verified"]


def in_us(lat, lng):
    lower48 = 24 <= lat <= 50 and -125 <= lng <= -66
    alaska = 51 <= lat <= 72 and -180 <= lng <= -129
    hawaii = 18 <= lat <= 23 and -161 <= lng <= -154
    return lower48 or alaska or hawaii


def problems(venues):
    seen = set()
    for v in venues:
        vid = v.get("id", "?")
        for f in REQUIRED:
            if v.get(f) in (None, "", []):
                yield f"{vid}: missing {f}"
        for f, allowed in ENUMS.items():
            if v.get(f) not in allowed:
                yield f"{vid}: {f} = {v.get(f)!r} is not allowed"
        for f, allowed in LISTS.items():
            bad = set(v.get(f) or []) - allowed
            if bad:
                yield f"{vid}: {f} has {sorted(bad)}"
        if v.get("outdoor") not in (True, False, None):
            yield f"{vid}: outdoor must be true, false or null"
        if isinstance(v.get("lat"), (int, float)) and isinstance(v.get("lng"), (int, float)):
            if not in_us(v["lat"], v["lng"]):
                yield f"{vid}: location {v['lat']}, {v['lng']} is outside the US"
        if vid in seen:
            yield f"{vid}: duplicate id"
        seen.add(vid)


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "venues.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    venues = data["venues"] if isinstance(data, dict) else data
    found = list(problems(venues))
    for p in found[:50]:
        print(p)
    if found:
        sys.exit(f"{len(found)} problems in {len(venues)} venues. Fix before publishing.")
    print(f"OK: {len(venues)} venues passed every check.")
