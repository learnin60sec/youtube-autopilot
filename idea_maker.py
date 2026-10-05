"""
YouTube Idea & Script Maker  (Part 2 of the YouTube automation project)
-----------------------------------------------------------------------
Reads trends.json (made by trend_finder.py) and uses AI to write ORIGINAL
video plans: title, hook, script with visual cues, description, tags,
hashtags and thumbnail text.

AI providers (default "auto" tries them in this order, skipping any
that have no key or are busy):
    gemini  FREE  -> set GEMINI_API_KEY=your_key   (aistudio.google.com/apikey)
    groq    FREE  -> set GROQ_API_KEY=your_key     (console.groq.com/keys)
    ollama  FREE  -> runs on your laptop (ollama.com)
    claude  paid  -> set ANTHROPIC_API_KEY=your_key

Plans are saved as "draft". With --auto-approve, plans that pass the
automatic quality checks are saved as "approved" (fully automatic mode).

Run:
    python idea_maker.py                                   # Gemini, auto everything
    python idea_maker.py --format short --count 3
    python idea_maker.py --category "Education" --auto-approve
    python idea_maker.py --provider ollama
    python idea_maker.py --language Hindi
"""

import os
import re
import sys
import json
import glob
import argparse
import time
from datetime import datetime

import requests

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")

# Different video styles so the channel never feels like one template
STYLES = [
    "Surprising fact: one true, little-known fact explained simply",
    "Myth vs Fact: a common belief, then the real truth",
    "3 common mistakes people make, and the fix",
    "Quick how-to in 3 clear steps",
    "Mini quiz: ask a question, pause, then reveal and explain the answer",
    "Explained simply: why something everyday works the way it does",
    "What happens if...: a curious scenario with a real, accurate answer",
]


def styles_for_today(count):
    day = datetime.now().timetuple().tm_yday
    return [STYLES[(day * count + i) % len(STYLES)] for i in range(count)]


WORD_LIMITS = {"short": (50, 120), "long": (900, 2000)}

FORMAT_RULES = {
    "short": ("A vertical YouTube Short of 20-40 seconds. Script 60-100 words, "
              "3-5 short sections. VIRAL RULES: "
              "(1) HOOK (most important, 60% of viewers swipe here): the first sentence "
              "must stop the scroll in under 2 seconds. Max 8 words. The FIRST 3 WORDS "
              "must already create curiosity or tension, e.g. 'Never do this when...', "
              "'Stop! You're parking wrong.', 'This tiny button saves lives.', "
              "'Most drivers get this wrong.' BANNED openings: 'Ever wonder', "
              "'Did you know', 'Have you ever', 'Hey guys', 'In this video', 'Today'. "
              "The 'hook' field must be exactly the first sentence of the script, and "
              "the first section's visual_search must be a dramatic, action-filled shot. "
              "(2) One idea only, short punchy sentences, fast pace. "
              "(3) Near the end, ONE short line (max 10 words) asking to like and follow, "
              "matching the topic, e.g. 'Like if this helped, follow for daily driving tips.' "
              "Then ask viewers ONE easy question to answer in the comments "
              "(e.g. 'Did you know this? Comment yes or no.'). "
              "(4) LOOP: the very last sentence must flow naturally back into the first "
              "sentence, so the video feels seamless when it replays."),
    "long": ("A YouTube video of 8-10 minutes. Script about 1200-1500 words in "
             "6-9 sections. The first section is named 'Intro'; every other section "
             "has a short, clear name (they become YouTube chapters, e.g. 'Tip 1: Check "
             "your mirrors'). WATCH-TIME RULES: (1) strong hook in the first 15 seconds "
             "that promises exactly what the viewer will learn (never open with 'Ever "
             "wonder', 'Did you know', 'Have you ever', 'Hey guys' or 'In this video'); (2) every 60-90 seconds "
             "add a curiosity line that makes people keep watching, e.g. 'but the next "
             "one surprises most people'; (3) save the most useful point for near the end "
             "and say so early; (4) around one third in, one short line: 'If you're "
             "learning something, subscribe, it helps a lot'; (5) ask one question for "
             "the comments; (6) end with a 20-second recap and tell viewers to watch "
             "another video on the channel.")}

SYSTEM_PROMPT = """You are an expert YouTube strategist and scriptwriter.
You study what is trending and create ORIGINAL videos that can beat it.

Rules:
- Never copy titles, scripts or ideas word for word. Use trends only as
  inspiration for a fresh angle, a better explanation or a new question.
- ACCURACY IS THE TOP RULE. Only choose topics built on well-established,
  widely known facts that are easy to verify. No statistics, percentages,
  studies, dates or "experts say" claims unless they are famous and certain.
  Never invent slang, hand signs, customs, origins or "secret meanings".
  If you are not sure a topic is true, pick a different topic.
- "fact_check_notes" must list any claim that is not 100% certain. It should
  normally be an empty list.
- No clickbait that the video does not deliver. The title and thumbnail must
  match the content.
- Visual cues must be generic search terms for free stock footage
  (e.g. "city traffic at night"), never clips from other creators.
- Reply with ONLY valid JSON. No markdown, no backticks, no extra text."""

PLAN_SCHEMA = """{
  "plans": [
    {
      "title": "under 70 characters",
      "hook": "first line the viewer hears",
      "script": [
        {"section": "Hook", "narration": "...", "visual_search": "stock footage search term"}
      ],
      "description": "2-3 short paragraphs, keyword rich",
      "tags": ["10-15 tags"],
      "hashtags": ["#three", "#hashtags", "#max"],
      "thumbnail_text": "2-4 bold, curiosity words (shown on screen the whole video)",
      "why_it_will_work": "one or two sentences linked to the trend data",
      "fact_check_notes": ["claims to verify before posting"],
      "series": null,
      "category": "the ONE topic area this video is really about"
    }
  ]
}"""


def load_trends(path):
    if not os.path.exists(path):
        sys.exit(f"Error: {path} not found. Run trend_finder.py first.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def pick_category(trends, forced, allowed=None, rotate=False):
    if forced:
        return forced
    if allowed and rotate:  # a different topic area each day
        return allowed[datetime.now().timetuple().tm_yday % len(allowed)]
    if allowed:
        for c in trends.get("categories", []):  # already ranked best first
            if c["category"] in allowed:
                return c["category"]
        return allowed[0]
    rec = trends.get("recommended_category")
    if not rec:
        sys.exit("No recommended category in trends.json. Use --category.")
    return rec["category"]


def best_own_category(allowed, path="performance.json"):
    """My channel's best topic so far (most views per day), from analytics_report.py."""
    try:
        with open(path, encoding="utf-8") as f:
            cats = json.load(f).get("category_views_per_day") or {}
    except (OSError, ValueError):
        return None
    scored = [(v, c) for c, v in cats.items() if c in allowed and v > 0]
    return max(scored)[1] if scored else None


def smart_categories(trends, forced, allowed, rotate, count, core=None, explore=True):
    """Plan 1 = my CORE topic (fixed, e.g. driving) or, if none, my best-performing topic.
    Other plans = proven winners get 2 turns, other topics get tested, clear flops are paused."""
    if forced or not allowed:
        return [pick_category(trends, forced, allowed, rotate)] * count
    best = core if core in allowed else best_own_category(allowed)
    if not best:
        return [pick_category(trends, None, allowed, rotate)] * count
    others = [c for c in allowed if c != best]
    try:
        with open("performance.json", encoding="utf-8") as f:
            perf = json.load(f)
        avg = perf.get("category_views_per_day") or {}
        counts = perf.get("category_video_counts") or {}
        top = max([avg.get(best, 0)] + [avg.get(c, 0) for c in others])
        weak = {c for c in others if counts.get(c, 0) >= 2 and avg.get(c, 0) < top * 0.10}
        if weak:
            print(f"  Skipping weak topics for now: {', '.join(sorted(weak))}")
        others = [c for c in others if c not in weak]
        strong = [c for c in others if counts.get(c, 0) >= 2 and avg.get(c, 0) >= top * 0.30]
        if explore:
            others = strong * 2 + [c for c in others if c not in strong]
        else:
            # No experiments: only my core topic and other PROVEN winners
            others = [best] + strong if strong else [best]
            print(f"  Only proven topics: {', '.join(dict.fromkeys([best] + others))}")
    except (OSError, ValueError):
        if not explore:
            others = [best]
    others = others or [best]
    day = datetime.now().timetuple().tm_yday
    return [best] + [others[(day + i) % len(others)] for i in range(count - 1)]


CATEGORY_NAMES = {"Autos & Vehicles", "Howto & Style", "Science & Technology", "Education",
                  "Pets & Animals", "Travel & Events", "Sports", "People & Blogs"}

TOPIC_FOLLOW = {
    "Autos & Vehicles": "daily driving tips",
    "Science & Technology": "daily science and tech facts",
    "Howto & Style": "daily life hacks",
    "Education": "a new lesson every day",
}


def past_titles(plans_dir, limit=40):
    titles = []
    for p in sorted(glob.glob(os.path.join(plans_dir, "*.json")), reverse=True)[:limit]:
        try:
            with open(p, encoding="utf-8") as f:
                titles.append(json.load(f).get("title", ""))
        except (OSError, ValueError):
            pass
    return [t for t in titles if t]


def pick_format(trends, forced):
    if forced != "auto":
        return forced
    scores = trends.get("format_scores") or {}
    return max(scores, key=scores.get) if scores else "short"


def performance_text(path="performance.json"):
    """What worked / did not work on MY channel (from analytics_report.py)."""
    try:
        with open(path, encoding="utf-8") as f:
            perf = json.load(f)
    except (OSError, ValueError):
        return ""
    lines = []
    if perf.get("best"):
        lines.append("What works best on MY channel (make more videos with this kind of "
                     "topic, hook and style):")
        lines += [f'- "{v["title"]}" ({v["views_per_day"]} views/day, hook: "{v.get("hook", "")}")'
                  for v in perf["best"][:5]]
    if perf.get("worst"):
        lines.append("What did badly on MY channel (avoid this kind of topic and style):")
        lines += [f'- "{v["title"]}" ({v["views_per_day"]} views/day)' for v in perf["worst"]]
    return ("\n".join(lines) + "\n\n") if lines else ""


# ---------------- Search topics (what people actually type on YouTube) --------
SEARCH_SEEDS = {
    "Autos & Vehicles": ["driving tips", "how to drive", "why do cars", "car myths", "how to park"],
    "Education": ["why is the", "how does the", "what happens if you", "why do we", "did you know"],
    "Science & Technology": ["how does a phone", "why does my phone", "how does wifi",
                             "science facts", "how does ai"],
    "Howto & Style": ["how to clean", "life hacks", "how to fix", "how to remove", "kitchen hacks"],
}


def search_suggestions(category, limit=25):
    """YouTube search autocomplete: real questions people search (free, no key).
    If it fails, the idea maker simply works without it."""
    found = []
    for seed in SEARCH_SEEDS.get(category, ["how to", "why do"]):
        try:
            r = requests.get("https://suggestqueries.google.com/complete/search",
                             params={"client": "firefox", "ds": "yt", "q": seed,
                                     "hl": "en", "gl": "us"}, timeout=8)
            found += [x for x in r.json()[1] if x.lower() != seed]
        except Exception:
            continue
    seen, out = set(), []
    for q in found:
        if q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out[:limit]


# ---------------- Series (Part 1 -> Part 2) --------------------------------------
def pending_series(plans_dir):
    """Oldest Part 1 that still needs its Part 2."""
    for p in sorted(glob.glob(os.path.join(plans_dir, "*.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                plan = json.load(f)
        except (OSError, ValueError):
            continue
        ser = plan.get("series") or {}
        if (ser.get("part") == 1 and not plan.get("series_done")
                and plan.get("status") in ("approved", "video_ready", "uploaded")):
            return p, plan
    return None, None


def series_instruction(pending, count, fmt):
    if fmt != "short":
        return ""
    if pending:
        ser = pending["series"]
        return (f'SERIES: The LAST plan (plan {count}) MUST be PART 2 of my series "{ser.get("name")}". '
                f'Part 1 was "{pending.get("title")}" and promised: '
                f'{ser.get("next_part_idea", "the next part")}. Put "(Part 2)" at the end of '
                f'the title, start with "Part 2!" and deliver exactly what was promised. '
                f'Set "series": {{"name": "{ser.get("name")}", "part": 2}}. '
                f'(This is allowed even though Part 1 is in my old topics list.)\n\n')
    if count >= 2 and datetime.now().timetuple().tm_yday % 2 == 0:
        return ('SERIES: Make plan 1 PART 1 of a new 2-part series (in plan 1\'s topic area). Put "(Part 1)" at the end '
                'of the title. Instead of the loop ending, end with a cliffhanger like '
                '"Follow so you don\'t miss Part 2!". Add "series": {"name": "short series '
                'name", "part": 1, "next_part_idea": "exactly what Part 2 will teach"}.\n\n')
    return ""


def build_user_prompt(trends, category, fmt, language, count, channel="", avoid=None,
                      extra="", categories=None):
    categories = categories or [category] * count
    videos = [v for v in trends.get("top_videos", []) if v["category"] in categories]
    if not videos:
        videos = trends.get("top_videos", [])
    examples = "\n".join(
        f'- "{v["title"]}" | {v["views"]:,} views | {v["like_rate_pct"] if v["like_rate_pct"] is not None else "hidden"}% likes '
        f'| {v["views_per_hour"]:,} views/hr | {v["format"]}'
        for v in videos[:12]
    )
    cat_info = next((c for c in trends.get("categories", [])
                     if c["category"] == category), {})
    channel_line = (f'My channel is called "{channel}". Every video must teach ONE useful, '
                    f'surprising thing quickly and clearly, matching that name.\n\n') if channel else ""
    avoid_line = ("Do NOT repeat these topics I already made:\n- " + "\n- ".join(avoid) + "\n\n") if avoid else ""
    keywords = ", ".join(cat_info.get("keywords") or trends.get("hot_keywords", [])[:15])

    return f"""Trend data from YouTube ({trends.get("region")}, {trends.get("generated_at", "")[:10]}):

Channel category: {category}
Topic area for each plan (follow this exactly):
{chr(10).join(f"- Plan {n + 1}: {c}" + (" (my best-performing topic, my viewers love it)" if n == 0 and len(set(categories)) > 1 else "") for n, c in enumerate(categories))}
For each plan, set "category" to the ONE topic area the video is REALLY about, chosen from: {", ".join(dict.fromkeys(categories + ["Autos & Vehicles", "Howto & Style", "Science & Technology", "Education"]))}.
Hot keywords: {keywords}

Top trending videos right now (inspiration only, do NOT copy):
{examples}

{channel_line}{performance_text()}{avoid_line}{extra}Task: create {count} ORIGINAL video plan(s) for my channel.
Format: {FORMAT_RULES[fmt]}
Language of title, script and description: {language}

Use exactly these video styles, one per plan, in this order:
{chr(10).join("- " + st for st in styles_for_today(count))}
Each plan must feel fresh: different topic, different hook wording. Return JSON in exactly this shape:
{PLAN_SCHEMA}"""


def clean_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1] if start != -1 else text)


class ProviderError(Exception):
    """An AI service could not answer right now."""


def short_error(r):
    try:
        return r.json().get("error", {}).get("message", "")[:120]
    except ValueError:
        return r.text[:120]


# ---------------- Gemini (free) ----------------
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
MODEL_CACHE = "gemini_model.txt"
SKIP_WORDS = ("image", "tts", "audio", "live", "embedding", "vision",
              "robotics", "computer-use", "native", "aqa", "learnlm",
              "transcribe", "customtools")


def gemini_models(key):
    """Ask Google which Gemini text models this key can use."""
    if os.getenv("GEMINI_MODEL"):
        return [os.getenv("GEMINI_MODEL")]
    r = requests.get(f"{GEMINI_BASE}/models", headers={"x-goog-api-key": key},
                     params={"pageSize": 1000}, timeout=20)
    if r.status_code in (400, 401, 403):
        raise ProviderError("Gemini rejected the key (make a new one at aistudio.google.com/apikey)")
    r.raise_for_status()
    found = []
    for m in r.json().get("models", []):
        name = m["name"].replace("models/", "")
        if "generateContent" not in m.get("supportedGenerationMethods", []):
            continue
        if not name.startswith("gemini") or any(w in name for w in SKIP_WORDS):
            continue
        ver = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
        found.append((float(ver.group(1)) if ver else 0, name))
    found.sort(reverse=True)
    names = [n for _, n in found]
    # Mix families so one overloaded family does not block everything:
    # newest flash, newest flash-lite, newest pro, then the rest
    ordered = []
    for key_word in ("flash-lite", "flash", "pro"):
        for n in names:
            if key_word in n and n not in ordered:
                if key_word == "flash" and "lite" in n:
                    continue
                ordered.append(n)
                break
    ordered += [n for n in names if n not in ordered]
    return ordered


def ask_gemini(prompt, max_tokens):
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise ProviderError("no GEMINI_API_KEY set")
    models = gemini_models(key)
    try:
        with open(MODEL_CACHE, encoding="utf-8") as f:
            last = f.read().strip()
        if last in models:
            models.remove(last)
            models.insert(0, last)
    except OSError:
        pass
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json",
                             "maxOutputTokens": max_tokens, "temperature": 0.9},
    }
    shown = False
    for model in models[:12]:
        try:
            r = requests.post(f"{GEMINI_BASE}/models/{model}:generateContent",
                              headers={"x-goog-api-key": key}, json=body, timeout=90)
        except (requests.ConnectionError, requests.Timeout):
            continue
        if r.status_code == 200:
            try:
                parts = r.json()["candidates"][0]["content"]["parts"]
            except (KeyError, IndexError):
                continue
            print(f"  Gemini model: {model}")
            try:
                with open(MODEL_CACHE, "w", encoding="utf-8") as f:
                    f.write(model)
            except OSError:
                pass
            return clean_json("".join(p.get("text", "") for p in parts
                                      if not p.get("thought")))
        if not shown:
            print(f"  Google says: {r.status_code} {short_error(r)}")
            shown = True
        print(f"  {model} not free right now, next...")
    raise ProviderError("all Gemini models busy")


# ---------------- Groq (free, very fast) ----------------
GROQ_BASE = "https://api.groq.com/openai/v1"
GROQ_PREFER = ("gpt-oss-120b", "llama-4", "llama-3.3-70b", "70b", "120b",
               "versatile", "qwen", "kimi", "llama", "gpt-oss")
GROQ_SKIP = ("whisper", "tts", "guard", "embed", "playai", "orpheus",
             "distil", "prompt", "compound")


def ask_groq(prompt, max_tokens):
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise ProviderError("no GROQ_API_KEY set")
    head = {"Authorization": f"Bearer {key}"}
    if os.getenv("GROQ_MODEL"):
        models = [os.getenv("GROQ_MODEL")]
    else:
        r = requests.get(f"{GROQ_BASE}/models", headers=head, timeout=20)
        if r.status_code in (401, 403):
            raise ProviderError("Groq rejected the key")
        r.raise_for_status()
        ids = [m["id"] for m in r.json().get("data", [])
               if not any(w in m["id"].lower() for w in GROQ_SKIP)]
        def rank(i):
            for n, w in enumerate(GROQ_PREFER):
                if w in i.lower():
                    return n
            return len(GROQ_PREFER)
        models = sorted(ids, key=rank)
    for model in models[:5]:
        body = {"model": model, "temperature": 0.9,
                "max_tokens": min(max_tokens, 8000),
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                             {"role": "user", "content": prompt}]}
        try:
            r = requests.post(f"{GROQ_BASE}/chat/completions", headers=head,
                              json=body, timeout=90)
            if r.status_code == 400:  # model may not support JSON mode
                body.pop("response_format")
                r = requests.post(f"{GROQ_BASE}/chat/completions", headers=head,
                                  json=body, timeout=90)
        except (requests.ConnectionError, requests.Timeout):
            continue
        if r.status_code == 200:
            print(f"  Groq model: {model}")
            return clean_json(r.json()["choices"][0]["message"]["content"])
        print(f"  {model} not free right now ({r.status_code}), next...")
    raise ProviderError("all Groq models busy")


# ---------------- Ollama (free, on your laptop) ----------------
def ask_ollama(prompt, max_tokens):
    try:
        requests.get("http://localhost:11434/api/tags", timeout=2)
    except requests.RequestException:
        raise ProviderError("Ollama not running")
    body = {"model": OLLAMA_MODEL, "stream": False, "format": "json",
            "options": {"num_predict": max_tokens},
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": prompt}]}
    r = requests.post("http://localhost:11434/api/chat", json=body, timeout=900)
    if r.status_code != 200:
        raise ProviderError(f"Ollama error {r.status_code} (run: ollama pull {OLLAMA_MODEL})")
    return clean_json(r.json()["message"]["content"])


# ---------------- Claude (paid backup) ----------------
def ask_claude(prompt, max_tokens):
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise ProviderError("no ANTHROPIC_API_KEY set")
    import anthropic
    try:
        msg = anthropic.Anthropic().messages.create(
            model=CLAUDE_MODEL, max_tokens=max_tokens, system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}])
    except anthropic.APIError as e:
        raise ProviderError(f"Claude error: {e}")
    return clean_json("".join(b.text for b in msg.content if b.type == "text"))


def fact_check(plan, provider, max_tokens=2000):
    """Ask the AI (as a strict fact-checker) to review the script. Returns problems."""
    script = " ".join(sec.get("narration", "") for sec in plan.get("script", []))
    prompt = f"""Act as a strict fact-checker for an educational video. Read the title and
script. Mark "fail" if ANY claim is false, exaggerated, invented, misleading, only true
in some places without saying so, or not widely verifiable. Invented slang, signals or
"secret meanings" are a fail. Otherwise "pass".

Title: {plan.get("title")}
Script: {script}

Return JSON only: {{"verdict": "pass" or "fail", "problems": ["short reason", ...]}}"""
    try:
        result, _ = ask_ai(provider, prompt, max_tokens)
    except Exception:
        return ["fact-check could not run (kept as draft)"]
    if str(result.get("verdict", "")).lower() != "pass":
        return ["fact-check: " + "; ".join(result.get("problems") or ["failed"])]
    return []


PROVIDERS = {"gemini": ask_gemini, "groq": ask_groq,
             "ollama": ask_ollama, "claude": ask_claude}
AUTO_ORDER = ["gemini", "groq", "ollama", "claude"]


def ask_ai(provider, prompt, max_tokens):
    """Try providers in order until one answers. Returns (data, provider)."""
    order = AUTO_ORDER if provider == "auto" else [provider]
    reasons = []
    for name in order:
        try:
            print(f"Trying {name}...")
            return PROVIDERS[name](prompt, max_tokens), name
        except ProviderError as e:
            print(f"  {name} skipped: {e}")
            reasons.append(f"{name}: {e}")
        except requests.RequestException as e:
            print(f"  {name} network problem, skipping")
            reasons.append(f"{name}: network")
    raise ProviderError("; ".join(reasons))


def normalize_plan(plan):
    """AI replies are not always in the exact shape we asked for.
    Turn any odd format (lists inside lists, plain text, other key names)
    into clean sections: {"section", "narration", "visual_search"}."""
    title = str(plan.get("title") or "")
    script = plan.get("script")
    if isinstance(script, dict):
        script = script.get("sections") or list(script.values())
    flat = []

    def add(item):
        if isinstance(item, list):
            for x in item:
                add(x)
        elif isinstance(item, dict):
            nar = (item.get("narration") or item.get("text") or item.get("script")
                   or item.get("content") or "")
            if isinstance(nar, list):
                nar = " ".join(str(x) for x in nar)
            flat.append({
                "section": str(item.get("section") or item.get("title") or item.get("name")
                               or f"Part {len(flat) + 1}"),
                "narration": str(nar).strip(),
                "visual_search": str(item.get("visual_search") or item.get("visual")
                                     or item.get("broll") or title),
            })
        elif isinstance(item, str) and item.strip():
            flat.append({"section": f"Part {len(flat) + 1}", "narration": item.strip(),
                         "visual_search": title})

    add(script if script is not None else [])
    plan["script"] = [x for x in flat if x["narration"]]
    for key in ("tags", "hashtags", "fact_check_notes"):
        val = plan.get(key)
        if isinstance(val, str):
            plan[key] = [t.strip() for t in val.split(",") if t.strip()]
        elif not isinstance(val, list):
            plan[key] = []
        else:
            plan[key] = [str(t) for t in val if t]
    for key in ("title", "hook", "description", "thumbnail_text", "why_it_will_work"):
        if key in plan and not isinstance(plan[key], str):
            plan[key] = str(plan[key])
    return plan


def expand_long_script(plan, provider, channel=""):
    """Free AI models often write only ~400 words for a 'long' video.
    So we expand the script section by section until it is long enough."""
    secs = plan.get("script") or []
    if not secs:
        return plan
    words = sum(len(x["narration"].split()) for x in secs)
    per = max(150, 1300 // len(secs))
    outline = "\n".join(f"{n + 1}. {x['section']}" for n, x in enumerate(secs))
    print(f"  Script only {words} words, expanding {len(secs)} sections to ~{per} words each...")
    for n, sec in enumerate(secs):
        if n == 0:
            job = ("Start with a strong hook that promises exactly what viewers will learn. "
                   "Never open with 'Ever wonder', 'Did you know', 'Have you ever' or 'Hey guys'.")
        elif n == len(secs) - 1:
            job = ("Include a short recap of the main points, ask ONE question for the comments, "
                   "and tell viewers to watch another video on the channel.")
        else:
            job = "End with one curiosity line that makes people keep watching the next part."
        if n == max(1, len(secs) // 3):
            job += " Somewhere in this section add: 'If you're learning something, subscribe, it helps a lot.'"
        prompt = f"""Video title: {plan.get("title")}
Channel: {channel}
Full outline:
{outline}

Write the spoken narration for section {n + 1} "{sec['section']}" ONLY, about {per} words.
Current short draft of this section: {sec['narration']}

Rules: simple, friendly spoken English; concrete everyday examples; only well-known,
easy-to-verify facts; no statistics, studies or "experts say" unless famous and certain;
do not repeat other sections. {job}

Return JSON only: {{"narration": "..."}}"""
        try:
            res, _ = ask_ai(provider, prompt, 1500)
        except Exception:
            continue
        nar = res.get("narration") if isinstance(res, dict) else None
        if isinstance(nar, list):
            nar = " ".join(str(x) for x in nar)
        if isinstance(nar, str) and len(nar.split()) > len(sec["narration"].split()):
            sec["narration"] = nar.strip()
    first = secs[0]["narration"].split(". ")[0].strip()
    if first:
        plan["hook"] = first if first.endswith((".", "!", "?")) else first + "."
    new_words = sum(len(x["narration"].split()) for x in secs)
    print(f"  Script is now {new_words} words.")
    return plan


def quality_check(plan, fmt):
    """Automatic checks. Returns a list of problems (empty list = passed)."""
    problems = []
    script = plan.get("script") or []
    words = sum(len(s.get("narration", "").split()) for s in script)
    low, high = WORD_LIMITS[fmt]
    if not (low <= words <= high):
        problems.append(f"script length {words} words (want {low}-{high})")
    title = plan.get("title", "")
    if not title or len(title) > 100:
        problems.append("title missing or too long")
    if any(not s.get("visual_search") for s in script):
        problems.append("some sections have no visual")
    if not plan.get("description"):
        problems.append("description missing")
    if len(plan.get("tags") or []) < 5:
        problems.append("too few tags")
    # Risky facts: never auto-publish unverified numbers, studies or origins
    notes = " ".join(plan.get("fact_check_notes") or []).lower()
    risky = ("%", "percent", "study", "studies", "statistic", "source", "research",
             "origin", "survey", "data", "according", "accuracy", "verify", "claim")
    if notes and any(w in notes for w in risky):
        problems.append("contains uncertain facts (kept as draft for you to check)")
    return problems


def main():
    ap = argparse.ArgumentParser(description="Make original video plans from trends")
    ap.add_argument("--trends", default="trends.json")
    ap.add_argument("--category", help="Stick to one niche, e.g. 'Education'")
    ap.add_argument("--allowed", help="Comma list: pick the best trending of these categories")
    ap.add_argument("--channel", default="", help="Channel name, keeps videos on theme")
    ap.add_argument("--rotate", action="store_true", help="Rotate topic area daily")
    ap.add_argument("--core", help="Main channel topic, always used for plan 1, e.g. 'Autos & Vehicles'")
    ap.add_argument("--no-explore", action="store_true",
                    help="Do not test new topics: only core topic + proven winners")
    ap.add_argument("--format", choices=["auto", "short", "long"], default="auto")
    ap.add_argument("--count", type=int, default=3, help="How many plans to make")
    ap.add_argument("--language", default="English")
    ap.add_argument("--outdir", default="plans")
    ap.add_argument("--provider", choices=["auto"] + list(PROVIDERS), default="auto")
    ap.add_argument("--auto-approve", action="store_true",
                    help="Approve plans that pass quality checks (no manual review)")
    args = ap.parse_args()

    trends = load_trends(args.trends)
    allowed = [c.strip() for c in args.allowed.split(",")] if args.allowed else None
    fmt = pick_format(trends, args.format)
    count = max(1, min(args.count, 5 if fmt == "short" else 2))
    categories = smart_categories(trends, args.category, allowed, args.rotate, count, args.core,
                                  explore=not args.no_explore)
    category = categories[0]
    max_tokens = 8000 if fmt == "short" else 16000

    print(f"Category: {category} | Format: {fmt} | Plans: {count} | "
          f"Language: {args.language} | AI: {args.provider}")
    print("Asking AI for original ideas...")

    print(f"  Topics: {', '.join(categories)}")
    searches = []
    for c in dict.fromkeys(categories):
        searches += search_suggestions(c, 15)
    extra = ""
    if searches:
        print(f"  Found {len(searches)} real search topics")
        extra += ("Real searches people type on YouTube right now. When it fits the style, "
                  "make a video that answers ONE of these (search videos get views for "
                  "months). Only pick educational ones you can answer accurately:\n- "
                  + "\n- ".join(searches) + "\n\n")
    pend_path, pending = pending_series(args.outdir)
    extra += series_instruction(pending, count, fmt)
    if pending and fmt == "short":
        print(f"  Making Part 2 for series: {pending['series'].get('name')}")
    prompt = build_user_prompt(trends, category, fmt, args.language, count,
                               args.channel, past_titles(args.outdir), extra, categories)

    def get_plans(the_prompt):
        for attempt in range(2):
            try:
                d, u = ask_ai(args.provider, the_prompt, max_tokens)
                if isinstance(d, list):  # AI sent a bare list of plans
                    d = {"plans": d}
                if isinstance(d, dict) and not d.get("plans") and d.get("title"):
                    d = {"plans": [d]}  # AI sent a single plan
                if d and d.get("plans"):
                    if isinstance(d["plans"], dict):
                        d["plans"] = [d["plans"]]
                    return d, u
            except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                print("AI reply was not in the right format, trying again...")
            except ProviderError as e:
                sys.exit("\nNo AI could answer right now.\n" + str(e) +
                         "\nTip: add a free Groq key (set GROQ_API_KEY=...) as a backup.")
        sys.exit("Could not get valid plans. Please run again.")

    os.makedirs(args.outdir, exist_ok=True)
    # Long videos have many facts, so the fact-checker blocks them more often.
    # If that happens, ask for a NEW, safer idea (up to 2 more tries).
    rounds = 3 if (fmt == "long" and args.auto_approve) else 1
    rejected, first_data = [], None
    for rnd in range(rounds):
        the_prompt = prompt
        if rejected:
            the_prompt += ("\n\nIMPORTANT: these ideas were REJECTED by the fact-checker. Do NOT "
                           "use them or similar topics:\n"
                           + "\n".join(f'- "{t}": {why}' for t, why in rejected)
                           + "\nPick a different topic built only on simple, well-known, "
                             "easy-to-verify facts.\n")
        data, used = get_plans(the_prompt)
        first_data = first_data or data
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S") + (f"_r{rnd}" if rnd else "")
        approved_now = False
        data["plans"] = [normalize_plan(pl) for pl in data["plans"] if isinstance(pl, dict)]
        for i, plan in enumerate(data["plans"], 1):
            if fmt == "long":
                words_now = sum(len(x["narration"].split()) for x in plan.get("script", []))
                if words_now < WORD_LIMITS["long"][0]:
                    expand_long_script(plan, args.provider, args.channel)
            problems = quality_check(plan, fmt)
            if args.auto_approve and not problems:
                print(f"  Fact-checking idea {i}...")
                problems += fact_check(plan, args.provider)
            status = "approved" if (args.auto_approve and not problems) else "draft"
            approved_now |= status == "approved"
            if problems:
                rejected.append((plan.get("title", "?"), "; ".join(problems)[:200]))
            plan_cat = categories[min(i - 1, len(categories) - 1)]
            if plan.get("category") in CATEGORY_NAMES:  # the AI's honest label for the content
                plan_cat = plan["category"]
            if (pending and fmt == "short" and i == len(data["plans"])
                    and (plan.get("series") or {}).get("part") == 2):
                plan_cat = pending.get("category", plan_cat)  # Part 2 stays in Part 1's topic
            plan.update({
                "status": status,
                "quality_problems": problems,
                "ai_provider": used,
                "format": fmt,
                "category": plan_cat,
                "language": args.language,
                "created_at": datetime.now().isoformat(),
            })
            path = os.path.join(args.outdir, f"plan_{stamp}_{i}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(plan, f, ensure_ascii=False, indent=2)

            words = sum(len(s.get("narration", "").split()) for s in plan.get("script", []))
            print(f"\n[{i}] {plan.get('title')}  -> {status.upper()}")
            print(f"    Hook: {plan.get('hook')}")
            print(f"    Thumbnail: {plan.get('thumbnail_text')} | Script: {words} words")
            print(f"    Why: {plan.get('why_it_will_work')}")
            if plan.get("fact_check_notes"):
                print(f"    Check facts: {'; '.join(plan['fact_check_notes'])}")
            if problems:
                print(f"    Quality problems: {'; '.join(problems)}")
            print(f"    Saved: {path}")
        if approved_now or rnd == rounds - 1:
            break
        print(f"\n  Idea was blocked, trying a new idea ({rnd + 2}/{rounds})...")

    first = first_data["plans"][-1] if first_data and first_data.get("plans") else {}
    if (pending and fmt == "short" and (first.get("series") or {}).get("part") == 2
            and first.get("status") == "approved"):
        pending["series_done"] = True
        with open(pend_path, "w", encoding="utf-8") as f:
            json.dump(pending, f, ensure_ascii=False, indent=2)
        print("  Series Part 2 is ready.")

    if args.auto_approve:
        print("\nAuto mode: plans that passed checks are approved for the video maker.")
    else:
        print("\nNext: open each plan, check the facts, edit anything you like,")
        print('then change "status": "draft" to "status": "approved".')


if __name__ == "__main__":
    main()
