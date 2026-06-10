# J.A.R.V.I.S. TikTok Video Optimizer

A monochrome, Iron Man-inspired web app that compresses and optimizes videos for flawless TikTok uploads.

## Features

| Feature | Detail |
|---------|--------|
| **Resolutions** | 1080p (1080×1920 vertical) or 720p (720×1280 vertical) |
| **Framerate** | Adjustable 1–120 FPS |
| **Quality** | CRF 18 (visually lossless) by default |
| **TikTok Ready** | H.264 High Profile, AAC audio, MP4 container, `+faststart`, yuv420p |
| **Aspect Ratio** | Force 9:16 with padding, or keep original aspect ratio |
| **Web Optimized** | Progressive download, capped bitrate, mobile-friendly encoding |

## Requirements

- Python 3.9+
- FFmpeg installed and available in your `PATH`
  - Install via [ffmpeg.org](https://ffmpeg.org/download.html) or your package manager:
    - macOS: `brew install ffmpeg`
    - Ubuntu/Debian: `sudo apt update && sudo apt install ffmpeg`
    - Windows: download from gyan.dev or use `winget install Gyan.FFmpeg`

## Setup

```bash
cd tiktok-jarvis-optimizer

# Create virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the server
python app.py
```

Open your browser to **http://localhost:5000**

## How to Use

1. **Upload** your video (drag & drop or click).
2. **Review** the input analysis panel (resolution, codec, bitrate, duration).
3. **Configure** output settings:
   - **Resolution**: 1080p or 720p vertical.
   - **Framerate**: 30, 60, or up to 120 FPS.
   - **Aspect Modulator**: TikTok 9:16 (with black padding) or Original aspect ratio.
   - **Quality / CRF**: 18 is visually lossless. Lower = bigger file, higher quality.
4. **Click** "INITIATE COMPRESSION".
5. **Download** the optimized file when complete.

## Why This Works for TikTok

TikTok re-encodes almost everything uploaded. By matching TikTok's preferred spec ahead of time, you minimize generational quality loss:
- **H.264 High Profile** — best compatibility with TikTok's ingestion pipeline.
- **AAC 128 kbps 44.1 kHz** — standard audio spec.
- **yuv420p + faststart** — web/mobile playback optimized.
- **Bitrate cap** — prevents bloat while CRF 18 keeps detail crisp.
- **9:16 padding** — ensures TikTok displays your video full-screen without extra cropping.

## Tech Stack

- **Backend**: Python / Flask / FFmpeg CLI
- **Frontend**: Vanilla JS, CSS3 animations, SVG HUD elements
- **Design**: Black & white, Orbitron + Share Tech Mono typography, J.A.R.V.I.S. HUD aesthetic
