"""
Daily Autopilot for "Learn in 60 Seconds"
------------------------------------------
Runs all 4 parts in order:
  1. trend_finder.py      -> what is trending today
     analytics_report.py  -> what works on MY channel (feeds the ideas)
  2. idea_maker.py        -> original, on-theme ideas (auto-approved if they pass checks)
                             + one long video on each LONG_VIDEO_DAYS day
  3. video_maker.py   -> voice + stock clips + subtitles + thumbnail
  4. uploader.py      -> posts to your channel

Run by hand:            python run_daily.py
Run every day by itself: see run_daily.bat + Windows Task Scheduler.
A log of every run is saved in the logs folder.
"""

import os
import sys
import subprocess
from datetime import datetime

# ------------------------- SETTINGS (change these if you like) -------------------------
CHANNEL = "Learn in 60 Seconds"
REGION = "US"                         # audience country for trends
VIDEOS_PER_DAY = 2                    # 1-3 is best for a new channel
LANGUAGE = "English"
ALLOWED = "Education,Howto & Style,Science & Technology,Autos & Vehicles"
CORE_TOPIC = "Autos & Vehicles"       # my main topic: Short #1 + long videos are always this
EXPLORE = False                       # False = no test topics, only proven winners
PRIVACY = "public"                    # public / unlisted / private
LONG_VIDEO_DAYS = [0, 2, 4]           # 0=Mon 1=Tue 2=Wed 3=Thu 4=Fri 5=Sat 6=Sun. [] = off
# ---------------------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
os.makedirs("logs", exist_ok=True)
LOG = os.path.join("logs", f"daily_{datetime.now():%Y%m%d_%H%M}.log")


def log(text):
    line = f"[{datetime.now():%H:%M:%S}] {text}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def step(name, args):
    log(f"=== {name} ===")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env["PYTHONUNBUFFERED"] = "1"  # show progress live, line by line
    p = subprocess.Popen([sys.executable] + args, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                         errors="replace", env=env)
    for line in p.stdout:
        line = line.rstrip()
        if line:
            log("  " + line)
    ok = p.wait() == 0
    log(f"{name}: {'OK' if ok else 'FAILED'}")
    return ok


def requeue_missing_videos():
    """In the cloud, video files from earlier runs are not kept. If a plan says
    'video_ready' but its file is gone, make that video again."""
    import glob, json
    for p in glob.glob(os.path.join("plans", "*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                plan = json.load(f)
        except (OSError, ValueError):
            continue
        if plan.get("status") == "video_ready" and not os.path.exists(plan.get("video_file") or ""):
            plan["status"] = "approved"
            with open(p, "w", encoding="utf-8") as f:
                json.dump(plan, f, ensure_ascii=False, indent=2)
            log(f"  Will re-make missing video: {plan.get('title')}")


def long_video_ready():
    """True only if a finished long video is waiting to be uploaded."""
    import glob, json
    for p in glob.glob(os.path.join("plans", "*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                plan = json.load(f)
        except (OSError, ValueError):
            continue
        if plan.get("format") == "long" and plan.get("status") == "video_ready":
            return True
    return False


def main():
    log(f"Daily run started for '{CHANNEL}'")

    if not step("1. Trends", ["trend_finder.py", "--region", REGION]):
        if os.path.exists("trends.json"):
            log("Using yesterday's trends.json instead.")
        else:
            log("No trend data at all, stopping.")
            return

    step("1b. My channel report", ["analytics_report.py"])

    step("2. Ideas", ["idea_maker.py", "--allowed", ALLOWED, "--channel", CHANNEL, "--rotate",
                      "--core", CORE_TOPIC] + ([] if EXPLORE else ["--no-explore"]) + [
                      "--format", "short", "--count", str(VIDEOS_PER_DAY),
                      "--language", LANGUAGE, "--auto-approve"])

    long_day = datetime.now().weekday() in LONG_VIDEO_DAYS
    if long_day:
        step("2b. Weekly long video idea", [
            "idea_maker.py", "--allowed", ALLOWED, "--channel", CHANNEL, "--core", CORE_TOPIC,
            "--format", "long", "--count", "1", "--language", LANGUAGE, "--auto-approve"])

    requeue_missing_videos()

    # Even if ideas failed today, older approved plans can still be made and posted
    step("3. Videos", ["video_maker.py"])
    uploads = VIDEOS_PER_DAY + (1 if long_video_ready() else 0)
    step("4. Upload", ["uploader.py", "--max", str(uploads), "--privacy", PRIVACY])

    step("5. Health check", ["channel_health.py"])

    log(f"Daily run finished. Log saved: {LOG}")


if __name__ == "__main__":
    main()
