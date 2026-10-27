"""
Step 4a of the data pipeline: a free check before any paid AI.

Downloads each candidate's homepage and looks for sauna words (sauna, steam room, banya,
cold plunge, ...). Only places whose homepage mentions one go on to the AI website check.
Places whose name already says sauna/bathhouse always go on, even if the homepage is silent.

Reads data/raw/deduped.json. Writes:
  data/raw/gate_results.json   every place with what the check found
  data/raw/pages/<key>.txt     homepage text for places that go on (re-used by the AI step)
Safe to stop and re-run: places already checked are skipped (matched by source id, so re-running
the earlier steps with more data is fine).

Run from the project folder:  py scripts/keyword_gate.py
"""
import html
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import truststore

truststore.inject_into_ssl()

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PAGES = RAW / "pages"
USER_AGENT = "Mozilla/5.0 (compatible; banya-sauna-finder/0.1; +https://github.com/JWC-iv/banya-sauna-finder)"
WORKERS = 32

SAUNA_WORDS = re.compile(
    r"\bsaunas?\b|steam room|\bbanyas?\b|cold plunge|plunge pool|ice bath|hammam|jjimjil|jimjil|"
    r"bath ?house|contrast therapy|\bonsen\b|\bvenik|aufguss", re.I)


def page_text(raw_html):
    t = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw_html)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def fetch(url):
    if "://" not in url:
        url = "https://" + url
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=15) as r:
        if "html" not in (r.headers.get("Content-Type") or "html"):
            return r.geturl(), ""
        return r.geturl(), r.read(2_000_000).decode("utf-8", "replace")


def key_of(place):
    return re.sub(r"[^A-Za-z0-9_-]", "_", place["sources"][0])


def check(key, place):
    out = {"key": key, "ok": False, "hits": [], "final_url": None, "error": None}
    try:
        out["final_url"], raw = fetch(place["website"])
        text = page_text(raw)
        out["ok"] = True
        out["hits"] = sorted({m.lower() for m in SAUNA_WORDS.findall(text)})[:10]
    except Exception as err:
        out["error"] = str(err)[:200]
        text = ""
    out["passes"] = bool(out["hits"]) or place["why"].startswith("name") or place["why"].startswith("tagged")
    if out["passes"] and text:
        (PAGES / f"{key}.txt").write_text(text[:60000], encoding="utf-8")
    return out


if __name__ == "__main__":
    PAGES.mkdir(parents=True, exist_ok=True)
    places = json.loads((RAW / "deduped.json").read_text(encoding="utf-8"))
    results_path = RAW / "gate_results.json"
    done = {r["key"]: r for r in json.loads(results_path.read_text())} if results_path.exists() else {}
    todo = [(key_of(p), p) for p in places if key_of(p) not in done and p.get("website")]
    print(f"{len(places)} places, {len(done)} already checked, {len(todo)} to check")
    with ThreadPoolExecutor(WORKERS) as pool:
        futures = [pool.submit(check, k, p) for k, p in todo]
        for n, f in enumerate(as_completed(futures), 1):
            r = f.result()
            done[r["key"]] = r
            if n % 500 == 0 or n == len(futures):
                results_path.write_text(json.dumps(list(done.values())), encoding="utf-8")
                passed = sum(1 for x in done.values() if x["passes"])
                print(f"  {n}/{len(futures)} checked, {passed} pass so far", flush=True)
                sys.stdout.flush()
    results_path.write_text(json.dumps(list(done.values())), encoding="utf-8")
    print(f"Done. {sum(1 for x in done.values() if x['passes'])} places go on to the AI check.")
