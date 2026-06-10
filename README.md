# CHRONOS // Temporal Video Engine v4.0

> *Compress. Optimize. Upload. Zero compromise.*

Holographic HUD video compressor for **TikTok** and **WhatsApp**. H.264/H.265/VP9/AV1. CRF, VBR, two-pass, hardware accel auto-detect. Smart Recommend. Batch queue. WhatsApp Status auto-split. WhatsApp Web bridge optional.

Built for creators who refuse to let platforms destroy their footage.

---

## Requirements

- Python 3.9+
- FFmpeg + ffprobe in PATH (or `C:\ffmpeg\bin`, or bundled next to the app)

Optional:
- Node.js — only for WhatsApp auto-send bridge (`npm install && node wa-bridge.js`)
- psutil — reliable pause/resume on Windows (`pip install psutil`)

---

## Install

```bash
cd tiktok-jarvis-optimizer
python -m venv venv
venv\Scripts\activate  # or source venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python app.py
```

Open **http://localhost:5000**

---

## Presets

| Preset | Platform | What it does |
|--------|----------|--------------|
| **TikTok Studio** | TikTok | 1080p 60fps CRF 18. Maximum quality. |
| **Quality First** | TikTok | 1080p 30fps balanced. Smaller file, still crisp. |
| **4K Lanczos** | TikTok | 1080p 30fps Lanczos scale. Best for 4K sources. |
| **Max Compatibility** | TikTok | CRF 20 medium. Widest device support. |
| **KSAEVELO** | TikTok | Metadata timing trick (`-itsscale`). Zero re-encode. TikTok reads it as smooth high-FPS without crushing quality. |
| **Status 720p** | WhatsApp | 720p VBR 1.5 Mbps. Auto-split >30s. |
| **Status HD** | WhatsApp | 1080p VBR 2.5 Mbps. Auto-split >30s. |
| **Chat Send** | WhatsApp | 1080p CRF 18. Single file, no split. |

**KSAEVELO**: stream-copies your video with adjusted timing metadata. Local playback looks slower — TikTok reads it correctly and plays smooth.

---

## Quick Workflow

1. Drop video onto the hex zone.
2. Toggle **TikTok / WhatsApp** in the header.
3. Click **Smart Recommend** or pick a preset.
4. Click **Initiate**. Watch the HUD.
5. Download. Done.

---

## Hardware Accel

Auto-detected at startup. Green = working. Orange = driver issue. Red = not present. Click any dot for full diagnostic stderr.

---

## Build .exe (Optional)

When everything is finalized:

```bash
pip install pywebview pyinstaller
python build.py
```

Outputs `dist/CHRONOS.exe` — native window, no browser needed.

---

## Stack

Python / Flask / FFmpeg CLI — Vanilla JS / CSS3 — WebView2 / PyInstaller
