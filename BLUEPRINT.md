# PROJECT BLUEPRINT: "Learn in 60 Seconds" YouTube Autopilot

> **Note for Claude:** This is my project. Please read it fully before helping.
> I am a beginner. Explain in very simple English (Hinglish is okay), and give
> me ONE small step at a time. I use Windows 11 and Command Prompt.
> If you need to change code, ask me to upload the .py file first.
> Never ask me to paste my API keys in the chat.

---

## 1. What we built (in simple words)

A system that runs **every day by itself** and:

1. **Finds** what is trending on YouTube (in the US).
2. **Writes** original, accurate video ideas and scripts with free AI.
3. **Makes** the video: AI voice + free stock clips + big subtitles + thumbnail.
4. **Uploads** the video to my YouTube channel.

```
trend_finder.py  →  idea_maker.py  →  video_maker.py  →  uploader.py
  (trends.json)      (plans/*.json)    (videos/*/video.mp4)   (YouTube)
         └──────────── all run by run_daily.py every day at 9:30 PM ────────────┘
```

---

## 2. My channel

| Item | Value |
|---|---|
| Channel name | Learn in 60 Seconds |
| Handle | @LearnIn60SecondsDaily |
| Channel ID | UCZR7ZUE_FJp3XmNhhIlOeaA |
| Type | Faceless educational **Shorts** (30–60 sec) |
| Topics allowed | Education, Howto & Style, Science & Technology, Autos & Vehicles |
| Audience | US (highest earning), English (United States) voice |
| Country of residence | India |
| Made for kids | No |
| Branding | Dark navy + yellow "60 SEC" stopwatch logo, banner, watermark |
| Phone verified | Yes (custom thumbnails work) |

---

## 3. My computer setup

- Windows 11 laptop, Python **3.14.7**
- Project folder: **C:\youtube_project**
- Laptop set to **never sleep when plugged in**

### Keys (saved with `setx`, never share them)

| Name | What it is | Where it comes from |
|---|---|---|
| `YT_API_KEY` | Reads YouTube trending data | console.cloud.google.com → APIs & Services → Credentials → API Keys |
| `GEMINI_API_KEY` | Free AI #1 (writes ideas) | aistudio.google.com/apikey |
| `GROQ_API_KEY` | Free AI #2 (backup, very fast) | console.groq.com/keys |
| `PEXELS_API_KEY` | Free stock video clips | pexels.com/api |
| `ANTHROPIC_API_KEY` | Optional paid backup (not set up) | console.anthropic.com |

Uploading uses **OAuth**, not a key:
- `client_secret.json` = OAuth "Desktop app" client from Google Cloud project **youtube-project** (Google Auth Platform → Clients). My channel Gmail is added as a Test user.
- `token.json` = saved login (made automatically on first upload). If deleted, the uploader asks me to sign in again.

Remember: after `setx`, **close and reopen** Command Prompt.

---

## 4. Files and what each one does

| File | Job |
|---|---|
| `trend_finder.py` | Scans ~500 trending US videos. Scores them (views per hour, like %, comments, views vs channel size). Ranks categories by **trend × earning potential**. Saves `trends.json`. |
| `idea_maker.py` | Uses trends to write original plans (title, hook, script sections with stock-video search words, description, tags, hashtags, thumbnail text). AI order: **Gemini → Groq → Ollama → Claude**, skipping busy ones. Auto-finds working Gemini models and remembers the last good one in `gemini_model.txt`. Keeps to the channel theme and **never repeats** old titles. **Quality checks** + **accuracy lock**: ideas with uncertain facts (stats, studies, "origins") stay as *draft* and are NOT auto-posted. |
| `video_maker.py` | For each *approved* plan: AI voice with edge-tts (en-US-AndrewNeural), one Pexels clip per section, timed 3-word subtitles, joins with FFmpeg (installed by imageio-ffmpeg), makes a 1280×720 yellow-text thumbnail. Output: `videos\<plan>\video.mp4` + `thumbnail.jpg`. Adds Pexels credits. |
| `uploader.py` | Uploads *video_ready* videos with title, description, hashtags (+#Shorts), tags, category, language, thumbnail. Retries on network errors. Logs to `upload_log.json`. Options: `--dry-run`, `--privacy`, `--publish-at`, `--max`. |
| `analytics_report.py` | **Smart report:** checks MY channel's public videos (views/day, likes, comments), finds best & weakest, shows monetization progress, saves `performance.json`. The Idea Maker uses it to make more videos like the winners. |
| `channel_health.py` | **Health check:** daily views/subs for the last 10 days, and for the 12 newest videos: public? processed? rejected? made for kids? country block? age restricted? plus views gained since the last check (`views_snapshot.json`). Runs automatically at the end of every nightly run (step 5), or by hand: `python channel_health.py`. |
| `run_daily.py` | Runs everything in order with live progress: trends → my channel report → ideas (+ 1 long video on Mon/Wed/Fri) → videos → upload. Settings at the top. Saves a log in `logs\`. |
| `run_daily.bat` | One-click launcher (used by Task Scheduler). |
| `requirements.txt` | Libraries: google-api-python-client, google-auth-oauthlib, requests, anthropic, edge-tts, imageio-ffmpeg, pillow |

### Settings at the top of `run_daily.py`
```
CHANNEL = "Learn in 60 Seconds"
REGION = "US"
VIDEOS_PER_DAY = 2
LANGUAGE = "English"
ALLOWED = "Education,Howto & Style,Science & Technology,Autos & Vehicles"
PRIVACY = "public"
LONG_VIDEO_DAYS = [0, 2, 4]   (Mon, Wed, Fri: also one 8-10 min video; [] = off)
CORE_TOPIC = "Autos & Vehicles"   (Short #1 + long videos always this topic)
EXPLORE = False                   (no test topics: Short #2 = driving again or another PROVEN winner, e.g. How-to/cast iron)
```

### Growth features built in (Oct 2026 update)
- **Viral Shorts rules:** 20–40 sec, scroll-stopping hook in first 2 sec, one comment question, loop ending.
- **Big yellow headline** at the top of every Short (works as the thumbnail, because Shorts ignore custom thumbnails).
- **New stock clip every ~5 sec** (Shorts) / ~10 sec (long videos). Faster voice (+12%).
- **Learns from my channel** via `performance.json`.
- **3 long videos per week** (Mon, Wed, Fri) for watch hours + "Full Guides" playlist.
- **Auto playlists** by topic: Driving & Car Tips in 60 Seconds, Science & Tech Explained Fast, Smart How-To Hacks, Learn Something New Every Day (cached in `playlists.json`).
- **Variety:** 7 rotating video styles (Did-you-know, Myth vs Fact, 3 mistakes, How-to, Quiz, Explained simply, What happens if) and a different topic area each day (`--rotate`).
- **Second AI fact-check** before any idea is auto-approved; fails stay as drafts.
- **Smarter clip matching:** picks the Pexels clip whose title best matches the search words.
- **Real search topics:** uses YouTube search autocomplete (free, unofficial endpoint, skipped if it fails) so videos answer what people actually search, which brings views for months.
- **Series:** about every 3rd day, one Short is "Part 1" with a cliffhanger; the next run makes "Part 2" automatically (only if Part 1 passed checks). Series get their own playlist "<name> (Series)".
- **Watch-time system:** long videos get automatic **chapters** (from section names) and a watch-time script structure (hook, curiosity lines every 60–90 s, subscribe line, recap). Every description gets "More like this" playlist link, latest long video link and a subscribe line. Shorts end with an on-screen card "FULL GUIDES ON MY CHANNEL" (or "FOLLOW FOR A NEW LESSON DAILY").
- **Retention report:** `analytics_report.py` reads YouTube Analytics (% watched, where viewers leave, subscribers gained per video, long-video watch hours) and turns it into tips the Idea Maker follows. Needs **YouTube Analytics API** enabled in Google Cloud + the extra "yt-analytics.readonly" permission (sign in again once).
- **Anti-swipe fixes (30 Sept 2026)**, because analytics showed 62% swiped away: hooks max 8 words with curiosity in the first 3 words (banned: "Ever wonder", "Did you know", "Have you ever"); slow zoom-in on the opening clip; new clip every 2 sec during the hook; yellow headline appears after 1 sec so the hook is seen first.
- **Long-video retry:** if the fact-checker blocks the long video idea, the Idea Maker asks for a new, safer idea (up to 3 tries). The extra upload slot on long days is used only when a long video is really ready.
- **Long-script expander:** free AI models write only ~400 words for long videos, so if a long script is under 900 words, the Idea Maker expands it section by section (~150–200 words each, ~1,300 total) before the checks. Also cleans up oddly formatted AI replies (`normalize_plan`).
- **Follow the data (1 Oct 2026):** Short #1 every day (and every long video) uses my best topic from `performance.json` (currently Autos & Vehicles: 406 views/day vs Education 9.9); Short #2 tests the other topics in rotation, so new winners can be found. Falls back to normal rotation if no data.
- **No experiments (3 Oct, my decision):** `EXPLORE = False` → both Shorts only use proven topics (driving + any topic with 2+ videos and 30%+ of the best views/day). Weak topics (Education, phone/Science) are skipped. Set `EXPLORE = True` to test new topics again.
- **Core topic (3 Oct):** `CORE_TOPIC = "Autos & Vehicles"` in run_daily.py → Short #1 and every long video are ALWAYS driving/cars. Short #2 follows the data. The AI now labels each video by its real content (`category` field), and the channel report re-labels old driving videos by title words (some were wrongly labelled Science & Tech because they were made in that slot).
- **Smarter test slot (2 Oct):** topics with 2+ videos and under 10% of the best topic's views/day are skipped (Education currently); other proven winners (30%+ of the best) get 2 turns for every 1 test turn. `analytics_report.py` now also saves `category_video_counts`.
- **Subscriber boosters:** Shorts say a short "Like if this helped, follow for daily <topic>" line; topic-matched end card (e.g. "FOLLOW FOR DAILY DRIVING TIPS"); one-click subscribe link in every description (`?sub_confirmation=1`); series every 2nd day.
- **`social_caption.txt`** in each video folder, for posting the same video to Instagram Reels / Facebook via Meta Business Suite (manual, free).

### Plan status flow (inside each `plans\*.json`)
```
draft  →  approved  →  video_ready  →  uploaded
(needs my check)  (auto if safe)  (video made)  (on YouTube)
```
To approve a draft by hand: open it in Notepad, change `"status": "draft"` to `"status": "approved"`.

### Other files/folders created
`trends.json`, `plans\`, `videos\` (+ `_clip_cache`), `logs\`, `upload_log.json`, `gemini_model.txt`, `token.json`

---

## 5. Daily automation

- Windows Task Scheduler task: **"YouTube Daily"**, runs `run_daily.bat` every day at **21:30 India time** (about 12 PM New York).
- Laptop must be ON, plugged in, and online at that time.
- Takes about 10–15 minutes (each video ≈ 3–4 minutes to make).
- Uploads max 2 per day, oldest ready video first.

---

## 6. Command cheat sheet

```
cd C:\youtube_project
python run_daily.py                          (run everything now)
python trend_finder.py --region US           (trends only)
python idea_maker.py --allowed "Education,Howto & Style" --channel "Learn in 60 Seconds" --format short --count 2
python video_maker.py                        (make all approved plans)
python video_maker.py --plan plans\plan_xxx.json
python uploader.py --dry-run                 (preview, no upload)
python uploader.py --plan plans\plan_xxx.json
python uploader.py --backfill-playlists      (put old videos into playlists)
python analytics_report.py                   (my channel report + monetization progress)
pip install -r requirements.txt              (after updating files)

schtasks /change /tn "YouTube Daily" /disable    (pause autopilot)
schtasks /change /tn "YouTube Daily" /enable     (turn back on)
schtasks /run /tn "YouTube Daily"                (run the task now)
```

---

## 7. Safety rules we follow

- **Original content only:** trends are inspiration; never copy other creators' scripts or clips. Stock clips come only from Pexels (free license, credited).
- **Accuracy first:** the AI is told to avoid stats, studies, invented slang or "secret meanings". Uncertain ideas stay as drafts.
- **My 2-minute daily check:** watch new Shorts; set any wrong one to Private in YouTube Studio.
- Fully automated, low-effort mass content risks YouTube's monetization rules, so quality and accuracy matter.

---

## 8. Progress so far

- ✅ All 4 parts + daily autopilot working (first full run: 28 Sept 2026).
- ✅ Video 1 live & public: "3 Step Parallel Park Trick for Student Drivers" (youtu.be/D8x7zWrW04Q).
- ⚠️ Uncertain facts (made before the accuracy lock), still PUBLIC by my choice: youtu.be/fSHYwe2T8S8 (bikers flash lights, top Short with 226 views), youtu.be/WDpa-uB7j4g ("G" hand sign). Watch their comments.
- ✅ Also uploaded 29 Sept: "Stop Braking in the Middle of a Turn" (youtu.be/n8OkwoAbzIQ), "Why Bikers Tap Their Helmet at You" (youtu.be/EJMvlnkyDNU).
- ✅ 30 Sept: "Why the Sky Is Actually Blue", "What Happens If You Swallow Gum", "Stop ruining your cast iron pan (Part 1)" (first series). First long video (Wed 30 Sept) was blocked by the fact-checker, so retries were added.
- 📊 3 Oct report: avg watched up 43% → 64% (anti-swipe fixes work). New driving hits: "Which Way Do You Turn on Ice?" 1,153/day, "Stop Crossing Your Arms When Steering" 617/day. 6 subs, 7,382 Shorts views. Task didn't run on battery → Task Scheduler "AC power only" unticked.
- 📊 2 Oct report: series works! "Cast iron pan (Part 1)" = #1 at 1,233 views/day. Topics: How-to 619/day, Autos 354/day, Education 4/day (sky, gum flopped). Views paused (+17) after the first wave. First long video ("Heart Skips a Beat") 4 views/day.
- 📊 1 Oct report: 5 subscribers, 4,317 Shorts views, top videos all car/bike ("Helmet Tap" 761/day, "Stop Braking" 655/day). Avg watched 43%, likes 0.5–1.6%.
- 📊 First analytics (29 Sept, 28 days): 37.8% stayed to watch / 62.2% swiped away; views from Shorts feed 82.5%, YouTube search 11.8%.
- Uploads were NOT locked to private by Google, so public auto-upload works.

## 9. Known issues & tips

- Gemini free models often say **503 busy** → the script auto-switches to Groq. Normal.
- Some stock clips don't match the script perfectly.
- `setx` only works in NEW Command Prompt windows.
- Old API keys were shown in chat once; consider regenerating them.
- **30 Sept 2026: token.json and client_secret.json were uploaded to chat by mistake** → revoke app access, reset the OAuth client secret, re-download client_secret.json, delete token.json and sign in again. **Never upload these two files again.**

## 10. Ideas for next improvements

0. **IN PROGRESS (3 Oct): Cloud with GitHub Actions.** Files: `.github/workflows/daily.yml` (runs 16:00 UTC = 9:30 PM IST, plus manual "Run workflow" button, TZ=Asia/Kolkata), `.gitignore` (never commits token.json, client_secret.json, videos/). GitHub Secrets needed: TOKEN_JSON, CLIENT_SECRET_JSON, YT_API_KEY, GEMINI_API_KEY, GROQ_API_KEY, PEXELS_API_KEY. After each run, plans/logs/reports are committed back to the private repo. Videos missing in the cloud are re-made (`requeue_missing_videos`). OAuth app must be **In production** (Testing mode logins expire after ~7 days). **Disable the laptop Task Scheduler task** once the cloud works (avoid double uploads). Old plan text: One-time setup ~30–45 min: GitHub account, keys stored as GitHub "Secrets", a workflow file that runs `run_daily.py` nightly, and saving plans/state between runs. Estimated use ~1,000 min/month (check current free limits). Quick alternative meanwhile: Task Scheduler "Wake the computer to run this task" + laptop left in Sleep (not shut down) and plugged in; some HP BIOS have "auto power-on".

1. Better stock clip matching (check clip titles/tags against the script).
2. Copyright-free background music at low volume.
3. Auto-reply / pin a comment on each video (needs extra YouTube permission).
4. Record my own voice for some videos (more human = better for monetization).
5. Later: long videos, Hindi version channel, Advanced features verification, apply for YouTube Partner Program (1,000 subs + 10M Shorts views in 90 days, or 4,000 watch hours).
