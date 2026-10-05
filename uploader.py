"""
YouTube Auto Uploader  (Part 4 of the YouTube automation project)
-----------------------------------------------------------------
Uploads finished videos (status "video_ready", made by video_maker.py) to
YOUR YouTube channel with title, description, hashtags, tags, category
and thumbnail.

One-time setup:
    1. Put client_secret.json (OAuth "Desktop app" credentials from Google
       Cloud) in this folder.
    2. pip install -r requirements.txt
    3. The first run opens your browser: sign in to the Google account that
       owns your channel and click Allow. A token.json file is saved, so
       future runs are automatic.

Run:
    python uploader.py --dry-run          # show what WOULD be uploaded
    python uploader.py                    # upload all ready videos (max 3)
    python uploader.py --privacy unlisted
    python uploader.py --plan plans\\plan_xxx_1.json
    python uploader.py --publish-at 2026-10-01T15:00:00Z   # schedule (UTC)

Note: Google keeps videos uploaded by new, unaudited API projects PRIVATE.
Either switch them to Public in YouTube Studio, or request an API audit
(see the message this script prints).
"""

import os
import sys
import glob
import json
import time
import random
import argparse

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube",
          "https://www.googleapis.com/auth/yt-analytics.readonly"]
CLIENT_SECRET = "client_secret.json"
TOKEN_FILE = "token.json"
LOG_FILE = "upload_log.json"
CHANNEL_HANDLE = "@LearnIn60SecondsDaily"
SUBSCRIBE_URL = f"https://www.youtube.com/{CHANNEL_HANDLE}?sub_confirmation=1"
PLAYLIST_CACHE = "playlists.json"

# Topic playlists: viewers binge more when videos are grouped
PLAYLISTS = {
    "Autos & Vehicles": "Driving & Car Tips in 60 Seconds",
    "Science & Technology": "Science & Tech Explained Fast",
    "Howto & Style": "Smart How-To Hacks",
    "Education": "Learn Something New Every Day",
}
DEFAULT_PLAYLIST = "Learn Something New Every Day"
LONG_PLAYLIST = "Full Guides (Long Videos)"

CATEGORY_IDS = {
    "Film & Animation": "1", "Autos & Vehicles": "2", "Music": "10",
    "Pets & Animals": "15", "Sports": "17", "Travel & Events": "19",
    "Gaming": "20", "People & Blogs": "22", "Comedy": "23",
    "Entertainment": "24", "News & Politics": "25", "Howto & Style": "26",
    "Education": "27", "Science & Technology": "28",
    "Nonprofits & Activism": "29",
}
LANG_CODES = {"english": "en", "hindi": "hi"}
RETRY_CODES = (500, 502, 503, 504)


def get_credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, encoding="utf-8") as f:
                granted = set(json.load(f).get("scopes") or [])
        except (OSError, ValueError):
            granted = set()
        if set(SCOPES) <= granted:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        else:
            print("New permission needed (channel analytics). Please sign in again once.")
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None
    if not creds or not creds.valid:
        if not os.path.exists(CLIENT_SECRET):
            sys.exit(f"Error: {CLIENT_SECRET} not found in this folder. "
                     "Download it from Google Cloud (OAuth client, Desktop app).")
        if os.getenv("GITHUB_ACTIONS"):
            sys.exit("YouTube login expired or missing in the cloud. On the laptop run "
                     "'python analytics_report.py' to sign in again, then copy the new "
                     "token.json into the TOKEN_JSON secret on GitHub.")
        print("Opening your browser. Sign in with your YouTube channel account and click Allow...")
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
        creds = flow.run_local_server(port=0, timeout_seconds=600)
        if not creds:
            sys.exit("Sign-in was not completed.")
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    return creds


def get_youtube():
    return build("youtube", "v3", credentials=get_credentials())


def clean_tags(tags):
    out, total = [], 0
    for t in tags or []:
        t = str(t).replace("#", "").replace(",", " ").replace("<", "").replace(">", "").strip()
        if not t or t.lower() in (x.lower() for x in out):
            continue
        cost = len(t) + (2 if " " in t else 0) + 1
        if total + cost > 480:
            break
        out.append(t)
        total += cost
    return out


def fmt_time(t):
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def chapters_text(plan):
    """YouTube chapters: first at 0:00, at least 3, each 10+ seconds apart."""
    ch = [c for c in plan.get("chapters") or [] if c.get("title")]
    if not ch:
        return ""
    ch[0] = dict(ch[0], t=0)
    clean = [ch[0]]
    for c in ch[1:]:
        if c["t"] - clean[-1]["t"] >= 10:
            clean.append(c)
    if len(clean) < 3:
        return ""
    return "Chapters:\n" + "\n".join(f"{fmt_time(c['t'])} {c['title']}" for c in clean)


def latest_long_url(plans_dir="plans"):
    best = None
    for p in glob.glob(os.path.join(plans_dir, "*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                pl = json.load(f)
        except (OSError, ValueError):
            continue
        if pl.get("format") == "long" and pl.get("youtube_url"):
            if not best or pl.get("uploaded_at", "") > best.get("uploaded_at", ""):
                best = pl
    return (best["youtube_url"], best.get("title", "")) if best else (None, None)


def build_metadata(plan, privacy, publish_at, links=None):
    title = (plan.get("title") or "New video").replace("<", "").replace(">", "").strip()
    hashtags = [h if h.startswith("#") else f"#{h}"
                for h in (plan.get("hashtags") or []) if h]
    is_short = plan.get("format") == "short" and (plan.get("duration_sec") or 0) <= 180
    if is_short and "#shorts" not in " ".join(hashtags).lower():
        hashtags.append("#Shorts")

    parts = [plan.get("description", "").strip()]
    if plan.get("format") == "long":
        parts.append(chapters_text(plan))
    parts += list(links or [])
    parts.append(" ".join(hashtags[:5]))
    if plan.get("credits"):
        parts.append("Stock footage:\n" + "\n".join(plan["credits"]))
    description = "\n\n".join(p for p in parts if p).replace("<", "").replace(">", "")

    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False,
              "embeddable": True}
    if publish_at:
        status["privacyStatus"] = "private"  # required for scheduling
        status["publishAt"] = publish_at

    lang = LANG_CODES.get((plan.get("language") or "english").lower(), "en")
    return {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": clean_tags(plan.get("tags")),
            "categoryId": CATEGORY_IDS.get(plan.get("category"), "27"),
            "defaultLanguage": lang,
            "defaultAudioLanguage": lang,
        },
        "status": status,
    }


def resumable_upload(request):
    response, tries = None, 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                print(f"    uploading... {int(status.progress() * 100)}%", end="\r")
        except HttpError as e:
            if e.resp.status not in RETRY_CODES:
                raise
            tries += 1
        except (ConnectionError, TimeoutError, OSError):
            tries += 1
        else:
            continue
        if tries > 8:
            raise RuntimeError("Upload failed after many retries.")
        wait = min(2 ** tries + random.random(), 60)
        print(f"    network problem, retrying in {wait:.0f}s...")
        time.sleep(wait)
    print("    uploading... 100%")
    return response


def playlist_id(yt, name):
    cache = {}
    if os.path.exists(PLAYLIST_CACHE):
        with open(PLAYLIST_CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    if name in cache:
        return cache[name]
    token = None
    while True:  # look for an existing playlist with this name
        res = yt.playlists().list(part="snippet", mine=True, maxResults=50,
                                  pageToken=token).execute()
        for pl in res.get("items", []):
            if pl["snippet"]["title"] == name:
                cache[name] = pl["id"]
        token = res.get("nextPageToken")
        if name in cache or not token:
            break
    if name not in cache:
        pl = yt.playlists().insert(part="snippet,status", body={
            "snippet": {"title": name,
                        "description": f"{name}. Quick lessons from Learn in 60 Seconds."},
            "status": {"privacyStatus": "public"}}).execute()
        cache[name] = pl["id"]
        print(f"    created playlist: {name}")
    with open(PLAYLIST_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    return cache[name]


def playlist_name(plan):
    return (LONG_PLAYLIST if plan.get("format") == "long"
            else PLAYLISTS.get(plan.get("category"), DEFAULT_PLAYLIST))


def add_to_playlist(yt, plan, video_id):
    name = playlist_name(plan)
    try:
        yt.playlistItems().insert(part="snippet", body={"snippet": {
            "playlistId": playlist_id(yt, name),
            "resourceId": {"kind": "youtube#video", "videoId": video_id}}}).execute()
        print(f"    added to playlist: {name}")
        return name
    except HttpError as e:
        print(f"    playlist not updated ({e.resp.status})")
        return None


def backfill_playlists(yt, plans_dir):
    """Put already-uploaded PUBLIC videos into their playlists (run once)."""
    for p in sorted(glob.glob(os.path.join(plans_dir, "*.json"))):
        with open(p, encoding="utf-8") as f:
            plan = json.load(f)
        vid = plan.get("youtube_id")
        if plan.get("status") != "uploaded" or not vid or plan.get("playlist"):
            continue
        items = yt.videos().list(part="status", id=vid).execute().get("items", [])
        if not items or items[0]["status"].get("privacyStatus") != "public":
            continue  # skip deleted or private videos
        print(f"{plan.get('title')}")
        name = add_to_playlist(yt, plan, vid)
        if name:
            plan["playlist"] = name
            with open(p, "w", encoding="utf-8") as f:
                json.dump(plan, f, ensure_ascii=False, indent=2)


def upload_plan(yt, plan_path, privacy, publish_at):
    with open(plan_path, encoding="utf-8") as f:
        plan = json.load(f)
    video = plan.get("video_file")
    if not video or not os.path.exists(video):
        raise RuntimeError("Video file not found. Run video_maker.py first.")

    links = []
    try:
        pid = playlist_id(yt, playlist_name(plan))
        links.append(f"▶ More like this: https://www.youtube.com/playlist?list={pid}")
    except HttpError:
        pass
    long_url, long_title = latest_long_url()
    if long_url and plan.get("format") != "long":
        links.append(f"📺 Full guide: {long_title}\n{long_url}")
    links.append(f"🔔 Subscribe for a new 60-second lesson every day: {SUBSCRIBE_URL}")
    body = build_metadata(plan, privacy, publish_at, links)
    media = MediaFileUpload(video, mimetype="video/mp4", chunksize=8 * 1024 * 1024,
                            resumable=True)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    video_id = resumable_upload(request)["id"]
    url = f"https://youtu.be/{video_id}"

    thumb = plan.get("thumbnail_file")
    if thumb and os.path.exists(thumb):
        try:
            yt.thumbnails().set(videoId=video_id,
                                media_body=MediaFileUpload(thumb, mimetype="image/jpeg")).execute()
            print("    thumbnail set")
        except HttpError as e:
            print(f"    thumbnail not set ({e.resp.status}). Custom thumbnails need a "
                  "phone-verified channel: youtube.com/verify")

    plan["playlist"] = add_to_playlist(yt, plan, video_id)
    ser = plan.get("series") or {}
    if ser.get("name"):
        try:
            yt.playlistItems().insert(part="snippet", body={"snippet": {
                "playlistId": playlist_id(yt, f"{ser['name']} (Series)"),
                "resourceId": {"kind": "youtube#video", "videoId": video_id}}}).execute()
            print(f"    added to series playlist: {ser['name']}")
        except HttpError:
            pass

    locked = False
    try:
        st = yt.videos().list(part="status", id=video_id).execute()["items"][0]["status"]
        locked = body["status"]["privacyStatus"] != "private" and st.get("privacyStatus") == "private"
    except (HttpError, KeyError, IndexError):
        pass

    plan.update({"status": "uploaded", "youtube_id": video_id, "youtube_url": url,
                 "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "privacy_locked": locked})
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)

    log = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, encoding="utf-8") as f:
            log = json.load(f)
    log.append({"title": body["snippet"]["title"], "url": url,
                "time": plan["uploaded_at"], "plan": plan_path})
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    return url, locked


def main():
    ap = argparse.ArgumentParser(description="Upload ready videos to YouTube")
    ap.add_argument("--plan", help="Upload just this plan file")
    ap.add_argument("--plans-dir", default="plans")
    ap.add_argument("--privacy", choices=["public", "unlisted", "private"], default="public")
    ap.add_argument("--publish-at", help="Schedule time in UTC, e.g. 2026-10-01T15:00:00Z")
    ap.add_argument("--max", type=int, default=3, help="Max uploads this run (daily quota is limited)")
    ap.add_argument("--dry-run", action="store_true", help="Only show what would be uploaded")
    ap.add_argument("--backfill-playlists", action="store_true",
                    help="Add already-uploaded public videos to playlists, then stop")
    args = ap.parse_args()

    if args.backfill_playlists:
        backfill_playlists(get_youtube(), args.plans_dir)
        return

    if args.plan:
        todo = [args.plan]
    else:
        todo = []
        for p in sorted(glob.glob(os.path.join(args.plans_dir, "*.json"))):
            with open(p, encoding="utf-8") as f:
                if json.load(f).get("status") == "video_ready":
                    todo.append(p)
    # Long videos go first, so the weekly long video is posted the same day
    def is_long(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("format") == "long"
    todo = sorted(todo, key=lambda p: not is_long(p))[:args.max]
    if not todo:
        sys.exit("No videos ready to upload. Run video_maker.py first.")

    if args.dry_run:
        for p in todo:
            with open(p, encoding="utf-8") as f:
                body = build_metadata(json.load(f), args.privacy, args.publish_at,
                                      ["▶ More like this: <playlist link>",
                                       "🔔 Subscribe for a new 60-second lesson every day!"])
            print(f"\nWOULD UPLOAD: {p}")
            print(json.dumps(body, ensure_ascii=False, indent=2))
        return

    yt = get_youtube()
    any_locked = False
    for p in todo:
        with open(p, encoding="utf-8") as f:
            title = json.load(f).get("title", p)
        print(f"Uploading: {title}")
        try:
            url, locked = upload_plan(yt, p, args.privacy, args.publish_at)
            any_locked |= locked
            print(f"  DONE -> {url}" + ("  (kept PRIVATE by YouTube)" if locked else "") + "\n")
        except HttpError as e:
            if e.resp.status == 403 and b"quota" in e.content.lower():
                sys.exit("  YouTube daily upload quota used up. Try again tomorrow.")
            print(f"  FAILED: {e}\n")
        except Exception as e:
            print(f"  FAILED: {e}\n")

    if any_locked:
        print("NOTE: YouTube kept these videos PRIVATE because your Google Cloud project")
        print("is not audited yet. For now: open YouTube Studio > Content and set them to Public.")
        print("For fully automatic public uploads, request an API audit from Google")
        print("(search: 'YouTube API Services audit and quota extension form').")


if __name__ == "__main__":
    main()
