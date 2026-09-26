"""
Batched relevance triage for Lane 2 (general news feeds).
Uses a fast, low-cost LLM call (via Groq) to identify stories in broad
geopolitical feeds that materially impact crude oil prices, even if they
lack explicit oil keywords (e.g. pipeline strikes, naval skirmishes in Hormuz).

Fails closed: any exception or classification failure drops all candidates
from Lane 2 rather than risking unfiltered noise reaching the trading agent.
"""

import json
from groq import Groq
from config import GROQ_API_KEY, GROQ_RELEVANCE_MODEL


def classify_batch(candidates: list[dict]) -> list[dict]:
    """
    Takes a list of candidate story dicts: [{"title": str, "summary": str, ...}, ...]
    Sends all candidates in a single batched prompt to Groq.
    Returns the subset of candidates judged relevant to crude oil markets.
    """
    if not candidates:
        return []

    if not GROQ_API_KEY:
        print("Warning: GROQ_API_KEY not configured. Failing closed for Lane 2 general news.")
        return []

    # Build enumerated candidate list for the prompt
    formatted_items = []
    for idx, item in enumerate(candidates):
        title = item.get("title", "").strip()
        summary = item.get("summary", "").strip()[:250]
        formatted_items.append(f"[{idx}] Title: {title}\nSummary: {summary}")

    batch_text = "\n\n".join(formatted_items)

    system_prompt = (
        "You are an expert crude oil commodity market analyst. Your job is to filter "
        "general international news headlines and identify only those that represent "
        "material catalysts for crude oil supply, demand, logistics, or pricing.\n\n"
        "Include:\n"
        "- Military/security conflicts in key oil-producing or transit regions (Persian Gulf, Strait of Hormuz, Red Sea)\n"
        "- Attacks on energy infrastructure (pipelines, refineries, tankers, ports)\n"
        "- Sanctions, export bans, or major trade restrictions on oil-exporting nations\n"
        "- Macroeconomic policy shocks directly affecting energy demand\n\n"
        "Exclude:\n"
        "- Routine domestic politics, elections, and civic debates\n"
        "- General diplomacy or summits without direct energy market implications\n"
        "- Local crime, cultural news, or non-energy environmental stories\n\n"
        "Respond STRICTLY in valid JSON matching this schema:\n"
        '{"relevant_indices": [integer, ...]}'
    )

    try:
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model=GROQ_RELEVANCE_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Classify the following news items:\n\n{batch_text}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        raw_content = response.choices[0].message.content or "{}"
        parsed = json.loads(raw_content)
        indices = parsed.get("relevant_indices", [])

        relevant_results = []
        for idx in indices:
            if isinstance(idx, int) and 0 <= idx < len(candidates):
                relevant_results.append(candidates[idx])

        return relevant_results

    except Exception as e:
        # Fails closed on any error (rate limit, JSON error, connection issue)
        print(f"Warning: Relevance classification failed ({e}). Dropping Lane 2 candidates this cycle.")
        return []


if __name__ == "__main__":
    test_candidates = [
        {
            "title": "Drone attack damages Saudi pipeline pumping stations near Red Sea",
            "summary": "Explosions were reported at two pumping stations along the major crude pipeline.",
        },
        {
            "title": "New archaeological discovery in Cairo reveals ancient tombs",
            "summary": "Egyptologists have uncovered a 3,000-year-old tomb complex south of the capital.",
        },
        {
            "title": "US naval forces escort commercial vessels through Strait of Hormuz after threats",
            "summary": "Tensions rise as coastal batteries were placed on alert near maritime choke point.",
        },
    ]
    print(f"Testing batch classification on {len(test_candidates)} candidates...")
    results = classify_batch(test_candidates)
    print(f"Relevant items identified: {len(results)}")
    for r in results:
        print(" -", r["title"])
