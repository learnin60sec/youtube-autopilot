"""
YouTube Trend Finder  (Part 1 of the YouTube automation project)
-----------------------------------------------------------------
Finds what is trending on top of YouTube right now, scores every video,
ranks categories by trend strength AND earning potential, and saves the
results to trends.json so the next script (idea + video maker) can use them.

Setup:
    pip install -r requirements.txt
    Set your API key:
        Windows (cmd):   set YT_API_KEY=your_key_here
        Mac/Linux:       export YT_API_KEY=your_key_here

Run:
    python trend_finder.py                 # default region US
    python trend_finder.py --region IN     # India
    python trend_finder.py --region US --top 20
"""

import os
import re
import sys
import json
import math
import argparse
from datetime import datetime, timezone
from collections import Counter, defaultdict

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Rough earning (RPM) tiers by category. These are general estimates only,
# real earnings depend on audience country, video length and advertisers.
HIGH_RPM = {"Education", "Science & Technology", "Howto & Style",
            "Autos & Vehicles", "News & Politics"}
LOW_RPM = {"Music", "Gaming", "Entertainment", "Comedy",
           "Film & Animation"}
RPM_WEIGHT = {"high": 1.3, "medium": 1.0, "low": 0.8}

STOPWORDS = set("""
the and for with you your this that from are was were have has had not but
all any can our out new how what why who when will just into about more most
get got its it's they them their there here one two off over than then too
very also only like official video full episode part vs amp live shorts short
hai hain aur mein kya kar karo nahi wala wali ki ka ke se ko
his her hers she him he they we me my mine you'll i'm don't can't
fyp foryou foryoupage edit viral bro trending subscribe
""".split())

SHORT_MAX_SECONDS = 180  # YouTube Shorts can be up to 3 minutes


def rpm_tier(category_name):
    if category_name in HIGH_RPM:
        return "high"
    if category_name in LOW_RPM:
        return "low"
    return "medium"


def parse_duration(iso):
    """Convert ISO 8601 duration like PT1H2M30S into seconds."""
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def get_categories(yt, region):
    res = yt.videoCategories().list(part="snippet", regionCode=region).execute()
    return {c["id"]: c["snippet"]["title"]
            for c in res.get("items", [])
            if c["snippet"].get("assignable")}


def get_trending(yt, region, category_id=None, max_results=50):
    params = dict(part="snippet,statistics,contentDetails",
                  chart="mostPopular", regionCode=region,
                  maxResults=max_results)
    if category_id:
        params["videoCategoryId"] = category_id
    try:
        return yt.videos().list(**params).execute().get("items", [])
    except HttpError:
        return []  # some categories have no trending chart


def get_channel_subs(yt, channel_ids):
    subs = {}
    ids = list(channel_ids)
    for i in range(0, len(ids), 50):
        res = yt.channels().list(part="statistics",
                                 id=",".join(ids[i:i + 50])).execute()
        for ch in res.get("items", []):
            st = ch.get("statistics", {})
            if st.get("hiddenSubscriberCount"):
                subs[ch["id"]] = None
            else:
                subs[ch["id"]] = int(st.get("subscriberCount", 0))
    return subs


def score_video(v, subs, now):
    st = v.get("statistics", {})
    views = int(st.get("viewCount", 0))
    likes_hidden = "likeCount" not in st
    likes = int(st.get("likeCount", 0))
    comments = int(st.get("commentCount", 0))
    published = datetime.fromisoformat(
        v["snippet"]["publishedAt"].replace("Z", "+00:00"))
    age_hours = max((now - published).total_seconds() / 3600, 1)

    views_per_hour = views / age_hours
    # If the creator hid likes, use a typical 3% so the video is not punished
    like_rate = 0.03 if likes_hidden else (likes / views if views else 0)
    comment_rate = comments / views if views else 0
    # Outlier: views compared to channel size. High = the TOPIC is strong,
    # not just a big channel.
    outlier = views / max(subs, 1000) if subs else None

    score = (math.log10(views_per_hour + 1)
             + like_rate * 100 * 0.5
             + comment_rate * 1000 * 0.2
             + (math.log10(outlier + 1) * 2 if outlier else 0))

    return {
        "views": views, "likes": likes, "comments": comments,
        "age_hours": round(age_hours, 1),
        "views_per_hour": round(views_per_hour),
        "like_rate_pct": None if likes_hidden else round(like_rate * 100, 2),
        "outlier": round(outlier, 2) if outlier else None,
        "score": round(score, 2),
    }


def title_keywords(videos, top_n=25):
    counter = Counter()
    for v in videos:
        # Remove #hashtags and @channel names so only real topic words remain
        clean = re.sub(r"[#@]\S+", " ", v["title"].lower())
        words = [w for w in re.findall(r"[a-zA-Z']+", clean)
                 if len(w) >= 3 and w not in STOPWORDS]
        for w in set(words):
            counter[w] += v["score"]
        for a, b in set(zip(words, words[1:])):
            counter[f"{a} {b}"] += v["score"] * 1.5
    return [k for k, _ in counter.most_common(top_n)]


def main():
    ap = argparse.ArgumentParser(description="Find top trending YouTube topics")
    ap.add_argument("--region", default="US", help="Country code, e.g. US, IN, GB")
    ap.add_argument("--top", type=int, default=15, help="How many top videos to show")
    ap.add_argument("--out", default="trends.json")
    args = ap.parse_args()

    api_key = os.getenv("YT_API_KEY")
    if not api_key:
        sys.exit("Error: set your YouTube API key in the YT_API_KEY environment variable.")

    yt = build("youtube", "v3", developerKey=api_key)
    now = datetime.now(timezone.utc)

    print(f"Scanning trending videos in {args.region}...")
    categories = get_categories(yt, args.region)

    raw = {}
    for v in get_trending(yt, args.region):
        raw[v["id"]] = v
    for cat_id in categories:
        for v in get_trending(yt, args.region, cat_id):
            raw[v["id"]] = v

    if not raw:
        sys.exit("No trending videos found. Check your API key and region code.")

    subs = get_channel_subs(yt, {v["snippet"]["channelId"] for v in raw.values()})

    videos = []
    for v in raw.values():
        cat_name = categories.get(v["snippet"].get("categoryId"), "Other")
        seconds = parse_duration(v["contentDetails"].get("duration"))
        info = score_video(v, subs.get(v["snippet"]["channelId"]), now)
        info.update({
            "id": v["id"],
            "url": f"https://www.youtube.com/watch?v={v['id']}",
            "title": v["snippet"]["title"],
            "channel": v["snippet"]["channelTitle"],
            "category": cat_name,
            "rpm_tier": rpm_tier(cat_name),
            "duration_sec": seconds,
            "format": "short" if seconds <= SHORT_MAX_SECONDS else "long",
            "tags": v["snippet"].get("tags", [])[:10],
        })
        videos.append(info)

    videos.sort(key=lambda x: x["score"], reverse=True)

    # Rank categories: trend strength x earning potential
    by_cat = defaultdict(list)
    for v in videos:
        by_cat[v["category"]].append(v)
    cat_rank = []
    for name, items in by_cat.items():
        if len(items) < 3:
            continue  # too little data
        avg = sum(i["score"] for i in items) / len(items)
        tier = rpm_tier(name)
        cat_rank.append({
            "category": name, "videos": len(items),
            "avg_trend_score": round(avg, 2), "rpm_tier": tier,
            "final_score": round(avg * RPM_WEIGHT[tier], 2),
            "keywords": title_keywords(items, 10),
        })
    cat_rank.sort(key=lambda x: x["final_score"], reverse=True)

    fmt = defaultdict(list)
    for v in videos:
        fmt[v["format"]].append(v["score"])
    format_scores = {k: round(sum(s) / len(s), 2) for k, s in fmt.items()}

    # ---------- Report ----------
    print(f"\nAnalyzed {len(videos)} trending videos\n")
    print("TOP CATEGORIES (trend x earning potential)")
    print("-" * 60)
    for c in cat_rank[:10]:
        print(f"{c['final_score']:>6}  {c['category']:<25} "
              f"earning: {c['rpm_tier']:<7} ({c['videos']} videos)")

    print(f"\nTOP {args.top} TRENDING VIDEOS")
    print("-" * 60)
    for v in videos[:args.top]:
        print(f"{v['score']:>6}  [{v['format']}] {v['title'][:70]}")
        likes_txt = "likes hidden" if v["like_rate_pct"] is None else f"{v['like_rate_pct']}% likes"
        print(f"        {v['views']:,} views | {likes_txt} | "
              f"{v['views_per_hour']:,}/hr | {v['category']}")

    print("\nHOT KEYWORDS:", ", ".join(title_keywords(videos, 15)))
    print("FORMAT SCORES:", format_scores)

    if cat_rank:
        best = cat_rank[0]
        print(f"\nRECOMMENDED CATEGORY: {best['category']} "
              f"(earning potential: {best['rpm_tier']})")
        print("Ideas to explore:", ", ".join(best["keywords"][:8]))

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": now.isoformat(),
            "region": args.region,
            "recommended_category": cat_rank[0] if cat_rank else None,
            "categories": cat_rank,
            "format_scores": format_scores,
            "hot_keywords": title_keywords(videos, 25),
            "top_videos": videos[:50],
        }, f, ensure_ascii=False, indent=2)
    print(f"\nSaved results to {args.out}")


if __name__ == "__main__":
    main()
