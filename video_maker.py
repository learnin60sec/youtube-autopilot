"""
YouTube Video Maker  (Part 3 of the YouTube automation project)
---------------------------------------------------------------
Turns an approved plan (from idea_maker.py) into a finished video:
  - free AI voice (Microsoft Edge voices via edge-tts)
  - free stock video clips from Pexels (one per script section)
  - big, easy-to-read subtitles timed to the voice
  - a thumbnail image with the plan's thumbnail text

Everything is free. FFmpeg is installed automatically with imageio-ffmpeg.

Setup:
    pip install -r requirements.txt
    Free Pexels key: pexels.com/api  ->  setx PEXELS_API_KEY "your_key"
    (Without a Pexels key, videos use plain colour backgrounds.)

Run:
    python video_maker.py                              # all APPROVED plans
    python video_maker.py --plan plans\\plan_xxx_1.json  # one plan, even a draft
    python video_maker.py --voice en-US-JennyNeural    # choose another voice
"""

import os
import re
import sys
import glob
import json
import math
import random
import shutil
import asyncio
import argparse
import subprocess

import requests
import edge_tts
import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont, ImageOps

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

VOICES = {"english": "en-US-AndrewNeural", "hindi": "hi-IN-MadhurNeural"}
BACKUP_VOICE = {"english": "en-US-GuyNeural", "hindi": "hi-IN-SwaraNeural"}
SIZES = {"short": (1080, 1920), "long": (1920, 1080)}
BG_COLORS = ["1e1e2e", "0f3460", "3a0ca3", "14532d", "7c2d12", "1f2937"]
WORDS_PER_CAPTION = 3
CLIP_SECONDS = {"short": 5, "long": 10}    # new stock clip every N seconds
HOOK_CLIP_SECONDS = 2                       # fast cuts during the Short's hook
HEADLINE_DELAY = 1.0                        # headline appears after the hook starts
CLIP_TARGET = {"short": 1920, "long": 1280}  # download size (smaller = faster)


# ---------------------------------------------------------------- helpers
def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-1500:])
    return r


def media_duration(path):
    r = subprocess.run([FFMPEG, "-i", path], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    if not m:
        raise RuntimeError(f"Could not read duration of {path}")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


# ---------------------------------------------------------------- voice
async def _tts(text, voice, rate, out_mp3):
    try:
        comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    except TypeError:  # older edge-tts versions
        comm = edge_tts.Communicate(text, voice, rate=rate)
    words = []
    with open(out_mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append((start, start + chunk["duration"] / 1e7, chunk["text"]))
    return words


def make_voice(text, voice, backup, rate, out_mp3):
    """Create narration. Returns (duration, [(start, end, word), ...])."""
    last_error = None
    for v in (voice, backup):
        for _ in range(2):
            try:
                words = asyncio.run(_tts(text, v, rate, out_mp3))
                dur = media_duration(out_mp3)
                if not words:  # no word timings: spread words evenly
                    parts = text.split()
                    step = dur / max(len(parts), 1)
                    words = [(i * step, (i + 1) * step, w) for i, w in enumerate(parts)]
                return dur, words
            except Exception as e:  # network hiccup or bad voice name
                last_error = e
    raise RuntimeError(f"Voice creation failed: {last_error}")


# ---------------------------------------------------------------- stock video
def pexels_clip(query, orientation, used, cache_dir, credits, target=1920):
    key = os.getenv("PEXELS_API_KEY")
    if not key:
        return None
    queries = [query, " ".join(query.split()[-2:]), query.split()[0] if query else ""]
    for q in [q for q in queries if q]:
        try:
            r = requests.get("https://api.pexels.com/videos/search",
                             headers={"Authorization": key},
                             params={"query": q, "orientation": orientation,
                                     "per_page": 15}, timeout=20)
        except requests.RequestException:
            return None
        if r.status_code != 200:
            return None
        all_vids = r.json().get("videos", [])
        vids = [v for v in all_vids if v["id"] not in used] or all_vids  # reuse if needed
        if not vids:
            continue
        # Pick the clip whose Pexels title best matches the search words
        words = set(re.findall(r"[a-z]+", q.lower()))
        def match(v):
            slug = set(re.findall(r"[a-z]+", v.get("url", "").lower()))
            return len(words & slug)
        vids.sort(key=match, reverse=True)
        best = match(vids[0])
        top = [x for x in vids if match(x) == best][:3]
        v = random.choice(top)
        files = [f for f in v.get("video_files", [])
                 if f.get("file_type") == "video/mp4" and f.get("width") and f.get("height")]
        if not files:
            continue
        # closest to the target size (not huge 4K files)
        files.sort(key=lambda f: abs(max(f["width"], f["height"]) - target))
        path = os.path.join(cache_dir, f"pexels_{v['id']}.mp4")
        if not os.path.exists(path):
            try:
                with requests.get(files[0]["link"], stream=True, timeout=60) as d:
                    d.raise_for_status()
                    with open(path, "wb") as f:
                        for block in d.iter_content(1 << 20):
                            f.write(block)
            except requests.RequestException:
                continue
        if v["id"] in used:
            return path
        used.add(v["id"])
        credits.append(f"Video by {v.get('user', {}).get('name', 'Pexels')} on Pexels: {v.get('url', '')}")
        return path
    return None


def section_video(src, duration, size, out, color, zoom=False):
    w, h = size
    if src:
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
              f"crop={w}:{h},fps=30,setsar=1")
        if zoom:  # slow push-in: the first seconds feel alive, not like a still photo
            frames = max(int(duration * 30), 1)
            vf += (f",zoompan=z='1+0.18*on/{frames}':x='iw/2-(iw/zoom/2)':"
                   f"y='ih/2-(ih/zoom/2)':d=1:s={w}x{h}:fps=30")
        vf += ",format=yuv420p"
        cmd = [FFMPEG, "-y", "-stream_loop", "-1", "-i", src, "-t", f"{duration:.3f}",
               "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", out]
    else:
        cmd = [FFMPEG, "-y", "-f", "lavfi",
               "-i", f"color=c=0x{color}:s={w}x{h}:r=30:d={duration:.3f}",
               "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", out]
    run(cmd)


# ---------------------------------------------------------------- subtitles
def ass_time(t):
    t = max(t, 0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def write_subtitles(words, size, fmt, path, headline="", total=0.0, cta=""):
    w, h = size
    font_size = 96 if fmt == "short" else 68
    margin_v = int(h * 0.30) if fmt == "short" else 90
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Main,Arial,{font_size},&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,7,3,2,60,60,{margin_v},1",
        # Headline: big yellow title in a dark box at the top, on screen the whole
        # Short, so ANY frame YouTube picks looks like a thumbnail.
        f"Style: Head,Arial,{int(font_size * 1.05)},&H0000E6FF,&H0000E6FF,&HB4000000,"
        f"&H00000000,-1,0,0,0,100,100,0,0,3,22,0,8,70,70,{int(h * 0.11)},1",
        f"Style: Cta,Arial,{int(font_size * 0.8)},&H00FFFFFF,&H00FFFFFF,&HC80000CC,"
        f"&H00000000,-1,0,0,0,100,100,0,0,3,20,0,5,80,80,0,1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if headline and fmt == "short":
        head = headline.upper().replace("{", "(").replace("}", ")")
        lines.append(f"Dialogue: 1,{ass_time(HEADLINE_DELAY)},{ass_time(total + 1)},Head,,0,0,0,,{head}")
    if cta and total > 6:
        lines.append(f"Dialogue: 2,{ass_time(total - 2.8)},{ass_time(total + 1)},Cta,,0,0,0,,{cta}")
    for i in range(0, len(words), WORDS_PER_CAPTION):
        group = words[i:i + WORDS_PER_CAPTION]
        start = group[0][0]
        end = words[i + WORDS_PER_CAPTION][0] if i + WORDS_PER_CAPTION < len(words) else group[-1][1] + 0.3
        text = " ".join(g[2] for g in group).replace("{", "(").replace("}", ")").upper()
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Main,,0,0,0,,{text}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------- thumbnail
def load_font(size):
    for p in ("C:/Windows/Fonts/impact.ttf", "C:/Windows/Fonts/arialbd.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def make_thumbnail(first_clip, text, out, work):
    frame = os.path.join(work, "frame.jpg")
    try:
        run([FFMPEG, "-y", "-ss", "1", "-i", first_clip, "-frames:v", "1", frame])
        img = ImageOps.fit(Image.open(frame).convert("RGB"), (1280, 720))
    except Exception:
        img = Image.new("RGB", (1280, 720), "#1e1e2e")
    img = Image.blend(img, Image.new("RGB", img.size, "black"), 0.35)
    draw = ImageDraw.Draw(img)
    text = (text or "WATCH THIS").upper()

    size = 170
    while size > 50:
        font = load_font(size)
        lines, line = [], ""
        for word in text.split():
            test = f"{line} {word}".strip()
            if draw.textlength(test, font=font) <= 1180:
                line = test
            else:
                lines.append(line)
                line = word
        lines.append(line)
        if len(lines) <= 3 and len(lines) * size * 1.1 <= 640:
            break
        size -= 10

    y = (720 - len(lines) * size * 1.1) / 2
    for ln in lines:
        x = (1280 - draw.textlength(ln, font=font)) / 2
        draw.text((x, y), ln, font=font, fill="#FFE600",
                  stroke_width=max(size // 18, 4), stroke_fill="black")
        y += size * 1.1
    img.save(out, quality=92)


def has_long_video(plans_dir):
    for p in glob.glob(os.path.join(plans_dir or ".", "*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                pl = json.load(f)
            if pl.get("format") == "long" and pl.get("status") == "uploaded":
                return True
        except (OSError, ValueError):
            continue
    return False


# ---------------------------------------------------------------- main build
def build_video(plan_path, voice_override=None, keep_work=False):
    with open(plan_path, encoding="utf-8") as f:
        plan = json.load(f)
    fmt = plan.get("format", "short")
    size = SIZES[fmt]
    lang = plan.get("language", "English").lower()
    voice = voice_override or VOICES.get(lang, VOICES["english"])
    backup = BACKUP_VOICE.get(lang, BACKUP_VOICE["english"])
    rate = "+12%" if fmt == "short" else "+0%"  # energetic pace keeps viewers watching

    name = os.path.splitext(os.path.basename(plan_path))[0]
    out_dir = os.path.join("videos", name)
    work = os.path.join(out_dir, "work")
    cache = os.path.join("videos", "_clip_cache")
    for d in (work, cache):
        os.makedirs(d, exist_ok=True)

    sections = [s for s in plan.get("script", []) if s.get("narration", "").strip()]
    if not sections:
        raise RuntimeError("Plan has no script sections.")

    orientation = "portrait" if fmt == "short" else "landscape"
    used, credits, all_words = set(), [], []
    video_list, audio_list, offset = [], [], 0.0

    chapters = []
    for i, sec in enumerate(sections):
        chapters.append({"t": round(offset), "title": (sec.get("section") or f"Part {i + 1}").strip()})
        print(f"  Section {i + 1}/{len(sections)}: voice...", end="", flush=True)
        mp3 = os.path.join(work, f"voice_{i}.mp3")
        dur, words = make_voice(sec["narration"], voice, backup, rate, mp3)
        all_words += [(s + offset, e + offset, w) for s, e, w in words]
        offset += dur

        print(" clips...", end="", flush=True)
        every = HOOK_CLIP_SECONDS if (fmt == "short" and i == 0) else CLIP_SECONDS[fmt]
        pieces = max(1, math.ceil(dur / every))
        got_clip = False
        for j in range(pieces):
            clip = pexels_clip(sec.get("visual_search", ""), orientation, used, cache,
                               credits, CLIP_TARGET[fmt])
            got_clip |= bool(clip)
            mp4 = os.path.join(work, f"sec_{i}_{j}.mp4")
            section_video(clip, dur / pieces, size, mp4, BG_COLORS[i % len(BG_COLORS)],
                          zoom=(fmt == "short" and i == 0))
            video_list.append(f"file 'sec_{i}_{j}.mp4'")
        print(f" done ({pieces} clip{'s' if pieces > 1 else ''})"
              + ("" if got_clip else " (no stock clip, colour background)"))

        audio_list.append(f"file 'voice_{i}.mp3'")

    with open(os.path.join(work, "videos.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(video_list) + "\n")
    with open(os.path.join(work, "audio.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(audio_list) + "\n")
    cta = ""
    if fmt == "short":  # end card that matches the topic: people subscribe for MORE of the same
        cta = {"Autos & Vehicles": "FOLLOW FOR DAILY DRIVING TIPS",
               "Science & Technology": "FOLLOW FOR DAILY SCIENCE FACTS",
               "Howto & Style": "FOLLOW FOR DAILY LIFE HACKS"}.get(
                   plan.get("category"), "FOLLOW FOR A NEW LESSON DAILY")
    write_subtitles(all_words, size, fmt, os.path.join(work, "subs.ass"),
                    plan.get("thumbnail_text", ""), offset, cta)

    print("  Joining everything together...")
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", "videos.txt",
         "-c", "copy", "video_raw.mp4"], cwd=work)
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", "audio.txt",
         "-c:a", "aac", "-b:a", "192k", "voice.m4a"], cwd=work)

    preset = "medium" if fmt == "short" else "fast"
    final_args = ["-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", preset,
                  "-crf", "20", "-c:a", "aac", "-b:a", "192k", "-shortest",
                  "-movflags", "+faststart", "final.mp4"]
    try:
        run([FFMPEG, "-y", "-i", "video_raw.mp4", "-i", "voice.m4a",
             "-vf", "subtitles=subs.ass"] + final_args, cwd=work)
    except RuntimeError:
        print("  Subtitles could not be added, making the video without them.")
        run([FFMPEG, "-y", "-i", "video_raw.mp4", "-i", "voice.m4a"] + final_args, cwd=work)

    video_out = os.path.join(out_dir, "video.mp4")
    thumb_out = os.path.join(out_dir, "thumbnail.jpg")
    shutil.move(os.path.join(work, "final.mp4"), video_out)
    make_thumbnail(os.path.join(work, "sec_0_0.mp4"), plan.get("thumbnail_text"), thumb_out, work)
    if not keep_work:
        shutil.rmtree(work, ignore_errors=True)

    tags = " ".join(h if h.startswith("#") else f"#{h}" for h in plan.get("hashtags", []))
    caption = (f"{plan.get('title', '')}\n\n{plan.get('hook', '')}\n\n"
               f"Follow for a new 60-second lesson every day! 🧠⚡\n"
               f"Full channel on YouTube: Learn in 60 Seconds\n\n{tags} #learn #facts #didyouknow")
    with open(os.path.join(out_dir, "social_caption.txt"), "w", encoding="utf-8") as f:
        f.write(caption)

    plan.update({"status": "video_ready",
                 "video_file": os.path.abspath(video_out),
                 "thumbnail_file": os.path.abspath(thumb_out),
                 "duration_sec": round(offset, 1),
                 "chapters": chapters if fmt == "long" else [],
                 "credits": credits})
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    return video_out, thumb_out, offset


def main():
    ap = argparse.ArgumentParser(description="Turn approved plans into videos")
    ap.add_argument("--plan", help="Make a video from this one plan file (even a draft)")
    ap.add_argument("--plans-dir", default="plans")
    ap.add_argument("--voice", help="edge-tts voice name, e.g. en-US-JennyNeural")
    ap.add_argument("--keep-work", action="store_true", help="Keep temporary files")
    args = ap.parse_args()

    if args.plan:
        todo = [args.plan]
    else:
        todo = []
        for p in sorted(glob.glob(os.path.join(args.plans_dir, "*.json"))):
            with open(p, encoding="utf-8") as f:
                if json.load(f).get("status") == "approved":
                    todo.append(p)
    if not todo:
        sys.exit("No approved plans found. Approve a plan, run idea_maker.py with "
                 "--auto-approve, or use --plan plans\\plan_xxx.json")

    if not os.getenv("PEXELS_API_KEY"):
        print("Note: no PEXELS_API_KEY set, videos will use colour backgrounds.\n")

    for p in todo:
        with open(p, encoding="utf-8") as f:
            title = json.load(f).get("title", p)
        print(f"Making video: {title}")
        try:
            video, thumb, dur = build_video(p, args.voice, args.keep_work)
            print(f"  DONE ({dur:.0f} sec) -> {video}\n  Thumbnail -> {thumb}\n")
        except Exception as e:
            print(f"  FAILED: {e}\n")


if __name__ == "__main__":
    main()
