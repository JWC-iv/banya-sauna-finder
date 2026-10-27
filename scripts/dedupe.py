"""
Step 3 of the data pipeline: merge records that are the same place.

Two records are the same place when they are within about 150 m of each other and either
share a website domain or have similar names. The merged record keeps every source id.

Reads data/raw/prefiltered.json, writes data/raw/deduped.json.
Run from the project folder:  py scripts/dedupe.py
"""
import json
import math
import re
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
MAX_METERS = 150


def meters(a, b):
    dlat = math.radians(b["lat"] - a["lat"])
    dlng = math.radians(b["lng"] - a["lng"]) * math.cos(math.radians(a["lat"]))
    return 6371000 * math.hypot(dlat, dlng)


def domain(url):
    if not url:
        return None
    if "://" not in url:
        url = "http://" + url
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host or None


def simple_name(name):
    return re.sub(r"[^a-z0-9 ]", "", (name or "").lower())


def same_place(a, b):
    if meters(a, b) > MAX_METERS:
        return False
    if a["domain"] and a["domain"] == b["domain"]:
        return True
    return SequenceMatcher(None, simple_name(a["name"]), simple_name(b["name"])).ratio() > 0.8


if __name__ == "__main__":
    rows = json.loads((RAW / "prefiltered.json").read_text(encoding="utf-8"))
    for r in rows:
        r["domain"] = domain(r["website"])
        r["sources"] = [r.pop("source")]
    # Bucket by ~1 km grid cell so each record is only compared with its neighbours.
    grid = {}
    merged = []
    for r in rows:
        cell = (round(r["lat"], 2), round(r["lng"], 2))
        match = None
        for dy in (-0.01, 0, 0.01):
            for dx in (-0.01, 0, 0.01):
                for other in grid.get((round(cell[0] + dy, 2), round(cell[1] + dx, 2)), []):
                    if same_place(r, other):
                        match = other
                        break
                if match:
                    break
            if match:
                break
        if match:
            match["sources"] += r["sources"]
            for k, v in r.items():  # fill gaps in the kept record
                if match.get(k) in (None, "") and v not in (None, ""):
                    match[k] = v
            if r["why"].startswith("name") and not match["why"].startswith("name"):
                match["why"] = r["why"]
        else:
            grid.setdefault(cell, []).append(r)
            merged.append(r)
    (RAW / "deduped.json").write_text(json.dumps(merged, indent=1, default=str), encoding="utf-8")
    print(f"{len(rows)} records -> {len(merged)} places after merging duplicates")
