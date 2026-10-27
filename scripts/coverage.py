"""
Step 7 of the data pipeline: how complete is each filter's data?

A filter ships only when at least 90% of venues have a known value for it (see CLAUDE.md).
The finder applies the same rule by itself, so this report just shows where things stand.

Run from the project folder:  py scripts/coverage.py [path]   (default: data/venues.json)
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THRESHOLD = 0.9

# Same "known" tests the finder uses (site/finder.js QUICK and FILTERS).
CHECKS = {
    "Open now (hours)": lambda v: bool(v.get("hours")),
    "Walk-ins (access)": lambda v: v.get("access") not in (None, "unknown"),
    "Cold plunge": lambda v: v.get("cold_plunge") not in (None, "unknown"),
    "Wood-fired / Heat (heat_types)": lambda v: bool(v.get("heat_types")),
    "Outdoor": lambda v: v.get("outdoor") is not None,
    "Private or social (session_type)": lambda v: v.get("session_type") not in (None, "unknown"),
    "Gender policy (later)": lambda v: v.get("gender_policy") not in (None, "unknown"),
    "Attire (later)": lambda v: v.get("attire") not in (None, "unknown"),
    "Day pass price (later)": lambda v: v.get("day_pass_price_usd") is not None,
}

if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "venues.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    venues = data["venues"] if isinstance(data, dict) else data
    n = len(venues)
    print(f"{n} venues\n")
    print(f"{'Filter':36s} {'known':>7s}  ships?")
    for name, known in CHECKS.items():
        share = sum(1 for v in venues if known(v)) / n if n else 0
        print(f"{name:36s} {share:6.0%}   {'yes' if share >= THRESHOLD else 'not yet'}")
    print("\nVenue types:", dict(Counter(v["venue_type"] for v in venues).most_common()))
    print("States:", dict(Counter(v.get("state") for v in venues).most_common(15)))
