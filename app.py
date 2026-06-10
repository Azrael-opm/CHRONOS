"""
CHRONOS // Temporal Video Optimization Engine v4.0
Unified backend for TikTok & WhatsApp compression.

Features:
- TikTok: H.264/HEVC/VP9/AV1, CRF/VBR, two-pass, hardware accel, batch queue.
- WhatsApp: Pre-compression engine (Pure Status HD philosophy) — 720p/1080p 9:16,
  auto-split into 30-second segments for Status, target-size rate control so
  WhatsApp's downstream encoder has nothing left to brutalize.
- Optional WhatsApp Web bridge (Node.js) for auto-send.
- Time-themed conservative estimation, psutil process control, thumbnail preview.
"""

import os
import re
import json
import uuid
import shutil
import subprocess
import threading
import time
import signal
import math
import sys
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.exceptions import RequestEntityTooLarge

# ── Optional psutil for robust process tree control ──
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 800 * 1024 * 1024
BASE_DIR = Path(__file__).parent.resolve()
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
TEMP_DIR = BASE_DIR / "temp"
for d in (UPLOAD_DIR, OUTPUT_DIR, TEMP_DIR):
    d.mkdir(exist_ok=True)

# ── FFmpeg / ffprobe discovery ──
COMMON_FFMPEG_DIRS = [
    Path(r"C:\ffmpeg\bin"),
    Path(r"C:\Program Files\ffmpeg\bin"),
    Path(r"C:\Program Files (x86)\ffmpeg\bin"),
]

# If running as a PyInstaller bundle, also check the exe directory and bundle temp dir
if getattr(sys, "frozen", False):
    _exe_dir = Path(sys.executable).parent.resolve()
    _bundle_dir = Path(sys._MEIPASS).resolve() if hasattr(sys, "_MEIPASS") else _exe_dir
    COMMON_FFMPEG_DIRS.insert(0, _exe_dir)
    COMMON_FFMPEG_DIRS.insert(0, _bundle_dir)


def find_executable(names):
    for name in names:
        path = shutil.which(name)
        if path:
            return path
        p = Path(name)
        if p.exists():
            return str(p)
    return None


FFMPEG_CMD = os.environ.get("FFMPEG_PATH") or find_executable(
    ["ffmpeg"] + [str(d / "ffmpeg.exe") for d in COMMON_FFMPEG_DIRS]
)
FFPROBE_CMD = os.environ.get("FFPROBE_PATH") or find_executable(
    ["ffprobe"] + [str(d / "ffprobe.exe") for d in COMMON_FFMPEG_DIRS]
)

if not FFMPEG_CMD or not FFPROBE_CMD:
    print("WARNING: ffmpeg or ffprobe not found. Set PATH or use C:\\ffmpeg\\bin.")

# Hardware encoder status
HW_STATUS = {
    "nvenc": {"state": "not_detected", "reason": ""},
    "qsv": {"state": "not_detected", "reason": ""},
    "amf": {"state": "not_detected", "reason": ""}
}


def _test_hw_encoder(encoder: str) -> tuple:
    if not FFMPEG_CMD:
        return False, "FFmpeg not found"
    try:
        cmd = [
            FFMPEG_CMD, "-f", "lavfi", "-i",
            "testsrc=duration=0.1:size=32x32:rate=1",
            "-c:v", encoder, "-f", "null", "-"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            return True, ""
        else:
            err = (result.stderr or result.stdout or "").strip()
            print(f"[CHRONOS] HW TEST FAIL [{encoder}]:\n{err}")
            return False, err
    except Exception as e:
        return False, str(e)


def detect_hw_encoders():
    global HW_STATUS
    if not FFMPEG_CMD:
        return
    try:
        result = subprocess.run([FFMPEG_CMD, "-encoders"], capture_output=True, text=True, timeout=15)
        out = result.stdout
        for enc, ffmpeg_enc in [("nvenc", "h264_nvenc"), ("qsv", "h264_qsv"), ("amf", "h264_amf")]:
            present = ffmpeg_enc in out
            if not present:
                HW_STATUS[enc] = {"state": "not_detected", "reason": "Encoder not found in FFmpeg build"}
            else:
                working, reason = _test_hw_encoder(ffmpeg_enc)
                if working:
                    HW_STATUS[enc] = {"state": "working", "reason": ""}
                else:
                    HW_STATUS[enc] = {"state": "detected_not_working", "reason": reason}
        print(f"[CHRONOS] HW detection results: {HW_STATUS}")
    except Exception as e:
        print(f"[CHRONOS] HW detection failed: {e}")


detect_hw_encoders()

# In-memory job store
jobs = {}


# ── Process Control Helpers ──

def _suspend_tree(pid: int) -> bool:
    if HAS_PSUTIL:
        try:
            parent = psutil.Process(pid)
            for child in parent.children(recursive=True):
                child.suspend()
            parent.suspend()
            return True
        except Exception as e:
            print(f"[CHRONOS] psutil suspend failed: {e}")
    return False


def _resume_tree(pid: int) -> bool:
    if HAS_PSUTIL:
        try:
            parent = psutil.Process(pid)
            for child in parent.children(recursive=True):
                child.resume()
            parent.resume()
            return True
        except Exception as e:
            print(f"[CHRONOS] psutil resume failed: {e}")
    return False


def _kill_tree(pid: int) -> bool:
    if HAS_PSUTIL:
        try:
            parent = psutil.Process(pid)
            for child in parent.children(recursive=True):
                child.terminate()
            parent.terminate()
            gone, alive = psutil.wait_procs([parent] + parent.children(recursive=True), timeout=5)
            for p in alive:
                p.kill()
            return True
        except Exception as e:
            print(f"[CHRONOS] psutil kill failed: {e}")
    return False


def suspend_process(pid: int) -> bool:
    ok = _suspend_tree(pid)
    if ok:
        return True
    if os.name != 'nt':
        try:
            os.kill(pid, signal.SIGSTOP)
            return True
        except Exception:
            pass
    return False


def resume_process(pid: int) -> bool:
    ok = _resume_tree(pid)
    if ok:
        return True
    if os.name != 'nt':
        try:
            os.kill(pid, signal.SIGCONT)
            return True
        except Exception:
            pass
    return False


def kill_process(pid: int) -> bool:
    ok = _kill_tree(pid)
    if ok:
        return True
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        pass
    return False


# ── Helpers ──

def run_ffprobe(filepath: str) -> dict:
    if not FFPROBE_CMD:
        return {"error": "ffprobe not found. Install FFmpeg and add to PATH."}
    cmd = [
        FFPROBE_CMD,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,codec_name,duration,bit_rate,nb_frames,pix_fmt",
        "-show_entries", "format=size,bit_rate,duration,format_name",
        "-of", "json",
        filepath,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return {"error": f"ffprobe executable not found: {FFPROBE_CMD}"}
    if result.returncode != 0:
        return {"error": result.stderr or "ffprobe failed."}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": "ffprobe returned invalid JSON."}


def has_audio(filepath: str) -> bool:
    if not FFPROBE_CMD:
        return False
    cmd = [
        FFPROBE_CMD, "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=codec_type", "-of", "csv=p=0",
        filepath,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        return "audio" in result.stdout.lower()
    except Exception:
        return False


def parse_duration(info: dict) -> float:
    for key in ("format", "streams"):
        try:
            d = info[key].get("duration") if key == "format" else info[key][0].get("duration")
            if d:
                dur = float(d)
                if dur > 0:
                    return dur
        except Exception:
            pass
    return 0.0


def parse_fps(info: dict) -> float:
    try:
        num, den = info["streams"][0]["r_frame_rate"].split("/")
        return round(float(num) / float(den), 2)
    except Exception:
        return 0.0


def get_container_ext(container: str) -> str:
    return {"mp4": ".mp4", "mov": ".mov", "webm": ".webm", "avi": ".avi"}.get(container, ".mp4")


def get_video_codec_lib(codec: str) -> str:
    return {"h264": "libx264", "hevc": "libx265", "vp9": "libvpx-vp9", "vp8": "libvpx", "av1": "libsvtav1"}.get(codec, "libx264")


def get_video_codec(codec_choice: str, hw_accel: str) -> str:
    if hw_accel == "nvenc":
        return {"h264": "h264_nvenc", "hevc": "hevc_nvenc"}.get(codec_choice, get_video_codec_lib(codec_choice))
    if hw_accel == "qsv":
        return {"h264": "h264_qsv", "hevc": "hevc_qsv"}.get(codec_choice, get_video_codec_lib(codec_choice))
    if hw_accel == "amf":
        return {"h264": "h264_amf", "hevc": "hevc_amf"}.get(codec_choice, get_video_codec_lib(codec_choice))
    return get_video_codec_lib(codec_choice)


def get_audio_settings(container: str, mode: str, bitrate: int):
    if container == "webm":
        return {"codec": "libopus" if mode == "lossy" else "flac", "bitrate": f"{bitrate}k" if mode == "lossy" else None, "ar": "48000"}
    elif container == "avi":
        if mode == "lossy":
            return {"codec": "libmp3lame", "bitrate": f"{bitrate}k", "ar": "44100"}
        else:
            return {"codec": "pcm_s16le", "bitrate": None, "ar": "44100"}
    return {"codec": "aac" if mode == "lossy" else "alac", "bitrate": f"{bitrate}k" if mode == "lossy" else None, "ar": "44100"}


def build_vf(resolution: str, aspect_mode: str, target_fps: int, scale_filter: str = "bicubic") -> str:
    tiktok = {"1080p": (1080, 1920), "720p": (720, 1280), "480p": (480, 854)}
    std = {"1080p": (1920, 1080), "720p": (1280, 720), "480p": (854, 480)}
    ttw, tth = tiktok[resolution]
    sw, sh = std[resolution]
    sf = scale_filter or "bicubic"
    filters = []
    if aspect_mode == "tiktok":
        filters.append(f"scale={ttw}:{tth}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags={sf}")
        filters.append(f"pad={ttw}:{tth}:(ow-iw)/2:(oh-ih)/2:black")
    else:
        filters.append(f"scale={sw}:{sh}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags={sf}")
    filters.append(f"fps={target_fps}")
    filters.append("format=yuv420p")
    return ",".join(filters)


def build_summary(info: dict, filename: str = None, audio_present: bool = False) -> dict:
    duration = parse_duration(info)
    fps = parse_fps(info)
    size_bytes = w = h = 0
    bit_rate = None
    format_name = "unknown"
    nb_frames = 0
    pix_fmt = "unknown"
    try:
        size_bytes = int(info["format"]["size"])
    except Exception:
        pass
    try:
        w = int(info["streams"][0]["width"])
        h = int(info["streams"][0]["height"])
    except Exception:
        pass
    try:
        bit_rate = int(info["streams"][0]["bit_rate"])
    except Exception:
        try:
            bit_rate = int(info["format"]["bit_rate"])
        except Exception:
            pass
    try:
        format_name = info["format"].get("format_name", "unknown")
    except Exception:
        pass
    try:
        nb_frames = int(info["streams"][0].get("nb_frames", 0))
    except Exception:
        pass
    try:
        pix_fmt = info["streams"][0].get("pix_fmt", "unknown")
    except Exception:
        pass
    return {
        "filename": filename or "unknown",
        "size_bytes": size_bytes,
        "width": w,
        "height": h,
        "fps": fps,
        "duration": duration,
        "video_codec": (info.get("streams") or [{}])[0].get("codec_name", "unknown"),
        "bit_rate": bit_rate,
        "format_name": format_name,
        "nb_frames": nb_frames,
        "pix_fmt": pix_fmt,
        "has_audio": audio_present,
    }


# ── Time Estimation ──
ENCODE_FPS_TABLE = {
    "h264": {
        "480p": {"medium": 55, "slow": 30, "veryslow": 12},
        "720p": {"medium": 35, "slow": 18, "veryslow": 8},
        "1080p": {"medium": 20, "slow": 10, "veryslow": 4},
    },
    "hevc": {
        "480p": {"medium": 28, "slow": 15, "veryslow": 6},
        "720p": {"medium": 18, "slow": 9, "veryslow": 4},
        "1080p": {"medium": 10, "slow": 5, "veryslow": 2},
    },
    "vp9": {
        "480p": {"medium": 12, "slow": 6, "veryslow": 2.5},
        "720p": {"medium": 8, "slow": 4, "veryslow": 1.5},
        "1080p": {"medium": 5, "slow": 2.5, "veryslow": 1},
    },
    "av1": {
        "480p": {"medium": 8, "slow": 4, "veryslow": 1.5},
        "720p": {"medium": 5, "slow": 2.5, "veryslow": 1},
        "1080p": {"medium": 3, "slow": 1.5, "veryslow": 0.6},
    },
}


def estimate_time(summary: dict, settings: dict) -> dict:
    duration = summary.get("duration", 0)
    source_fps = summary.get("fps", 30) or 30
    if not duration:
        return {"seconds": 0, "label": "Unknown"}

    res = settings.get("resolution", "1080p")
    preset = settings.get("preset", "slow")
    codec = settings.get("codec", "h264")
    hw = settings.get("hw_accel", "none")
    two_pass = settings.get("two_pass", False)

    codec_table = ENCODE_FPS_TABLE.get(codec, ENCODE_FPS_TABLE["h264"])
    res_table = codec_table.get(res, codec_table["1080p"])
    encode_fps = res_table.get(preset, res_table["slow"])

    total_frames = duration * source_fps
    base_seconds = total_frames / encode_fps

    source_w = summary.get("width", 0)
    source_h = summary.get("height", 0)
    source_pixels = source_w * source_h
    if source_pixels > 2073600:
        base_seconds *= 1.4

    if settings.get("hevc_intermediate"):
        hevc_table = ENCODE_FPS_TABLE["hevc"]
        hevc_res = hevc_table.get(res, hevc_table["1080p"])
        hevc_fps = hevc_res.get("slow", 2.5)
        if source_pixels > 2073600:
            hevc_fps *= 1.4
        base_seconds += total_frames / hevc_fps

    if settings.get("strategy") == "vbr":
        base_seconds *= 1.1

    if two_pass:
        base_seconds *= 1.8

    if hw == "nvenc":
        base_seconds *= 0.15
    elif hw == "qsv":
        base_seconds *= 0.25
    elif hw == "amf":
        base_seconds *= 0.20

    # WhatsApp segment overhead: segments = ceil(duration / 30)
    if settings.get("platform") == "whatsapp" and settings.get("wa_mode") == "status":
        segs = math.ceil(duration / 30)
        if segs > 1:
            base_seconds *= (1 + (segs - 1) * 0.15)

    base_seconds *= 1.5
    seconds = max(5, int(base_seconds))

    if seconds > 3600:
        label = f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    elif seconds > 60:
        label = f"{seconds // 60}m {seconds % 60}s"
    else:
        label = f"{seconds}s"
    return {"seconds": seconds, "label": label}


def get_faster_alternatives(summary: dict, settings: dict) -> list:
    alts = []
    presets = ["veryslow", "slow", "medium"]
    cp = settings.get("preset", "slow")
    if cp in presets:
        idx = presets.index(cp)
        if idx > 0:
            alt = {**settings, "preset": presets[idx - 1]}
            et = estimate_time(summary, alt)
            alts.append({**alt, "reason": f"Faster preset: {alt['preset'].upper()}", "time_label": et["label"], "time_secs": et["seconds"]})

    ress = ["1080p", "720p", "480p"]
    cr = settings.get("resolution", "1080p")
    if cr in ress:
        idx = ress.index(cr)
        if idx < len(ress) - 1:
            alt = {**settings, "resolution": ress[idx + 1]}
            et = estimate_time(summary, alt)
            alts.append({**alt, "reason": f"Lower resolution: {alt['resolution'].upper()}", "time_label": et["label"], "time_secs": et["seconds"]})

    if settings.get("hevc_intermediate"):
        alt = {**settings, "hevc_intermediate": False}
        et = estimate_time(summary, alt)
        alts.append({**alt, "reason": "Single-pass (no HEVC intermediate)", "time_label": et["label"], "time_secs": et["seconds"]})

    if settings.get("codec") in ("vp9", "hevc", "av1"):
        alt = {**settings, "codec": "h264"}
        et = estimate_time(summary, alt)
        alts.append({**alt, "reason": "Switch codec to H.264", "time_label": et["label"], "time_secs": et["seconds"]})

    if settings.get("hw_accel") in ("none", None, ""):
        for hw in ["nvenc", "qsv", "amf"]:
            if HW_STATUS.get(hw, {}).get("state") == "working":
                alt = {**settings, "hw_accel": hw}
                et = estimate_time(summary, alt)
                alts.append({**alt, "reason": f"Hardware encode ({hw.upper()})", "time_label": et["label"], "time_secs": et["seconds"]})
                break

    seen = set()
    unique = []
    for a in alts:
        key = (a.get("preset"), a.get("resolution"), a.get("hevc_intermediate"), a.get("codec"), a.get("hw_accel"))
        if key not in seen:
            seen.add(key)
            unique.append(a)
    unique.sort(key=lambda x: x["time_secs"])
    return unique[:3]


# ── Smart Recommendation Engine ──

def smart_recommend(summary: dict, platform: str = "tiktok") -> dict:
    w = summary.get("width", 0)
    h = summary.get("height", 0)
    codec = summary.get("video_codec", "").lower()
    size_bytes = summary.get("size_bytes", 0)
    duration = summary.get("duration", 0) or 1
    fps = summary.get("fps", 30)
    bitrate_kbps = (size_bytes * 8) / (duration * 1000) if duration else 0

    rec = {
        "resolution": "1080p",
        "fps": min(60, int(fps)) if fps > 60 else int(fps) or 30,
        "aspect_mode": "tiktok",
        "codec": "h264",
        "container": "mp4",
        "strategy": "crf",
        "crf": 18,
        "vbr_kbps": 12000,
        "scale_filter": "bicubic",
        "preset": "slow",
        "color_tags": False,
        "hevc_intermediate": False,
        "audio_mode": "lossy",
        "audio_bitrate": 192,
        "reasons": [],
        "preset_name": "CHRONOS Auto",
        "hw_accel": "none",
        "two_pass": False,
        "platform": platform,
        "wa_mode": "status",
    }

    if platform == "whatsapp":
        # Pure Status HD philosophy: pre-compress to WhatsApp's ingestion limit
        # so WA's downstream encoder has nothing to brutalize.
        rec["aspect_mode"] = "tiktok"
        rec["container"] = "mp4"
        rec["codec"] = "h264"
        rec["color_tags"] = True
        rec["strategy"] = "vbr"
        rec["preset"] = "medium"
        rec["scale_filter"] = "bicubic"
        rec["hevc_intermediate"] = False
        rec["audio_mode"] = "lossy"
        rec["audio_bitrate"] = 128
        rec["fps"] = 30
        rec["wa_mode"] = "status"

        if h >= 1080 or w >= 1080:
            rec["resolution"] = "1080p"
            # 1080p status at 30s needs ~2.5 Mbps video to stay under ~10 MB
            rec["vbr_kbps"] = 2500
            rec["reasons"].append("WhatsApp Status HD (1080p). VBR 2.5 Mbps targets ~8-10 MB per 30-second segment — lands inside WA's ingestion sweet spot so the server does not re-compress.")
        else:
            rec["resolution"] = "720p"
            rec["vbr_kbps"] = 1500
            rec["reasons"].append("WhatsApp Status 720p. VBR 1.5 Mbps targets ~5-6 MB per 30-second segment. WA receives a file already near its internal limit, so the quality-killing second-pass is skipped.")

        rec["reasons"].append("AAC 128 kbps / 44.1 kHz stereo — maximum compatibility with WhatsApp's audio pipeline.")
        rec["reasons"].append("Auto-split enabled: clips longer than 30 seconds will be divided into 30-second status segments.")

        if HW_STATUS.get("nvenc", {}).get("state") == "working":
            rec["hw_accel"] = "nvenc"
            rec["reasons"].append("NVIDIA NVENC detected. Hardware acceleration for fast multi-segment encoding.")
        elif HW_STATUS.get("qsv", {}).get("state") == "working":
            rec["hw_accel"] = "qsv"
            rec["reasons"].append("Intel QuickSync detected. Hardware acceleration for fast multi-segment encoding.")
        elif HW_STATUS.get("amf", {}).get("state") == "working":
            rec["hw_accel"] = "amf"
            rec["reasons"].append("AMD AMF detected. Hardware acceleration for fast multi-segment encoding.")

        return rec

    # TikTok recommendations — Quality First philosophy
    # Default CRF 18 ensures visually lossless output regardless of file size.
    rec["strategy"] = "crf"
    rec["crf"] = 18
    rec["vbr_kbps"] = 12000

    if h >= 2160 or w >= 3840:
        rec["resolution"] = "1080p"
        rec["scale_filter"] = "lanczos"
        rec["preset"] = "slow"
        rec["crf"] = 18
        rec["color_tags"] = True
        rec["reasons"].append("4K/2160p source detected. Lanczos downscale to 1080p with BT.709 color tagging for optimal TikTok ingestion.")
    elif h >= 1440:
        rec["resolution"] = "1080p"
        rec["scale_filter"] = "lanczos"
        rec["reasons"].append("1440p+ source. High-quality Lanczos downscale to 1080p recommended.")
    elif h >= 1080:
        rec["resolution"] = "1080p"
        rec["reasons"].append(f"Source is {h}p. Native 1080p encode for TikTok optimal playback.")
    else:
        rec["resolution"] = "720p"
        rec["reasons"].append(f"Source below 1080p ({h}p). 720p target avoids upscaling artifacts.")

    if fps >= 90:
        rec["fps"] = 60
        rec["reasons"].append(f"High FPS source ({fps}). TikTok playback infrastructure optimized for 60 FPS max.")
    elif fps > 0:
        rec["fps"] = int(fps)

    # Quality-first: always recommend CRF 18. VBR is only for explicit size targeting.
    if bitrate_kbps > 25000:
        rec["preset"] = "slow"
        rec["reasons"].append(f"Extreme bitrate source ({bitrate_kbps:.0f} kbps). CRF 18 visually lossless ensures TikTok will pass through with minimal recompression.")
    elif bitrate_kbps > 12000:
        rec["preset"] = "slow"
        rec["reasons"].append(f"High bitrate source ({bitrate_kbps:.0f} kbps). CRF 18 is the TikTok quality sweet spot.")
    elif bitrate_kbps > 5000:
        rec["preset"] = "slow"
        rec["reasons"].append(f"Source bitrate {bitrate_kbps:.0f} kbps. CRF 18 visually lossless optimization.")
    else:
        rec["preset"] = "slow"
        rec["reasons"].append(f"Source bitrate already efficient ({bitrate_kbps:.0f} kbps). CRF preserves clarity.")

    if codec in ("hevc", "h265"):
        rec["hevc_intermediate"] = True
        rec["codec"] = "h264"
        rec["reasons"].append("H.265 source detected. Two-stage HEVC→H.264 pipeline preserves grade through filters.")
    elif codec == "vp9":
        rec["codec"] = "h264"
        rec["reasons"].append("VP9 source detected. Transcoding to H.264 for universal TikTok compatibility.")
    elif codec in ("h264", "avc"):
        rec["codec"] = "h264"
        rec["hevc_intermediate"] = False
        rec["reasons"].append("Source is H.264. Direct transcode minimizes generational quality loss.")
    else:
        rec["codec"] = "h264"
        rec["reasons"].append(f"Source codec '{codec}' non-standard. Transcoding to H.264 High Profile.")

    if h > w:
        rec["aspect_mode"] = "tiktok"
        rec["reasons"].append("Vertical video detected. 9:16 padding for full-screen TikTok display.")
    else:
        rec["aspect_mode"] = "original"
        rec["reasons"].append("Landscape/square source. Original aspect ratio preserved to prevent cropping.")

    rec["audio_mode"] = "lossy"
    rec["audio_bitrate"] = 192
    rec["reasons"].append("AAC 192 kbps recommended — universal TikTok compatibility with crisp audio.")

    rec["container"] = "mp4"

    if HW_STATUS.get("nvenc", {}).get("state") == "working":
        rec["hw_accel"] = "nvenc"
        rec["reasons"].append("NVIDIA NVENC detected. Hardware acceleration will massively reduce encode time with minimal quality trade-off.")
    elif HW_STATUS.get("qsv", {}).get("state") == "working":
        rec["hw_accel"] = "qsv"
        rec["reasons"].append("Intel QuickSync detected. Hardware acceleration available for fast encoding.")
    elif HW_STATUS.get("amf", {}).get("state") == "working":
        rec["hw_accel"] = "amf"
        rec["reasons"].append("AMD AMF detected. Hardware acceleration available for fast encoding.")

    # Two-pass only if VBR is somehow selected; with CRF default, skip it
    if rec["strategy"] == "vbr" and rec["hw_accel"] == "none" and rec["codec"] in ("h264", "hevc"):
        rec["two_pass"] = True
        rec["reasons"].append("Two-pass VBR recommended for precise bitrate targeting. First pass analyzes the entire video, second pass hits the target size accurately.")

    return rec


# ── Encode Plan Builder ──

def build_encode_plan(job_id: str, settings: dict) -> dict:
    job = jobs[job_id]
    input_path = job["input_path"]
    duration = job["summary"]["duration"]
    source_has_audio = has_audio(input_path)
    platform = settings.get("platform", "tiktok")
    wa_mode = settings.get("wa_mode", "status")

    resolution = settings.get("resolution", "1080p")
    target_fps = int(settings.get("fps", 60))
    aspect_mode = settings.get("aspect_mode", "tiktok")
    codec_choice = settings.get("codec", "h264")
    container = settings.get("container", "mp4")
    strategy = settings.get("strategy", "crf")
    crf = int(settings.get("crf", 18))
    vbr_kbps = int(settings.get("vbr_kbps", 12000))
    scale_filter = settings.get("scale_filter", "bicubic")
    hevc_intermediate = settings.get("hevc_intermediate", False)
    color_tags = settings.get("color_tags", False)
    preset_name = settings.get("preset", "slow")
    audio_mode = settings.get("audio_mode", "lossy")
    audio_bitrate = int(settings.get("audio_bitrate", 192))
    two_pass = settings.get("two_pass", False)
    hw_accel = (settings.get("hw_accel", "none") or "none").strip().lower()

    if strategy is None or strategy == "" or strategy == "null":
        strategy = "vbr" if vbr_kbps != 12000 else "crf"
    strategy = str(strategy).strip().lower()

    stem = Path(job["summary"]["filename"]).stem.replace(" ", "_")
    ext = get_container_ext(container)
    output_filename = f"{stem}_CHRONOS_{resolution}{ext}"
    output_path = str(OUTPUT_DIR / output_filename)
    job["output_path"] = output_path

    vf = build_vf(resolution, aspect_mode, target_fps, scale_filter)
    aud = get_audio_settings(container, audio_mode, audio_bitrate)

    color_args = []
    if color_tags:
        color_args = ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]

    base = [FFMPEG_CMD, "-fflags", "+genpts", "-y", "-i", input_path, "-vf", vf]

    vcodec = get_video_codec(codec_choice, hw_accel)
    is_hw = hw_accel in ("nvenc", "qsv", "amf")
    video_args = ["-c:v", vcodec, "-pix_fmt", "yuv420p"]

    if not is_hw:
        if codec_choice in ("h264", "hevc"):
            video_args += ["-preset", preset_name]
        elif codec_choice == "vp9":
            video_args += ["-deadline", "good", "-cpu-used", "4"]
        elif codec_choice == "av1":
            svt_presets = {"veryslow": "2", "slow": "4", "medium": "8"}
            video_args += ["-preset", svt_presets.get(preset_name, "8"), "-svtav1-params", "tune=0"]

    if is_hw:
        if hw_accel == "nvenc":
            nvenc_preset = {"veryslow": "slow", "slow": "slow", "medium": "medium", "fast": "fast"}.get(preset_name, "medium")
            video_args += ["-preset", nvenc_preset]
            if strategy == "vbr":
                video_args += ["-rc", "vbr", "-b:v", f"{vbr_kbps}k", "-maxrate", f"{int(vbr_kbps * 1.5)}k", "-bufsize", f"{int(vbr_kbps * 2)}k"]
            else:
                video_args += ["-rc", "vbr", "-cq", str(crf)]
                mr, bs = ("20M", "40M") if resolution == "1080p" else ("12M", "24M")
                if resolution == "480p":
                    mr, bs = "6M", "12M"
                video_args += ["-maxrate", mr, "-bufsize", bs]
        elif hw_accel == "qsv":
            if strategy == "vbr":
                video_args += ["-b:v", f"{vbr_kbps}k", "-maxrate", f"{int(vbr_kbps * 1.5)}k"]
            else:
                video_args += ["-global_quality", str(crf), "-look_ahead", "0"]
                mr, bs = ("20M", "40M") if resolution == "1080p" else ("12M", "24M")
                if resolution == "480p":
                    mr, bs = "6M", "12M"
                video_args += ["-maxrate", mr, "-bufsize", bs]
        elif hw_accel == "amf":
            amf_preset = {"veryslow": "quality", "slow": "quality", "medium": "balanced", "fast": "speed"}.get(preset_name, "balanced")
            video_args += ["-preset", amf_preset]
            if strategy == "vbr":
                video_args += ["-rc", "vbr", "-b:v", f"{vbr_kbps}k", "-maxrate", f"{int(vbr_kbps * 1.5)}k"]
            else:
                video_args += ["-rc", "cqp", "-qp_i", str(crf), "-qp_p", str(crf), "-qp_b", str(crf)]
    else:
        if strategy == "vbr":
            maxrate = f"{int(vbr_kbps * 1.5)}k"
            bufsize = f"{int(vbr_kbps * 2)}k"
            video_args += ["-b:v", f"{vbr_kbps}k", "-maxrate", maxrate, "-bufsize", bufsize]
        else:
            maxrate, bufsize = ("20M", "40M") if resolution == "1080p" else ("12M", "24M")
            if resolution == "480p":
                maxrate, bufsize = "6M", "12M"
            video_args += ["-crf", str(crf), "-maxrate", maxrate, "-bufsize", bufsize]

    output_args = []
    if container in ("mp4", "mov"):
        output_args += ["-movflags", "+faststart"]

    audio_args = []
    if source_has_audio:
        audio_args += ["-c:a", aud["codec"]]
        if aud["bitrate"]:
            audio_args += ["-b:a", aud["bitrate"]]
        audio_args += ["-ar", aud["ar"], "-ac", "2"]

    # HEVC intermediate branch (always CPU for stage 1)
    if hevc_intermediate and codec_choice == "h264":
        temp_path = str(TEMP_DIR / f"{job_id}_intermediate.mkv")
        step1 = base + [
            "-c:v", "libx265", "-crf", "16", "-preset", "slow", "-pix_fmt", "yuv420p",
        ]
        if source_has_audio:
            step1 += ["-c:a", "copy"]
        step1 += ["-f", "matroska", temp_path]

        step2 = [FFMPEG_CMD, "-y", "-i", temp_path, "-c:v", "libx264", "-preset", preset_name, "-pix_fmt", "yuv420p"]
        if strategy == "vbr":
            maxrate = f"{int(vbr_kbps * 1.5)}k"
            bufsize = f"{int(vbr_kbps * 2)}k"
            step2 += ["-b:v", f"{vbr_kbps}k", "-maxrate", maxrate, "-bufsize", bufsize]
        else:
            maxrate, bufsize = ("20M", "40M") if resolution == "1080p" else ("12M", "24M")
            if resolution == "480p":
                maxrate, bufsize = "6M", "12M"
            step2 += ["-crf", str(crf), "-maxrate", maxrate, "-bufsize", bufsize]
        step2 += output_args + audio_args + color_args + [output_path]

        log_lines = [
            f"[CHRONOS] PAYLOAD strategy={strategy} vbr_kbps={vbr_kbps} crf={crf} preset={preset_name} codec={codec_choice} hw={hw_accel} two_pass={two_pass}",
            f"[CHRONOS] HEVC-INT STEP1: {' '.join(str(c) for c in step1)}",
            f"[CHRONOS] HEVC-INT STEP2: {' '.join(str(c) for c in step2)}",
        ]
        return {
            "mode": "hevc_intermediate",
            "step1_cmd": step1,
            "step2_cmd": step2,
            "temp_path": temp_path,
            "log_lines": log_lines,
            "ffmpeg_cmd": " ".join(str(c) for c in step2),
            "duration": duration,
        }

    # Two-pass VBR (software only)
    if two_pass and strategy == "vbr" and not is_hw and codec_choice in ("h264", "hevc"):
        passlog_prefix = str(TEMP_DIR / f"{job_id}_passlog")
        pass1_cmd = base + video_args + ["-pass", "1", "-passlogfile", passlog_prefix, "-an", "-f", "null", os.devnull]
        pass2_cmd = base + video_args + ["-pass", "2", "-passlogfile", passlog_prefix] + output_args + audio_args + color_args + [output_path]

        log_lines = [
            f"[CHRONOS] PAYLOAD strategy={strategy} vbr_kbps={vbr_kbps} crf={crf} preset={preset_name} codec={codec_choice} hw={hw_accel} two_pass={two_pass}",
            f"[CHRONOS] PASS1 CMD: {' '.join(str(c) for c in pass1_cmd)}",
            f"[CHRONOS] PASS2 CMD: {' '.join(str(c) for c in pass2_cmd)}",
        ]
        return {
            "mode": "two_pass",
            "step1_cmd": pass1_cmd,
            "step2_cmd": pass2_cmd,
            "temp_path": None,
            "log_lines": log_lines,
            "ffmpeg_cmd": " ".join(str(c) for c in pass2_cmd),
            "duration": duration,
        }

    # Single pass direct
    cmd = base + video_args + output_args + audio_args + color_args + [output_path]
    log_lines = [
        f"[CHRONOS] PAYLOAD strategy={strategy} vbr_kbps={vbr_kbps} crf={crf} preset={preset_name} codec={codec_choice} hw={hw_accel} two_pass={two_pass}",
        f"[CHRONOS] CMD: {' '.join(str(c) for c in cmd)}",
    ]
    return {
        "mode": "direct",
        "step1_cmd": cmd,
        "step2_cmd": None,
        "temp_path": None,
        "log_lines": log_lines,
        "ffmpeg_cmd": " ".join(str(c) for c in cmd),
        "duration": duration,
    }


# ── FFmpeg Job Runners ──

def run_ffmpeg_simple(job_id: str, cmd: list, duration: float, weight: float = 1.0, offset: float = 0.0):
    job = jobs[job_id]
    print(f"[CHRONOS] RUNNING: {' '.join(str(c) for c in cmd)}")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    job["proc"] = proc
    for line in proc.stdout:
        if job.get("status") in ("cancelled", "stopped"):
            break
        line_stripped = line.strip()
        print(line_stripped)
        job["log"].append(line_stripped)
        if duration and duration > 0:
            m = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", line_stripped)
            if m:
                h, mn, s = map(float, m.groups())
                current = h * 3600 + mn * 60 + s
                raw_pct = min(99.9, (current / duration) * 100)
                job["progress"] = min(99, int(offset + raw_pct * weight))
    proc.wait()
    job["proc"] = None
    return proc.returncode == 0


def run_ffmpeg_segments(job_id: str, segments: list):
    job = jobs[job_id]
    job["status"] = "processing"
    job["log"] = []
    job["progress"] = 0
    job["started_at"] = time.time()
    job["output_files"] = []

    total = len(segments)
    for i, seg in enumerate(segments):
        if job.get("status") in ("cancelled", "stopped"):
            break
        ok = run_ffmpeg_simple(job_id, seg["cmd"], seg["duration"], weight=1.0/total, offset=(i/total)*100)
        if not ok:
            job["status"] = "error"
            job["error"] = f"Segment {i+1}/{total} failed."
            return
        if Path(seg["output"]).exists():
            job["output_files"].append(seg["output"])

    if job.get("status") in ("cancelled", "stopped"):
        return

    if job["output_files"]:
        job["status"] = "completed"
        job["progress"] = 100
        job["output_path"] = job["output_files"][0]
        total_size = sum(Path(p).stat().st_size for p in job["output_files"])
        job["output_size"] = total_size
        out_info = run_ffprobe(job["output_files"][0])
        if not out_info.get("error"):
            has_audio = False
            try:
                has_audio = any("audio" in (s.get("codec_type") or "").lower() for s in out_info.get("streams", []))
            except Exception:
                pass
            job["output_summary"] = build_summary(out_info, Path(job["output_files"][0]).name, has_audio)
        else:
            job["output_summary"] = None
    else:
        job["status"] = "error"
        job["error"] = "All segments failed."


def run_ffmpeg_job(job_id: str, plan: dict):
    job = jobs[job_id]
    job["status"] = "processing"
    job["log"] = []
    job["progress"] = 0
    job["started_at"] = time.time()
    for line in plan.get("log_lines", []):
        job["log"].append(line)

    def _execute(plan_inner):
        ok = True
        mode = plan_inner["mode"]
        duration = plan_inner["duration"]
        step1 = plan_inner["step1_cmd"]
        step2 = plan_inner.get("step2_cmd")
        temp_path = plan_inner.get("temp_path")

        if mode == "hevc_intermediate" and step2:
            ok = run_ffmpeg_simple(job_id, step1, duration, weight=0.4, offset=0.0)
            if job.get("status") in ("cancelled", "stopped"):
                return ok, "stopped"
            if not ok or not Path(temp_path).exists():
                return False, "HEVC intermediate stage failed."
            ok = run_ffmpeg_simple(job_id, step2, duration, weight=0.6, offset=40.0)
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass
        elif mode == "two_pass" and step2:
            ok = run_ffmpeg_simple(job_id, step1, duration, weight=0.3, offset=0.0)
            if job.get("status") in ("cancelled", "stopped"):
                return ok, "stopped"
            if not ok:
                return False, "Two-pass stage 1 failed."
            ok = run_ffmpeg_simple(job_id, step2, duration, weight=0.7, offset=30.0)
            try:
                for f in TEMP_DIR.glob(f"{job_id}_passlog*"):
                    f.unlink(missing_ok=True)
            except Exception:
                pass
        else:
            ok = run_ffmpeg_simple(job_id, step1, duration, weight=1.0, offset=0.0)
        return ok, None

    ok, err_msg = _execute(plan)

    # Hardware fallback if driver/runtime failed
    if not ok and err_msg != "stopped" and job.get("settings", {}).get("hw_accel") not in ("none", "", None):
        hw_log = "\n".join(job.get("log", []))
        hw_fallback_keywords = [
            "Driver does not support",
            "No device available",
            "Failed to create DXVA",
            "Device creation failed",
            "Function not implemented",
            "Error while opening encoder",
        ]
        hw_encoders_mentioned = ["h264_nvenc", "hevc_nvenc", "h264_qsv", "hevc_qsv", "h264_amf", "hevc_amf"]
        if any(kw in hw_log for kw in hw_fallback_keywords) and any(hw in hw_log for hw in hw_encoders_mentioned):
            job["log"].append("[CHRONOS] HARDWARE ENCODER FAILED. Auto-falling back to CPU (software) encoding...")
            print("[CHRONOS] HARDWARE ENCODER FAILED. Auto-falling back to CPU (software) encoding...")
            job["settings"]["hw_accel"] = "none"
            fallback_plan = build_encode_plan(job_id, job["settings"])
            for line in fallback_plan.get("log_lines", []):
                job["log"].append(line)
                print(line)
            job["ffmpeg_cmd"] = fallback_plan["ffmpeg_cmd"]
            ok, err_msg = _execute(fallback_plan)

    if job.get("status") in ("cancelled", "stopped"):
        return

    if ok and Path(job["output_path"]).exists():
        job["status"] = "completed"
        job["progress"] = 100
        job["output_size"] = Path(job["output_path"]).stat().st_size
        out_info = run_ffprobe(job["output_path"])
        if not out_info.get("error"):
            has_audio = False
            try:
                has_audio = any("audio" in (s.get("codec_type") or "").lower() for s in out_info.get("streams", []))
            except Exception:
                pass
            job["output_summary"] = build_summary(out_info, Path(job["output_path"]).name, has_audio)
        else:
            job["output_summary"] = None
    else:
        job["status"] = "error"
        job["error"] = err_msg or "FFmpeg exited with errors. Check terminal logs."


# ── Routes ──

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/hwstatus")
def hwstatus():
    return jsonify(HW_STATUS)


@app.route("/upload", methods=["POST"])
def upload():
    try:
        if "video" not in request.files:
            return jsonify({"error": "No video file provided"}), 400
        file = request.files["video"]
        if not file.filename:
            return jsonify({"error": "Empty filename"}), 400

        job_id = str(uuid.uuid4())
        ext = Path(file.filename).suffix
        input_path = UPLOAD_DIR / f"{job_id}{ext}"
        file.save(str(input_path))

        info = run_ffprobe(str(input_path))
        if info.get("error"):
            return jsonify({"error": info["error"]}), 500

        audio_present = has_audio(str(input_path))
        summary = build_summary(info, file.filename, audio_present)

        thumb_path = UPLOAD_DIR / f"{job_id}_thumb.jpg"
        has_thumb = False
        try:
            subprocess.run(
                [FFMPEG_CMD, "-y", "-i", str(input_path), "-ss", "00:00:01", "-vframes", "1", "-q:v", "2", str(thumb_path)],
                capture_output=True,
                timeout=30,
            )
            has_thumb = thumb_path.exists()
        except Exception:
            pass

        jobs[job_id] = {
            "status": "uploaded",
            "input_path": str(input_path),
            "output_path": str(OUTPUT_DIR / f"{job_id}_tiktok.mp4"),
            "info": info,
            "summary": summary,
            "log": [],
            "progress": 0,
            "error": None,
            "ffmpeg_cmd": None,
            "proc": None,
            "platform": "tiktok",
        }
        return jsonify({"job_id": job_id, "summary": summary, "has_thumb": has_thumb})

    except RequestEntityTooLarge:
        return jsonify({"error": "Upload too large. Max 800 MB."}), 413
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/thumbnail/<job_id>")
def thumbnail(job_id):
    thumb = UPLOAD_DIR / f"{job_id}_thumb.jpg"
    if thumb.exists():
        return send_file(str(thumb), mimetype="image/jpeg")
    return jsonify({"error": "No thumbnail"}), 404


@app.route("/recommend/<job_id>")
def recommend(job_id):
    if job_id not in jobs:
        return jsonify({"error": "Invalid job_id"}), 400
    platform = request.args.get("platform", "tiktok")
    rec = smart_recommend(jobs[job_id]["summary"], platform)
    return jsonify(rec)


@app.route("/estimate", methods=["POST"])
def estimate():
    data = request.get_json(force=True)
    job_id = data.get("job_id")
    if not job_id or job_id not in jobs:
        return jsonify({"error": "Invalid job_id"}), 400

    selected_preset = data.get("selected_preset", "")
    if selected_preset == "ksaevelo":
        return jsonify({"estimate": {"seconds": 5, "label": "~5s"}, "alternatives": []})

    settings = {
        "resolution": data.get("resolution", "1080p"),
        "preset": data.get("preset", "slow"),
        "codec": data.get("codec", "h264"),
        "strategy": data.get("strategy", "crf"),
        "hevc_intermediate": data.get("hevc_intermediate", False),
        "hw_accel": data.get("hw_accel", "none"),
        "two_pass": data.get("two_pass", False),
        "platform": data.get("platform", "tiktok"),
        "wa_mode": data.get("wa_mode", "status"),
    }
    summary = jobs[job_id]["summary"]
    est = estimate_time(summary, settings)
    alts = get_faster_alternatives(summary, settings)
    return jsonify({"estimate": est, "alternatives": alts})


@app.route("/process", methods=["POST"])
def process():
    data = request.get_json(force=True)
    job_id = data.get("job_id")
    if not job_id or job_id not in jobs:
        return jsonify({"error": "Invalid job_id"}), 400

    job = jobs[job_id]

    # Reset job state for retry/restart
    if job.get("proc"):
        try:
            job["proc"].kill()
        except Exception:
            pass
    job["status"] = "processing"
    job["log"] = []
    job["progress"] = 0
    job["error"] = None
    job["output_size"] = None
    job["output_summary"] = None
    job["started_at"] = time.time()
    job["ffmpeg_cmd"] = None
    job["output_files"] = []

    platform = data.get("platform", "tiktok")
    wa_mode = data.get("wa_mode", "status")
    job["platform"] = platform
    job["wa_mode"] = wa_mode

    input_path = job["input_path"]
    duration = job["summary"]["duration"]
    source_has_audio = has_audio(input_path)

    selected_preset = data.get("selected_preset", "")
    if selected_preset == "ksaevelo":
        container = data.get("container", "mp4")
        stem = Path(job["summary"]["filename"]).stem.replace(" ", "_")
        ext = get_container_ext(container)
        output_filename = f"{stem}_KSAEVELO{ext}"
        output_path = str(OUTPUT_DIR / output_filename)
        job["output_path"] = output_path

        source_fps = job["summary"].get("fps", 0)
        if source_fps >= 100:
            itsscale = 6
        elif source_fps >= 45:
            itsscale = 2
        else:
            itsscale = 1

        cmd = [FFMPEG_CMD, "-itsscale", str(itsscale), "-i", input_path, "-c:v", "copy", "-c:a", "copy"]
        if container in ("mp4", "mov"):
            cmd += ["-movflags", "+faststart"]
        cmd += [output_path]

        log_lines = [
            f"[CHRONOS] PAYLOAD selected_preset=ksaevelo itsscale={itsscale} source_fps={source_fps:.2f}",
            f"[CHRONOS] KSAEVELO CMD: {' '.join(str(c) for c in cmd)}",
        ]
        job["log"] = list(log_lines)
        for line in log_lines:
            print(line)
        job["ffmpeg_cmd"] = " ".join(str(c) for c in cmd)
        job["status"] = "processing"
        job["progress"] = 0
        job["started_at"] = time.time()
        job["output_files"] = []

        def run_ksaevelo():
            ok = run_ffmpeg_simple(job_id, cmd, duration=0, weight=1.0, offset=0.0)
            if job.get("status") in ("cancelled", "stopped"):
                return
            if ok and Path(output_path).exists():
                job["status"] = "completed"
                job["progress"] = 100
                job["output_size"] = Path(output_path).stat().st_size
                out_info = run_ffprobe(output_path)
                if not out_info.get("error"):
                    has_audio_out = False
                    try:
                        has_audio_out = any("audio" in (s.get("codec_type") or "").lower() for s in out_info.get("streams", []))
                    except Exception:
                        pass
                    job["output_summary"] = build_summary(out_info, Path(output_path).name, has_audio_out)
                    job["output_files"] = [output_path]
                else:
                    job["output_summary"] = None
            else:
                job["status"] = "error"
                job["error"] = "KSAEVELO stream copy failed."

        thread = threading.Thread(target=run_ksaevelo)
        thread.start()
        return jsonify({"status": "started", "mode": "ksaevelo"})

    resolution = data.get("resolution", "1080p")
    target_fps = int(data.get("fps", 60))
    aspect_mode = data.get("aspect_mode", "tiktok")
    codec_choice = data.get("codec", "h264")
    container = data.get("container", "mp4")
    strategy = data.get("strategy", "crf")
    crf = int(data.get("crf", 18))
    vbr_kbps = int(data.get("vbr_kbps", 12000))
    scale_filter = data.get("scale_filter", "bicubic")
    hevc_intermediate = data.get("hevc_intermediate", False)
    color_tags = data.get("color_tags", False)
    preset_name = data.get("preset", "slow")
    audio_mode = data.get("audio_mode", "lossy")
    audio_bitrate = int(data.get("audio_bitrate", 192))
    two_pass = data.get("two_pass", False)
    hw_accel = (data.get("hw_accel", "none") or "none").strip().lower()

    if strategy is None or strategy == "" or strategy == "null":
        strategy = "vbr" if vbr_kbps != 12000 else "crf"
    strategy = str(strategy).strip().lower()

    # Quality guardrails: prevent brutally low bitrates for TikTok that destroy visual fidelity
    if platform == "tiktok" and strategy == "vbr":
        quality_floor = {"480p": 1000, "720p": 2000, "1080p": 4000}.get(resolution, 2000)
        if vbr_kbps < quality_floor:
            print(f"[CHRONOS] QUALITY GUARDRAIL: VBR {vbr_kbps} kbps below {quality_floor} kbps floor for {resolution}. Clamping to floor to preserve watchable quality.")
            vbr_kbps = quality_floor

    stem = Path(job["summary"]["filename"]).stem.replace(" ", "_")
    ext = get_container_ext(container)

    # ── WhatsApp Status: auto-split segments ──
    if platform == "whatsapp" and wa_mode == "status" and duration > 30:
        num_segments = math.ceil(duration / 30)
        segments = []
        for i in range(num_segments):
            start = i * 30
            seg_dur = min(30, duration - start)
            seg_name = f"{stem}_CHRONOS_WA_{i+1:02d}{ext}"
            seg_path = str(OUTPUT_DIR / seg_name)

            vf = build_vf(resolution, aspect_mode, target_fps, scale_filter)
            aud = get_audio_settings(container, audio_mode, audio_bitrate)
            color_args = []
            if color_tags:
                color_args = ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
            vcodec = get_video_codec(codec_choice, hw_accel)
            is_hw = hw_accel in ("nvenc", "qsv", "amf")
            video_args = ["-c:v", vcodec, "-pix_fmt", "yuv420p"]
            if not is_hw:
                if codec_choice in ("h264", "hevc"):
                    video_args += ["-preset", preset_name]
            else:
                if hw_accel == "nvenc":
                    nvenc_preset = {"veryslow": "slow", "slow": "slow", "medium": "medium", "fast": "fast"}.get(preset_name, "medium")
                    video_args += ["-preset", nvenc_preset]
                elif hw_accel == "amf":
                    amf_preset = {"veryslow": "quality", "slow": "quality", "medium": "balanced", "fast": "speed"}.get(preset_name, "balanced")
                    video_args += ["-preset", amf_preset]
            if strategy == "vbr":
                maxrate = f"{int(vbr_kbps * 1.5)}k"
                bufsize = f"{int(vbr_kbps * 2)}k"
                video_args += ["-b:v", f"{vbr_kbps}k", "-maxrate", maxrate, "-bufsize", bufsize]
            else:
                video_args += ["-crf", str(crf)]
            output_args = ["-movflags", "+faststart"]
            audio_args = []
            if source_has_audio:
                audio_args += ["-c:a", aud["codec"]]
                if aud["bitrate"]:
                    audio_args += ["-b:a", aud["bitrate"]]
                audio_args += ["-ar", aud["ar"], "-ac", "2"]

            seg_cmd = [FFMPEG_CMD, "-fflags", "+genpts", "-y", "-ss", str(start), "-t", str(seg_dur), "-i", input_path, "-vf", vf] + video_args + output_args + audio_args + color_args + [seg_path]
            segments.append({"cmd": seg_cmd, "duration": seg_dur, "output": seg_path})

        log_lines = [
            f"[CHRONOS] PAYLOAD platform=whatsapp wa_mode={wa_mode} strategy={strategy} vbr_kbps={vbr_kbps} crf={crf} preset={preset_name} codec={codec_choice} hw={hw_accel} segments={num_segments}",
            f"[CHRONOS] WHATSAPP STATUS SEGMENTS: {num_segments}",
        ]
        for seg in segments:
            log_lines.append(f"[CHRONOS] SEG CMD: {' '.join(str(c) for c in seg['cmd'])}")
        job["log"] = list(log_lines)
        for line in log_lines:
            print(line)
        job["ffmpeg_cmd"] = " [SEGMENT] ".join(" ".join(str(c) for c in s["cmd"]) for s in segments)

        thread = threading.Thread(target=run_ffmpeg_segments, args=(job_id, segments))
        thread.start()
        return jsonify({"status": "started", "mode": "whatsapp_segments", "segments": num_segments})

    # ── Standard single-file paths (TikTok or WhatsApp Chat) ──
    job["settings"] = {
        "resolution": resolution,
        "fps": target_fps,
        "aspect_mode": aspect_mode,
        "codec": codec_choice,
        "container": container,
        "strategy": strategy,
        "crf": crf,
        "vbr_kbps": vbr_kbps,
        "scale_filter": scale_filter,
        "hevc_intermediate": hevc_intermediate,
        "color_tags": color_tags,
        "preset": preset_name,
        "audio_mode": audio_mode,
        "audio_bitrate": audio_bitrate,
        "two_pass": two_pass,
        "hw_accel": hw_accel,
        "platform": platform,
        "wa_mode": wa_mode,
    }

    plan = build_encode_plan(job_id, job["settings"])
    job["log"] = list(plan["log_lines"])
    for line in job["log"]:
        print(line)
    job["ffmpeg_cmd"] = plan["ffmpeg_cmd"]

    thread = threading.Thread(target=run_ffmpeg_job, args=(job_id, plan))
    thread.start()
    return jsonify({"status": "started", "mode": plan["mode"]})


@app.route("/control/<job_id>", methods=["POST"])
def control(job_id):
    if job_id not in jobs:
        return jsonify({"error": "Invalid job_id"}), 400
    data = request.get_json(force=True)
    action = data.get("action", "")
    job = jobs[job_id]
    pid = job.get("proc") and job["proc"].pid

    if action == "stop":
        if pid:
            kill_process(pid)
        job["status"] = "stopped"
        job["error"] = "User stopped."
        return jsonify({"status": "stopped"})
    elif action == "pause":
        if pid:
            if suspend_process(pid):
                job["status"] = "paused"
                return jsonify({"status": "paused"})
        return jsonify({"error": "Cannot pause"}), 400
    elif action == "resume":
        if pid:
            if resume_process(pid):
                job["status"] = "processing"
                return jsonify({"status": "resumed"})
        return jsonify({"error": "Cannot resume"}), 400
    return jsonify({"error": "Unknown action"}), 400


@app.route("/delete/<job_id>", methods=["POST"])
def delete_job(job_id):
    if job_id not in jobs:
        return jsonify({"error": "Invalid job_id"}), 400
    job = jobs[job_id]
    if job.get("proc"):
        try:
            job["proc"].kill()
        except Exception:
            pass
    for path in [job.get("input_path"), job.get("output_path")]:
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass
    for f in job.get("output_files", []):
        try:
            Path(f).unlink(missing_ok=True)
        except Exception:
            pass
    try:
        (UPLOAD_DIR / f"{job_id}_thumb.jpg").unlink(missing_ok=True)
    except Exception:
        pass
    for f in TEMP_DIR.glob(f"{job_id}*"):
        try:
            f.unlink(missing_ok=True)
        except Exception:
            pass
    del jobs[job_id]
    return jsonify({"status": "deleted"})


@app.route("/status/<job_id>")
def status(job_id):
    job = jobs.get(job_id, {})
    elapsed = 0
    if job.get("started_at"):
        elapsed = int(time.time() - job.get("started_at"))
    return jsonify({
        "status": job.get("status"),
        "progress": job.get("progress"),
        "log": job.get("log", [])[-30:],
        "error": job.get("error"),
        "output_size": job.get("output_size"),
        "output_summary": job.get("output_summary"),
        "output_files": job.get("output_files", []),
        "ffmpeg_cmd": job.get("ffmpeg_cmd"),
        "elapsed_seconds": elapsed,
        "platform": job.get("platform", "tiktok"),
        "wa_mode": job.get("wa_mode", "status"),
    })


@app.route("/download/<job_id>")
def download(job_id):
    job = jobs.get(job_id)
    if not job or job.get("status") != "completed":
        return jsonify({"error": "Not ready"}), 400
    idx = request.args.get("idx", 0, type=int)
    files = job.get("output_files", [])
    if files and idx < len(files):
        path = files[idx]
    elif job.get("output_path"):
        path = job["output_path"]
    else:
        return jsonify({"error": "No output file"}), 400
    return send_file(
        path,
        as_attachment=True,
        download_name=Path(path).name,
        mimetype="video/mp4",
    )


# ── WhatsApp Integration ──

@app.route("/whatsapp/bridge/status")
def wa_bridge_status():
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:3000/status", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return jsonify(json.loads(resp.read()))
    except Exception:
        return jsonify({"ready": False, "qr": None})


@app.route("/whatsapp/send", methods=["POST"])
def whatsapp_send():
    data = request.get_json(force=True)
    job_id = data.get("job_id")
    phone = data.get("phone", "").strip()
    if not phone:
        return jsonify({"error": "Phone number required"}), 400
    job = jobs.get(job_id)
    if not job or job.get("status") != "completed":
        return jsonify({"error": "Job not ready"}), 400

    # Try local bridge first
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:3000/status", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            bridge = json.loads(resp.read())
        if bridge.get("ready"):
            files = job.get("output_files", [])
            if not files and job.get("output_path"):
                files = [job["output_path"]]
            for f in files:
                payload = json.dumps({"to": phone, "file": f}).encode()
                req2 = urllib.request.Request(
                    "http://localhost:3000/send",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                urllib.request.urlopen(req2, timeout=30)
            return jsonify({"sent": True, "via": "bridge"})
    except Exception as e:
        print(f"[CHRONOS] WhatsApp bridge not available: {e}")

    # Fallback: wa.me link
    text = "Compressed+video+from+CHRONOS"
    link = f"https://wa.me/{phone}?text={text}"
    return jsonify({"sent": False, "link": link, "reason": "bridge_not_ready"})


@app.errorhandler(RequestEntityTooLarge)
def handle_large_upload(error):
    return jsonify({"error": "Upload too large. Max 800 MB."}), 413


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000, threaded=True)
