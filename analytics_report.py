"""
Channel Smart Report  (growth add-on)
-------------------------------------
Checks how YOUR videos are doing, finds what works best, and saves it to
performance.json. idea_maker.py reads that file and makes more videos like
your winners and fewer like your losers.

Also shows your progress toward monetization.

Run:
    python analytics_report.py
Uses the same login as uploader.py (token.json), no extra setup.
"""

import os
import re
import json
import math
from datetime import datetime, timezone
from collections import defaultdict

from datetime import timedelta
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from uploader import get_credentials

OUT = "performance.json"
MIN_AGE_DAYS = 1.0  # judge a video only after 1 day online


def parse_duration(iso):
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    d, h, mi, s = (int(x) if x else 0 for x in m.groups()) if m else (0, 0, 0, 0)
    return d * 86400 + h * 3600 + mi * 60 + s


DRIVING_WORDS = re.compile(
    r"\b(driv\w*|car|cars|brak\w*|steer\w*|turn|turning|park\w*|biker\w*|bike|"
    r"motorcycl\w*|helmet|lane|traffic|road|tire|tyre|engine|highway|ice)\b", re.I)


def real_category(title, label):
    """Some driving videos were made in another topic's slot and got the wrong label."""
    return "Autos & Vehicles" if DRIVING_WORDS.search(title or "") else label


def plan_lookup():
    """youtube_id -> plan info (category, format)."""
    info = {}
    for p in os.listdir("plans") if os.path.isdir("plans") else []:
        if not p.endswith(".json"):
            continue
        try:
            with open(os.path.join("plans", p), encoding="utf-8") as f:
                plan = json.load(f)
        except (OSError, ValueError):
            continue
        if plan.get("youtube_id"):
            info[plan["youtube_id"]] = plan
    return info


def my_videos(yt):
    ch = yt.channels().list(part="contentDetails,statistics,snippet", mine=True).execute()["items"][0]
    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, token = [], None
    while len(ids) < 300:
        res = yt.playlistItems().list(part="contentDetails", playlistId=uploads,
                                      maxResults=50, pageToken=token).execute()
        ids += [i["contentDetails"]["videoId"] for i in res.get("items", [])]
        token = res.get("nextPageToken")
        if not token:
            break
    videos = []
    for i in range(0, len(ids), 50):
        res = yt.videos().list(part="snippet,statistics,contentDetails,status",
                               id=",".join(ids[i:i + 50])).execute()
        videos += res.get("items", [])
    return ch, videos


def watch_data(creds, fmt_of):
    """Real watch time, % watched, subscribers gained, and where viewers leave."""
    ya = build("youtubeAnalytics", "v2", credentials=creds)
    end = datetime.now().date()
    start = end - timedelta(days=90)
    res = ya.reports().query(
        ids="channel==MINE", startDate=str(start), endDate=str(end),
        metrics="views,estimatedMinutesWatched,averageViewDuration,"
                "averageViewPercentage,subscribersGained",
        dimensions="video", sort="-views", maxResults=50).execute()
    cols = [h["name"] for h in res.get("columnHeaders", [])]
    rows = [dict(zip(cols, r)) for r in (res.get("rows") or [])]

    for r in rows[:10]:  # where do most viewers leave? (only for the top videos)
        r["leave_at_pct"] = None
        try:
            curve = ya.reports().query(
                ids="channel==MINE", startDate=str(start), endDate=str(end),
                metrics="audienceWatchRatio", dimensions="elapsedVideoTimeRatio",
                filters=f"video=={r['video']}").execute().get("rows") or []
            for ratio, watch in curve:
                if watch < 0.5:
                    r["leave_at_pct"] = round(ratio * 100)
                    break
        except HttpError:
            pass

    tips = []
    shorts = [r for r in rows if fmt_of.get(r["video"]) == "short" and r["views"] >= 5]
    longs = [r for r in rows if fmt_of.get(r["video"]) == "long" and r["views"] >= 5]
    avg_s = round(sum(r["averageViewPercentage"] for r in shorts) / len(shorts), 1) if shorts else None
    avg_l = round(sum(r["averageViewPercentage"] for r in longs) / len(longs), 1) if longs else None
    early = [r for r in rows if r.get("leave_at_pct") is not None and r["leave_at_pct"] <= 15]
    if early:
        tips.append("Many viewers leave in the first seconds: make hooks shorter, bolder "
                    "and more surprising; show the payoff immediately.")
    if avg_s is not None and avg_s < 70:
        tips.append("Shorts are watched less than 70%: cut words, get to the point faster, "
                    "keep Shorts nearer 20-30 seconds.")
    if avg_l is not None and avg_l < 35:
        tips.append("Long videos lose viewers: shorter intro, more curiosity lines, "
                    "and more concrete examples in each section.")
    long_minutes = sum(r["estimatedMinutesWatched"] for r in longs)
    return rows, {"avg_view_pct_shorts": avg_s, "avg_view_pct_long": avg_l,
                  "long_watch_hours_90d": round(long_minutes / 60, 1), "tips": tips}


def main():
    creds = get_credentials()
    yt = build("youtube", "v3", credentials=creds)
    ch, raw = my_videos(yt)
    plans = plan_lookup()
    now = datetime.now(timezone.utc)

    videos = []
    for v in raw:
        if v["status"].get("privacyStatus") != "public":
            continue
        st = v.get("statistics", {})
        views = int(st.get("viewCount", 0))
        likes = int(st.get("likeCount", 0))
        comments = int(st.get("commentCount", 0))
        published = datetime.fromisoformat(v["snippet"]["publishedAt"].replace("Z", "+00:00"))
        age = max((now - published).total_seconds() / 86400, 0.1)
        seconds = parse_duration(v["contentDetails"].get("duration"))
        plan = plans.get(v["id"], {})
        videos.append({
            "id": v["id"], "title": v["snippet"]["title"],
            "views": views, "likes": likes, "comments": comments,
            "age_days": round(age, 1),
            "views_per_day": round(views / max(age, 1), 1),
            "like_rate_pct": round(likes / views * 100, 1) if views else 0,
            "format": plan.get("format") or ("short" if seconds <= 180 else "long"),
            "category": real_category(v["snippet"]["title"], plan.get("category", "Unknown")),
            "hook": plan.get("hook", ""),
            "published": published.isoformat(),
        })

    judged = [v for v in videos if v["age_days"] >= MIN_AGE_DAYS]
    for v in judged:
        v["score"] = round(math.log10(v["views_per_day"] + 1) * 10
                           + v["like_rate_pct"] * 0.5 + v["comments"] * 0.5, 2)
    judged.sort(key=lambda x: x["score"], reverse=True)

    by_cat = defaultdict(list)
    for v in judged:
        by_cat[v["category"]].append(v["views_per_day"])
    cat_avg = {c: round(sum(x) / len(x), 1) for c, x in by_cat.items()}

    subs = int(ch["statistics"].get("subscriberCount", 0))
    shorts_90 = sum(v["views"] for v in videos if v["format"] == "short"
                    and (now - datetime.fromisoformat(v["published"])).days <= 90)

    fmt_of = {v["id"]: v["format"] for v in videos}
    title_of = {v["id"]: v["title"] for v in videos}
    try:
        rows, retention = watch_data(creds, fmt_of)
    except HttpError as e:
        rows, retention = [], {"tips": [], "error": f"analytics not available yet ({e.resp.status})"}
    top_subs = sorted([r for r in rows if r.get("subscribersGained", 0) > 0],
                      key=lambda r: r["subscribersGained"], reverse=True)[:5]
    retention["best_for_subscribers"] = [
        {"title": title_of.get(r["video"], r["video"]), "subscribers": r["subscribersGained"]}
        for r in top_subs]

    report = {
        "generated_at": now.isoformat(),
        "subscribers": subs,
        "total_views": int(ch["statistics"].get("viewCount", 0)),
        "public_videos": len(videos),
        "shorts_views_90_days": shorts_90,
        "best": judged[:5],
        "worst": judged[-3:] if len(judged) >= 6 else [],
        "category_views_per_day": cat_avg,
        "category_video_counts": {c: len(x) for c, x in by_cat.items()},
        "retention": retention,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"CHANNEL: {ch['snippet']['title']}")
    print(f"Subscribers: {subs:,}   Total views: {report['total_views']:,}   Public videos: {len(videos)}")
    print("\nMONETIZATION PROGRESS (YouTube Partner Program)")
    print(f"  Subscribers:          {subs:,} / 1,000  ({min(subs / 10, 100):.1f}%)")
    print(f"  Shorts views (90 d):  {shorts_90:,} / 10,000,000  ({min(shorts_90 / 100000, 100):.2f}%)")
    print(f"  Long-video watch hours (90 d, approx): "
          f"{retention.get('long_watch_hours_90d', 0)} / 4,000 (official number: Studio > Earn)")

    print("\nWATCH TIME")
    if retention.get("error"):
        print("  " + retention["error"])
    for r in rows[:8]:
        leave = f"most leave at {r['leave_at_pct']}%" if r.get("leave_at_pct") is not None else ""
        print(f"  {r['averageViewPercentage']:>5.1f}% watched  +{r['subscribersGained']} subs  "
              f"{title_of.get(r['video'], r['video'])[:45]}  {leave}")
    if retention.get("avg_view_pct_shorts") is not None:
        print(f"  Average % watched: Shorts {retention['avg_view_pct_shorts']}%"
              + (f", Long {retention['avg_view_pct_long']}%" if retention.get('avg_view_pct_long') is not None else ""))
    for t in retention.get("tips", []):
        print("  TIP: " + t)

    if judged:
        print("\nBEST VIDEOS (make more like these)")
        for v in judged[:5]:
            print(f"  {v['views_per_day']:>8}/day  {v['like_rate_pct']}% likes  {v['title'][:60]}")
    if report["worst"]:
        print("\nWEAKEST VIDEOS (avoid this style)")
        for v in report["worst"]:
            print(f"  {v['views_per_day']:>8}/day  {v['title'][:60]}")
    if cat_avg:
        print("\nVIEWS PER DAY BY TOPIC:", cat_avg)
    if not judged:
        print("\nVideos are still new. The report gets useful after a few days online.")
    print(f"\nSaved {OUT} (idea_maker.py uses it automatically)")


if __name__ == "__main__":
    main()
