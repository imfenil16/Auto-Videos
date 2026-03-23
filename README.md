# Viral Edit Video Generator

Recreates the **"play → freeze → cutout outline → expanding reveal → dark animated background"** style popular on TikTok/Reels — fully automated.

## What It Does

Given **1 video** and **N background images**, it produces a vertical (9:16) video with:

1. **Play** (0 → freeze) — Video plays full-screen with gentle zoom
2. **Freeze** — Frame freezes, subject is cut out (AI background removal) with a bold white silhouette outline on a blurred freeze frame
3. **Reveal** — Barn-door wipe expands from center with torn-paper edges, revealing the background slideshow
4. **Loop** — Background images cycle with Ken Burns effect (zoom + pan), dark/grayscale, stacking slide-in transitions
5. **Subject** — Cutout stays on top with subtle shake throughout

Uses **rembg** (U2Net) for AI background removal and **OpenCV** for outline generation.

## Prerequisites

- **Python 3.10+**
- **FFmpeg** (required by MoviePy)
  ```powershell
  winget install Gyan.FFmpeg
  ```

### Install dependencies
```powershell
pip install -r requirements.txt
```

## Usage

### CLI
```powershell
python generate_video.py -v clip.mp4 -i bg1.jpg bg2.jpg bg3.jpg
python generate_video.py -v clip.mp4 -i bg1.png bg2.png -o result.mp4 --freeze 1.5 --seed 123
```

| Arg | Description |
|-----|-------------|
| `-v`, `--video` | Input video file (required) |
| `-i`, `--images` | Background images — files and/or directories (required) |
| `-o`, `--output` | Output path (default: `output.mp4`) |
| `--freeze` | When to freeze, in seconds (default: `1.5`) |
| `--seed` | Random seed for reproducible Ken Burns directions (default: `42`) |

### Web UI
```powershell
python app.py
```
Opens at `http://localhost:5000`. Drag and drop a video + images, set freeze time, and download the result.

## Configuration

Edit the constants at the top of `generate_video.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `OUTPUT_WIDTH` | 1080 | Video width |
| `OUTPUT_HEIGHT` | 1920 | Video height (9:16) |
| `FPS` | 30 | Frames per second |
| `FREEZE_TIME` | 1.5 | When to freeze (seconds) |
| `FREEZE_BG_BLUR` | 15 | Blur on frozen background |
| `FREEZE_HOLD` | 0.25 | Hold on blurred bg before wipe |
| `OUTLINE_THICKNESS` | 14 | White outline width (px) |
| `TEAR_AMPLITUDE` | 24 | Torn paper edge jaggedness (px) |
| `TEAR_FREQUENCY` | 0.018 | Torn paper bump density |
| `SHAKE_AMPLITUDE` | 4 | Subject shake intensity (px) |
| `SHAKE_FREQUENCY` | 8.0 | Shake oscillations per second |
| `BG_BLUR` | 5 | Background Gaussian blur |
| `BG_DIM` | 0.45 | Background brightness (0–1) |
| `BG_GRAYSCALE` | True | Grayscale backgrounds |
| `BG_IMAGE_DURATION` | 0.6 | Seconds per background image |
| `BG_CROSSFADE` | 0.25 | Crossfade between images |
| `BG_ZOOM` | (1.0, 1.12) | Ken Burns zoom range |

## How It Works

```
INPUT:  1 video + N images
           │
    ┌──────┴──────┐
    │  Phase 1     │  → Play video with gentle zoom
    └──────┬──────┘
           │
    ┌──────┴──────┐
    │  Phase 2     │  → Freeze frame → rembg AI cutout → white outline
    │              │  → Blurred freeze background + white flash
    └──────┬──────┘
           │
    ┌──────┴──────┐
    │  Phase 3     │  → Barn-door wipe (torn paper edges)
    │              │  → Background slideshow (dark, grayscale, Ken Burns)
    │              │  → Subject cutout with shake on top
    └──────┬──────┘
           │
       output.mp4
```

## Tips

- Use **5–15 background images** for best results (they loop automatically)
- Video duration = input video duration (backgrounds loop to fill)
- Foreground audio is preserved in the output
- Change `--seed` for different random pan/zoom directions
