# Soft Body Ring Drop — Video Generator

Recreates the @KAWAKEN_3DCG style soft body demo video using Blender + Python.

## Prerequisites

### 1. Install Blender (free)
- Download from https://www.blender.org/download/
- Install normally
- Make sure `blender` is accessible from your terminal:
  - Default install path: `C:\Program Files\Blender Foundation\Blender 4.x\blender.exe`
  - Or add it to your PATH

### 2. Install FFmpeg (free, for stitching clips)
Run in PowerShell:
```powershell
winget install Gyan.FFmpeg
```
Or download from https://ffmpeg.org/download.html

## Usage

### Quick Start (one command)
```powershell
# Replace with your actual Blender path if not in PATH
& "C:\Program Files\Blender Foundation\Blender 4.2\blender.exe" --background --python generate_video.py
```

### If Blender is in your PATH
```powershell
blender --background --python generate_video.py
```

### What happens
1. Blender opens in background mode (no GUI)
2. For each softness value (0%, 10%, 25%, 50%, 80%, 100%):
   - Creates the wooden cone sculpture
   - Creates the glass ring
   - Applies soft body physics
   - Renders the animation as PNG frames
3. FFmpeg stitches all clips into `renders/final_output.mp4`

### If FFmpeg wasn't found during rendering
Run the fallback stitch script:
```powershell
.\stitch_videos.ps1
```

## Configuration

Edit the top of `generate_video.py` to adjust:

| Setting | Default | Description |
|---------|---------|-------------|
| `RESOLUTION_X` | 1080 | Video width |
| `RESOLUTION_Y` | 1920 | Video height (9:16 vertical) |
| `FPS` | 30 | Frames per second |
| `CLIP_DURATION_SEC` | 5 | Seconds per softness value |
| `SAMPLES` | 64 | Render quality (higher = better but slower) |
| `USE_EEVEE` | True | True = fast render, False = Cycles (photorealistic) |

## Output

```
renders/
├── soft_000/        # Frames for Soft 0%
├── soft_010/        # Frames for Soft 10%
├── soft_025/        # Frames for Soft 25%
├── soft_050/        # Frames for Soft 50%
├── soft_080/        # Frames for Soft 80%
├── soft_100/        # Frames for Soft 100%
├── clip_000.mp4     # Individual clips
├── clip_010.mp4
├── ...
└── final_output.mp4 # Final stitched video
```

## Tips
- First run with `SAMPLES = 16` and `CLIP_DURATION_SEC = 2` for a quick preview
- Switch `USE_EEVEE = False` for photorealistic Cycles rendering (much slower)
- Increase `SAMPLES` to 256+ for production quality
