"""
First pass at "Banya Approved" picks, against the standard in CLAUDE.md (signed off by John 2026-11-11).

Free part, from data we already have (data/venues.json):
  must have real heat (traditional, wood-fired, banya or smoke) AND a cold plunge;
  then count bonuses: wood/smoke/banya heat, a cold pool or natural-water plunge, rituals
  (aufguss/venik), social bathing, outdoor. Franchise chains (5+ locations) are out.
Paid part, for venues that could reach the bar: Claude searches the web for independent coverage
(articles, guides, SaunaTimes, North American Sauna Society) and writes a short note on why.
Two or more independent sources count as one more bonus. Two bonuses = approved.

Results go to data/banya_approved.json, an editorial file that build_venues.py merges in, so
re-running the data pipeline never loses the picks. John's own decisions go in the same file
with "by": "john" and always win over the first pass.

Run from the project folder:
    py scripts/banya_approved.py score            free scoring only, prints the counts
    py scripts/banya_approved.py search 20        search coverage for 20 candidates (a test)
    py scripts/banya_approved.py search           search every candidate not searched yet
    py scripts/banya_approved.py apply            write the picks into data/banya_approved.json
"""
import datetime
import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
SEARCH_RESULTS = RAW / "banya_search.json"
APPROVED = DATA / "banya_approved.json"
MODEL = "claude-haiku-5-5"
PRICE_IN, PRICE_OUT, PRICE_SEARCH = 0.10 / 1e6, 0.50 / 1e6, 10 / 1000  # USD

REAL_HEAT = {"traditional", "wood_fired", "banya", "smoke"}
HAS_PLUNGE = {"tub", "pool", "natural_water", "yes_unspecified"}
LABELS = {"wood": "wood-fired, smoke or banya heat", "cold": "a cold pool or natural-water plunge",
          "rituals": "rituals (aufguss or venik)", "social": "social bathing", "outdoor": "outdoor bathing",
          "press": "independent coverage"}


def chain_key(name):
    return re.sub(r"[^a-z ]", "", name.lower()).split(" - ")[0][:14]


def bonuses(v):
    b = []
    if set(v["heat_types"]) & {"wood_fired", "smoke", "banya"}:
        b.append("wood")
    if v["cold_plunge"] in ("pool", "natural_water"):
        b.append("cold")
    if set(v["extras"]) & {"aufguss", "venik"}:
        b.append("rituals")
    if v["session_type"] in ("communal", "both") or v["venue_type"] in ("bathhouse", "banya", "korean_spa"):
        b.append("social")
    if v["outdoor"] is True:
        b.append("outdoor")
    return b


def candidates():
    """Venues that meet both must-haves and are not franchise chains, with their free bonuses."""
    venues = json.loads((DATA / "venues.json").read_text(encoding="utf-8"))["venues"]
    chains = Counter(chain_key(v["name"]) for v in venues)
    out = []
    for v in venues:
        if not (set(v["heat_types"]) & REAL_HEAT and v["cold_plunge"] in HAS_PLUNGE):
            continue
        if chains[chain_key(v["name"])] >= 5:
            continue
        out.append((v, bonuses(v)))
    return out


# ---------- The web search for coverage ----------
SYSTEM = """You help Banya Press, a sauna publisher, pick standout saunas. For one venue you get the \
facts already verified from its own website. Use web search (a few searches at most) to find independent \
coverage of this specific venue: news or magazine articles, travel guides, "best saunas" lists, \
SaunaTimes, the North American Sauna Society, sauna blogs with real reviews.

Do NOT count: the venue's own site or social accounts; booking, listing or trip-planning sites (Google, \
Yelp, Tripadvisor, Wanderlog, ClassPass, Groupon, Mindbody, ResortPass, Wellhub, Fresha, Booksy); other \
sauna directories; auto-generated "top 10 near you" pages; press releases; paid placements. Only count a source that clearly names this venue at this location.

Then write `note`: one or two warm, plain sentences for a sauna lover on why this place stands out. Use \
only the verified facts and what the sources say; never invent details. Mention outside recognition \
only if you found it.

Finish with only a JSON object on the last line, no code fence:
{"sources": [{"name": "publication", "title": "article title", "url": "https://..."}], "note": "..."}"""


def describe(v, b):
    facts = [f"{v['name']}, {v['address'] or ''}, {v['city']}, {v['state']}",
             f"Website: {v['website']}", f"Type: {v['venue_type']}",
             f"Heat: {', '.join(v['heat_types'])}", f"Cold plunge: {v['cold_plunge']}",
             f"Outdoor: {v['outdoor']}", f"Sessions: {v['session_type']}",
             f"Extras: {', '.join(v['extras']) or 'none listed'}",
             f"Strengths already verified: {', '.join(LABELS[x] for x in b) or 'none beyond the basics'}"]
    return "\n".join(facts)


def search_one(client, v, b):
    messages = [{"role": "user", "content": describe(v, b)}]
    tin = tout = searches = 0
    for _ in range(4):  # resume if the server pauses a long search turn
        msg = client.messages.create(
            model=MODEL, max_tokens=4000, system=SYSTEM, messages=messages,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
            output_config={"effort": "low"})
        tin += msg.usage.input_tokens + (msg.usage.cache_read_input_tokens or 0)
        tout += msg.usage.output_tokens
        stu = getattr(msg.usage, "server_tool_use", None)
        searches += (getattr(stu, "web_search_requests", 0) or 0) if stu else 0
        if msg.stop_reason != "pause_turn":
            break
        messages = [messages[0], {"role": "assistant", "content": msg.content}]
    text = "".join(b.text for b in msg.content if b.type == "text")
    found = re.findall(r"\{.*\}", text, re.S)
    try:
        answer = json.loads(found[-1]) if found else {"error": "no json"}
    except json.JSONDecodeError:
        answer = {"error": "bad json"}
    cost = tin * PRICE_IN + tout * PRICE_OUT + searches * PRICE_SEARCH
    return {"id": v["id"], "answer": answer, "searches": searches, "cost": round(cost, 5)}


def run_search(limit):
    import anthropic
    import truststore
    truststore.inject_into_ssl()
    env = ROOT / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            os.environ.setdefault("ANTHROPIC_API_KEY", line.split("=", 1)[1].strip())
    client = anthropic.Anthropic()
    done = {r["id"]: r for r in json.loads(SEARCH_RESULTS.read_text(encoding="utf-8"))} if SEARCH_RESULTS.exists() else {}
    # Only venues one bonus short or better can reach the bar, so only they are worth a search.
    todo = [(v, b) for v, b in candidates() if len(b) >= 1 and v["id"] not in done]
    todo.sort(key=lambda vb: -len(vb[1]))
    if limit:
        # A test sample: mix venues that already pass with ones that are one short.
        strong = [x for x in todo if len(x[1]) >= 2][: limit // 2]
        short = [x for x in todo if len(x[1]) == 1][: limit - len(strong)]
        todo = strong + short
    print(f"Searching coverage for {len(todo)} venues with {MODEL}...")
    with ThreadPoolExecutor(4) as pool:
        for r in pool.map(lambda vb: search_one(client, *vb), todo):
            done[r["id"]] = r
            SEARCH_RESULTS.write_text(json.dumps(list(done.values()), indent=1), encoding="utf-8")
    new = [done[v["id"]] for v, _ in todo]
    spent = sum(r["cost"] for r in new)
    print(f"Done. {sum(r['searches'] for r in new)} searches, about ${spent:.2f} "
          f"(${spent / max(len(new), 1):.3f} per venue).")
    remaining = sum(1 for v, b in candidates() if len(b) >= 1 and v["id"] not in done)
    print(f"{remaining} candidates not searched yet; about ${remaining * spent / max(len(new), 1):.2f} to finish.")


# ---------- Deciding ----------
def decide():
    searched = {r["id"]: r for r in json.loads(SEARCH_RESULTS.read_text(encoding="utf-8"))} if SEARCH_RESULTS.exists() else {}
    picks = {}
    for v, b in candidates():
        r = searched.get(v["id"])
        sources = (r or {}).get("answer", {}).get("sources", []) if r else []
        sources = [s for s in sources if isinstance(s, dict) and s.get("url")]
        allb = b + (["press"] if len({re.sub(r"^www\.", "", s["url"].split("/")[2]) for s in sources if "//" in s["url"]}) >= 2 else [])
        if len(allb) >= 2 and r and "note" in r.get("answer", {}):
            picks[v["id"]] = {"name": v["name"], "city": v["city"], "state": v["state"],
                              "strengths": [LABELS[x] for x in allb], "note": r["answer"]["note"],
                              "sources": sources}
    return picks


def run_apply():
    today = datetime.date.today().isoformat()
    existing = json.loads(APPROVED.read_text(encoding="utf-8")) if APPROVED.exists() else {}
    picks = decide()
    out = {k: e for k, e in existing.items() if e.get("by") == "john"}  # John's calls always stay
    for vid, p in picks.items():
        if vid in out:
            continue
        out[vid] = {"approved": True, "by": "claude-first-pass", "date": today, **p}
    APPROVED.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{sum(1 for e in out.values() if e['approved'])} approved "
          f"({sum(1 for e in out.values() if e['by'] == 'john')} by John). Saved to {APPROVED}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "score"
    if mode == "score":
        c = candidates()
        counts = Counter(len(b) for _, b in c)
        print(f"{len(c)} venues have real heat + a cold plunge and are not chains")
        print("free bonuses:", dict(sorted(counts.items())))
        print(f"already meet the bar on free data: {sum(1 for _, b in c if len(b) >= 2)}; "
              f"one short: {counts[1]}")
    elif mode == "search":
        run_search(int(sys.argv[2]) if len(sys.argv) > 2 else 0)
    elif mode == "apply":
        run_apply()
