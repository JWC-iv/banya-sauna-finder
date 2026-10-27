"""
Step 4b of the data pipeline: Claude reads each candidate's website.

For every place that passed the free keyword check (keyword_gate.py), this fetches the homepage
plus up to 4 relevant inner pages (hours, prices, amenities, FAQ...), and asks Claude:
  1. Does this business sell sauna access to the public? (most "spas" will say no)
  2. If yes: what type of venue is it, and what do the pages clearly state about the filter fields?
Every filled field comes with the page URL and a short quote as evidence. Anything not clearly
stated is "unknown" or null. Never guess.

Needs an Anthropic API key in a file called .env in the project folder:
    ANTHROPIC_API_KEY=sk-ant-...
(.env is git-ignored, so the key never goes to GitHub.)

Three ways to run it, from the project folder:
    py scripts/check_websites.py sample 50     try 50 random places right away, print the cost
    py scripts/check_websites.py submit        send every place as one batch job (half price)
    py scripts/check_websites.py collect       download the batch results when they're ready
Add --model claude-haiku-5-5 (or another model id) to any of them. The default is Claude Opus 5.5.
"""
import argparse
import html
import json
import os
import random
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

import anthropic
import truststore
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

truststore.inject_into_ssl()

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PAGES = RAW / "pages"
USER_AGENT = "Mozilla/5.0 (compatible; banya-sauna-finder/0.1; +https://github.com/JWC-iv/banya-sauna-finder)"
MAX_CHARS_PER_PAGE = 12000
MAX_CHARS_TOTAL = 30000
PRICES_PER_MILLION = {  # input, output (USD); batch jobs cost half
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}
USEFUL_LINK = re.compile(
    r"hour|price|pricing|rate|menu|amenit|facilit|sauna|bath|spa|plunge|visit|faq|day.?pass|"
    r"member|book|experience|thermal|about|etiquette|what.?to.?expect", re.I)

SYSTEM_PROMPT = """You review websites of US businesses for a sauna finder run by Banya Press. \
You get the text of a few pages from one business's own website. Report only what those pages clearly state.

First decide `sells_public_sauna_access`: true only if a member of the public can pay to use a sauna \
(or banya / steam room / hammam / infrared sauna) at this business: by day pass, single session, \
booking, or a membership open to the public. False for: sauna sellers, builders and installers; \
spas where the sauna is only a perk inside a massage or facial appointment and is not sold on its own; \
hotels where the sauna is only for hotel guests; private homes and rentals; massage-only businesses; \
businesses whose pages never mention a sauna; and sites that are broken, parked or about a different business.

venue_type, when access is sold:
- banya: Russian / Eastern European style bathhouse
- korean_spa: Korean jjimjilbang or Korean-style spa
- bathhouse: other multi-room social bathhouse (Japanese, Turkish, modern social bathhouse)
- sauna_studio: sauna-focused studio or club, including infrared studios and public sauna clubs
- contrast_therapy: studio built around hot/cold contrast (sauna + cold plunge) and recovery
- mobile_or_floating_sauna: trailer, boat, pop-up or rentable mobile sauna open to the public
- day_spa_day_pass: day spa or resort spa that sells a spa day pass with sauna access to non-guests
- gym: gym, fitness club, YMCA or athletic club where the sauna comes with a gym membership or day pass
- hotel: the business is a hotel, inn or resort and the sauna is part of it

Field rules:
- heat_types: traditional = dry Finnish-style sauna (electric or heater not stated); wood_fired only if \
wood burning is stated; infrared; steam (steam room, hammam, wet sauna); smoke; banya (Russian banya room). \
Empty list if no heat source is described.
- cold_plunge: tub, pool, natural_water (lake, ocean, river), yes_unspecified (a cold plunge exists but \
its form is not stated), none (the site says there is none), unknown.
- outdoor: true if the sauna or bathing area is outdoors, false if it says indoor only, else null.
- access: walk_in (walk-ins or drop-ins welcome), reservation_required, membership_only, unknown.
- session_type: communal (shared sessions with strangers), private (private rooms or private bookings \
only), both, unknown.
- gender_policy: coed, segregated (separate men's and women's areas), both (some co-ed and some \
single-gender times or areas), women_only, men_only, unknown.
- attire: swimsuit, towel, nude, mixed (depends on area or day), unknown.
- hours: OpenStreetMap opening_hours syntax like "Mo-Fr 07:00-21:00; Sa,Su 08:00-20:00", or null. \
Use the hours for sauna or bathing access if they differ from other hours.
- day_pass_price_usd: cheapest single-visit price for adult sauna access, as a number, or null.
- extras: aufguss (guided heat or towel ritual sessions), venik (birch or oak leaf treatment), \
massage, food (cafe or restaurant on site).

For every field you fill with something other than unknown, null or an empty list, add an evidence \
item with the page URL and a short exact quote (under 25 words) that shows it. If you can't quote it, \
don't fill it."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["sells_public_sauna_access", "reason", "venue_type", "heat_types", "cold_plunge", "outdoor",
                 "access", "session_type", "gender_policy", "attire", "hours", "day_pass_price_usd",
                 "extras", "phone", "evidence"],
    "properties": {
        "sells_public_sauna_access": {"type": "boolean"},
        "reason": {"type": "string", "description": "One sentence explaining the decision."},
        "venue_type": {"type": "string", "enum": [
            "banya", "korean_spa", "bathhouse", "sauna_studio", "contrast_therapy", "mobile_or_floating_sauna",
            "day_spa_day_pass", "gym", "hotel", "not_a_venue"]},
        "heat_types": {"type": "array", "items": {"type": "string", "enum": [
            "traditional", "wood_fired", "infrared", "steam", "smoke", "banya"]}},
        "cold_plunge": {"type": "string", "enum": [
            "none", "tub", "pool", "natural_water", "yes_unspecified", "unknown"]},
        "outdoor": {"type": ["boolean", "null"]},
        "access": {"type": "string", "enum": ["walk_in", "reservation_required", "membership_only", "unknown"]},
        "session_type": {"type": "string", "enum": ["communal", "private", "both", "unknown"]},
        "gender_policy": {"type": "string", "enum": [
            "coed", "segregated", "both", "women_only", "men_only", "unknown"]},
        "attire": {"type": "string", "enum": ["swimsuit", "towel", "nude", "mixed", "unknown"]},
        "hours": {"type": ["string", "null"]},
        "day_pass_price_usd": {"type": ["number", "null"]},
        "extras": {"type": "array", "items": {"type": "string", "enum": ["aufguss", "venik", "massage", "food"]}},
        "phone": {"type": ["string", "null"]},
        "evidence": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["field", "url", "quote"],
            "properties": {"field": {"type": "string"}, "url": {"type": "string"}, "quote": {"type": "string"}}}},
    },
}


# ---------- Fetching pages ----------
def page_text(raw_html):
    t = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw_html)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.geturl(), r.read(2_000_000).decode("utf-8", "replace")


def gather_pages(place, gate):
    """Homepage plus up to 4 useful pages on the same site."""
    start = gate.get("final_url") or place["website"]
    if "://" not in start:
        start = "https://" + start
    try:
        home_url, raw = fetch(start)
    except Exception:
        cached = PAGES / f"{gate['key']}.txt"
        return [(start, cached.read_text(encoding="utf-8"))] if cached.exists() else []
    pages = [(home_url, page_text(raw))]
    host = urlparse(home_url).netloc
    links = []
    for href, label in re.findall(r'(?is)<a[^>]+href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', raw):
        url = urljoin(home_url, href)
        if urlparse(url).netloc != host or url in links or url.rstrip("/") == home_url.rstrip("/"):
            continue
        if USEFUL_LINK.search(url) or USEFUL_LINK.search(page_text(label)):
            links.append(url)
    for url in links[:4]:
        try:
            final, raw2 = fetch(url)
            pages.append((final, page_text(raw2)))
        except Exception:
            pass
    return pages


def build_prompt(place, pages):
    parts = [f"Business: {place['name']}\nListed address: {place.get('address') or ''}, "
             f"{place.get('city') or ''}, {place.get('state') or ''}\n"]
    total = 0
    for url, text in pages:
        chunk = text[:MAX_CHARS_PER_PAGE]
        if total + len(chunk) > MAX_CHARS_TOTAL:
            chunk = chunk[:max(0, MAX_CHARS_TOTAL - total)]
        if not chunk:
            break
        total += len(chunk)
        parts.append(f"--- PAGE {url} ---\n{chunk}\n")
    return "\n".join(parts)


def request_params(model, prompt):
    return {
        "model": model,
        "max_tokens": 8000,
        # Effort low: this is careful reading, not hard reasoning. Raise it if the sample looks sloppy.
        "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": prompt}],
    }


def parse_message(msg):
    if msg.stop_reason == "refusal":
        return {"error": "refused"}
    text = next((b.text for b in msg.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"error": f"bad json (stop_reason {msg.stop_reason})"}


# ---------- Setup ----------
def load_key():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("ANTHROPIC_API_KEY="):
                os.environ.setdefault("ANTHROPIC_API_KEY", line.split("=", 1)[1].strip())


def candidates():
    places = {re.sub(r"[^A-Za-z0-9_-]", "_", p["sources"][0]): p
              for p in json.loads((RAW / "deduped.json").read_text(encoding="utf-8"))}
    gates = json.loads((RAW / "gate_results.json").read_text(encoding="utf-8"))
    return [(g, places[g["key"]]) for g in gates if g["passes"] and g["key"] in places]


def cost(model, usage_in, usage_out, batch):
    p_in, p_out = PRICES_PER_MILLION.get(model, (0, 0))
    dollars = usage_in / 1e6 * p_in + usage_out / 1e6 * p_out
    return dollars / 2 if batch else dollars


def prepare(items):
    """Fetch pages for many places in parallel; returns (key, place, prompt, urls)."""
    def one(item):
        gate, place = item
        pages = gather_pages(place, gate)
        return gate["key"], place, build_prompt(place, pages), [u for u, _ in pages]
    with ThreadPoolExecutor(16) as pool:
        return [r for r in pool.map(one, items) if r[3]]


# ---------- Modes ----------
def run_sample(client, model, n):
    items = candidates()
    # Reuse the same sample for every model so their answers can be compared side by side.
    keys_path = RAW / "sample_keys.json"
    if keys_path.exists():
        keys = set(json.loads(keys_path.read_text()))
        picked = [it for it in items if it[0]["key"] in keys]
    else:
        random.seed(7)
        picked = random.sample(items, min(n, len(items)))
        keys_path.write_text(json.dumps([g["key"] for g, _ in picked]))
    # Fetch the pages once, so every model reads exactly the same text.
    prompts_path = RAW / "sample_prompts.json"
    if prompts_path.exists():
        prepared = json.loads(prompts_path.read_text(encoding="utf-8"))
    else:
        prepared = prepare(picked)
        prompts_path.write_text(json.dumps(prepared, default=str), encoding="utf-8")
    print(f"Checking {len(prepared)} places with {model}...")
    results, tin, tout = [], 0, 0
    def ask(p):
        key, place, prompt, urls = p
        msg = client.messages.create(**request_params(model, prompt))
        return key, place, urls, msg
    with ThreadPoolExecutor(4) as pool:
        for key, place, urls, msg in pool.map(ask, prepared):
            u = msg.usage
            tin += u.input_tokens + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0)
            tout += u.output_tokens
            results.append({"key": key, "place": place, "pages": urls, "answer": parse_message(msg)})
    out = RAW / f"check_sample_{model}.json"
    out.write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    yes = sum(1 for r in results if r["answer"].get("sells_public_sauna_access"))
    spent = cost(model, tin, tout, batch=False)
    total = len(candidates())
    print(f"{yes}/{len(results)} sell sauna access. Spent about ${spent:.2f} "
          f"({tin} input, {tout} output tokens). Saved to {out}")
    print(f"All {total} candidates would cost about ${spent / len(results) * total:.0f} normally, "
          f"${spent / len(results) * total / 2:.0f} as a batch job.")


def run_submit(client, model):
    items = candidates()
    print(f"Fetching pages for {len(items)} places (takes a while)...")
    prepared = prepare(items)
    requests = [Request(custom_id=key[:64], params=MessageCreateParamsNonStreaming(**request_params(model, prompt)))
                for key, _, prompt, _ in prepared]
    batch_ids = []
    for start in range(0, len(requests), 3000):  # about 100 MB per batch, under the 256 MB limit
        batch = client.messages.batches.create(requests=requests[start:start + 3000])
        batch_ids.append(batch.id)
        print(f"Submitted batch {batch.id} ({len(requests[start:start + 3000])} places)")
    meta = {"model": model, "batch_ids": batch_ids,
            "pages": {key[:64]: {"key": key, "urls": urls} for key, _, _, urls in prepared}}
    (RAW / "batch_job.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print("Batches usually finish within an hour. Then run: py scripts/check_websites.py collect")


def run_collect(client):
    meta = json.loads((RAW / "batch_job.json").read_text(encoding="utf-8"))
    places = {re.sub(r"[^A-Za-z0-9_-]", "_", p["sources"][0]): p
              for p in json.loads((RAW / "deduped.json").read_text(encoding="utf-8"))}
    results, tin, tout = [], 0, 0
    for batch_id in meta["batch_ids"]:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status != "ended":
            print(f"Batch {batch_id} is still {batch.processing_status}. Try again later.")
            return
        for r in client.messages.batches.results(batch_id):
            info = meta["pages"][r.custom_id]
            if r.result.type == "succeeded":
                msg = r.result.message
                tin += msg.usage.input_tokens + (msg.usage.cache_read_input_tokens or 0)
                tout += msg.usage.output_tokens
                answer = parse_message(msg)
            else:
                answer = {"error": r.result.type}
            results.append({"key": info["key"], "place": places.get(info["key"]), "pages": info["urls"],
                            "answer": answer})
    (RAW / "checked.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    yes = sum(1 for r in results if r["answer"].get("sells_public_sauna_access"))
    print(f"{yes}/{len(results)} sell sauna access. Cost about ${cost(meta['model'], tin, tout, True):.2f}. "
          f"Saved to data/raw/checked.json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["sample", "submit", "collect"])
    ap.add_argument("n", nargs="?", type=int, default=50)
    ap.add_argument("--model", default="claude-opus-5-5")
    args = ap.parse_args()
    load_key()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("No API key found. Put ANTHROPIC_API_KEY=... in a file named .env in the project folder.")
    client = anthropic.Anthropic()
    if args.mode == "sample":
        run_sample(client, args.model, args.n)
    elif args.mode == "submit":
        run_submit(client, args.model)
    else:
        run_collect(client)
