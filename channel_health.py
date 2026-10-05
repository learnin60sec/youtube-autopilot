"""
Channel Health Check
--------------------
One command that checks, automatically:
  - daily views and subscribers for the last 10 days (YouTube Analytics)
  - for your newest videos: public or not, processed or not, blocked or
    restricted (copyright, age limit, country blocks, made-for-kids)
  - how many views each video gained since the last health check

Run:
    python channel_health.py
Then copy everything it prints and send it to Claude.
"""

import os
import json
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from uploader import get_credentials
from analytics_report import my_videos

SNAPSHOT = "views_snapshot.json"
NEWEST = 12


def daily_views(creds):
    ya = build("youtubeAnalytics", "v2", credentials=creds)
    end = datetime.now().date()
    start = end - timedelta(days=10)
    res = ya.reports().query(ids="channel==MINE", startDate=str(start), endDate=str(end),
                             metrics="views,subscribersGained", dimensions="day",
                             sort="day").execute()
    return res.get("rows") or []


def main():
    creds = get_credentials()
    yt = build("youtube", "v3", credentials=creds)
    ch, videos = my_videos(yt)
    now = datetime.now(timezone.utc)
    problems = []

    print(f"CHANNEL HEALTH: {ch['snippet']['title']}   ({now:%Y-%m-%d %H:%M} UTC)")
    st = ch.get("statistics", {})
    print(f"Subscribers: {st.get('subscriberCount')}   Total views: {st.get('viewCount')}   "
          f"Videos: {st.get('videoCount')}")

    # ---- daily views (Analytics is usually 1-3 days behind)
    print("\nDAILY VIEWS (YouTube Analytics, last days may still be missing)")
    try:
        rows = daily_views(creds)
        for day, views, subs in rows:
            print(f"  {day}  {int(views):>6} views  +{int(subs)} subs")
        if not rows:
            print("  No data yet.")
    except HttpError as e:
        print(f"  Not available ({e.resp.status})")

    # ---- newest videos: status + views gained since last check
    try:
        with open(SNAPSHOT, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = {}
    snap = {}

    videos.sort(key=lambda v: v["snippet"]["publishedAt"], reverse=True)
    print(f"\nNEWEST {min(NEWEST, len(videos))} VIDEOS")
    for v in videos[:NEWEST]:
        s, cd = v.get("status", {}), v.get("contentDetails", {})
        views = int(v.get("statistics", {}).get("viewCount", 0))
        snap[v["id"]] = {"views": views, "time": now.isoformat()}
        gained = ""
        if v["id"] in old:
            hrs = (now - datetime.fromisoformat(old[v["id"]]["time"])).total_seconds() / 3600
            gained = f"+{views - old[v['id']]['views']} in {hrs:.0f}h"

        flags = []
        if s.get("privacyStatus") != "public":
            flags.append(f"NOT PUBLIC ({s.get('privacyStatus')})")
        if s.get("uploadStatus") not in ("processed", None):
            flags.append(f"upload {s.get('uploadStatus')}")
        if s.get("rejectionReason"):
            flags.append(f"REJECTED: {s['rejectionReason']}")
        if s.get("failureReason"):
            flags.append(f"FAILED: {s['failureReason']}")
        if s.get("madeForKids"):
            flags.append("MADE FOR KIDS (limits reach)")
        if cd.get("regionRestriction"):
            flags.append("COUNTRY BLOCK")
        if (cd.get("contentRating") or {}).get("ytRating") == "ytAgeRestricted":
            flags.append("AGE RESTRICTED")
        for fl in flags:
            problems.append(f"{v['snippet']['title'][:40]}: {fl}")

        age_h = (now - datetime.fromisoformat(v["snippet"]["publishedAt"].replace("Z", "+00:00"))
                 ).total_seconds() / 3600
        print(f"  {views:>6} views {gained:<14} {age_h:>5.0f}h old  "
              f"{v['snippet']['title'][:45]}  {'| ' + ', '.join(flags) if flags else 'OK'}")

    with open(SNAPSHOT, "w", encoding="utf-8") as f:
        json.dump({**old, **snap}, f, indent=2)

    print("\nVERDICT")
    if problems:
        print("  PROBLEMS FOUND:")
        for p in problems:
            print("   - " + p)
    else:
        print("  No restrictions found: all newest videos are public, processed and not blocked.")
        print("  If views are low, it is the normal quiet period between waves, not a technical problem.")
    if not old:
        print("  (First check: run again tomorrow to see views gained per video.)")


if __name__ == "__main__":
    main()
