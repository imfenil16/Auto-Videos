#!/usr/bin/env python3
"""
Viral Edit Video Generator
==========================
Creates the "play → freeze → cutout outline → dark animated background" style.

Timeline:
  Phase 1 — PLAY     (0 – freeze_t):  Video plays full-screen with zoom
  Phase 2 — FREEZE   (freeze_t):      Frame freezes, subject highlighted on blurred bg
  Phase 3 — REVEAL   (expanding):     Vertical window expands from center revealing slideshow
  Phase 4 — LOOP     (rest):          Bg images cycle (Ken Burns, dark/grayscale, crossfade)

Key style rules:
  - Foreground = cutout with silhouette OUTLINE (not card/box)
  - Subject is BOTTOM-ALIGNED (not centered)
  - Foreground is STATIC (no breathing/floating/shake)
  - Background provides all motion

Usage:
  python generate_video.py -v clip.mp4 -i bg1.jpg bg2.jpg bg3.jpg
  python generate_video.py -v clip.mp4 -i ./backgrounds/ --freeze 1.5 -o result.mp4

Requirements:
  pip install moviepy pillow numpy rembg opencv-python
"""

import argparse
import math
import os
import random
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

try:
    from moviepy.editor import VideoFileClip, VideoClip
except ImportError:
    try:
        from moviepy import VideoFileClip, VideoClip
    except ImportError:
        print("Error: moviepy is required.\n  pip install moviepy")
        sys.exit(1)

try:
    from rembg import remove as rembg_remove
    HAS_REMBG = True
except ImportError:
    HAS_REMBG = False


# ═══════════════════════════════════════════════════════════════
# CONFIGURATION — Tweak these to change the style
# ═══════════════════════════════════════════════════════════════

# Output
OUTPUT_WIDTH  = 1080
OUTPUT_HEIGHT = 1920        # 9:16 vertical
FPS           = 30

# Phase 1: Play video (before freeze)
HOOK_ZOOM     = (1.0, 1.12) # scale range during pre-freeze playback

# Phase 2→3: Freeze + reveal transition
FREEZE_TIME         = 1.5   # seconds — when to freeze (overridable via --freeze)
FREEZE_BG_BLUR      = 15    # blur radius for the frozen frame background
FREEZE_HOLD         = 0.25  # seconds — hold on blurred bg before wipe starts
REVEAL_DURATION     = 0.6   # seconds — expanding barn-door wipe from center
WIPE_EDGE_WIDTH     = 3     # px — white separator line at wipe boundary
WIPE_EDGE_FEATHER   = 6     # px — soft glow around wipe edge
TEAR_AMPLITUDE      = 24    # px — how jagged the torn paper edge is
TEAR_FREQUENCY      = 0.018 # how many bumps per pixel width
FLASH_DURATION      = 0.12  # seconds — white flash on freeze
FLASH_PEAK          = 0.20  # max flash opacity (0–1)
SCALE_POP           = 1.05  # slight scale pop on cutout at freeze
SCALE_POP_DURATION  = 0.20  # seconds — pop in/out

# Subject shake (subtle vibration after freeze)
SHAKE_AMPLITUDE     = 4     # max px offset
SHAKE_FREQUENCY     = 8.0   # oscillations per second

# Subject cutout (silhouette outline, NOT card/box)
OUTLINE_THICKNESS   = 14    # white outline around subject silhouette (px) — bold & visible
OUTLINE_FEATHER     = 1     # slight softness on outline edge (px)
SHADOW_BLUR         = 10    # subtle drop shadow blur
SHADOW_OPACITY      = 0.15  # subtle shadow opacity
SHADOW_OFFSET_Y     = 5     # shadow Y offset

# Background slideshow (dark cinematic style)
BG_BLUR           = 5       # Gaussian blur radius (4–6, NOT too high)
BG_DIM            = 0.45    # brightness multiplier
BG_GRAYSCALE      = True    # grayscale for cinematic feel
BG_IMAGE_DURATION = 0.6     # seconds per image
BG_CROSSFADE      = 0.25    # crossfade between images
BG_ZOOM           = (1.0, 1.12)  # Ken Burns zoom range
BG_PAN_MAX        = 0.03    # max pan as fraction of image size

# Vignette overlay
VIGNETTE_STRENGTH = 0.30    # 0 = off, 1.0 = full black edges

# Intensity phase (last portion of video)
INTENSITY_RATIO    = 0.7    # kicks in at this fraction of total duration
INTENSE_IMAGE_DUR  = 0.4    # faster switching
INTENSE_ZOOM       = (1.0, 1.15)  # more aggressive zoom


# ═══════════════════════════════════════════════════════════════
# EASING
# ═══════════════════════════════════════════════════════════════

def ease_out(t):
    """Cubic ease-out."""
    return 1 - (1 - t) ** 3

def ease_in_out(t):
    """Cubic ease-in-out."""
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2

def ease_in(t):
    """Quadratic ease-in — starts slow, accelerates."""
    return t * t


# ═══════════════════════════════════════════════════════════════
# TORN PAPER EDGE
# ═══════════════════════════════════════════════════════════════

def _build_tear_offsets(width, amplitude, frequency, seed=123):
    """Generate a rough torn-paper offset curve for one horizontal edge."""
    rng = random.Random(seed)
    offsets = np.zeros(width, dtype=np.float32)
    # Multi-octave: large slow waves + medium bumps + fine jagged noise
    for x in range(width):
        # Octave 1: slow undulation
        o1 = math.sin(x * frequency * 2 * math.pi) * amplitude * 0.35
        # Octave 2: medium bumps (3x frequency)
        o2 = math.sin(x * frequency * 6 * math.pi + 1.7) * amplitude * 0.25
        # Octave 3: fine jitter (9x frequency)
        o3 = math.sin(x * frequency * 18 * math.pi + 3.1) * amplitude * 0.15
        # Random noise
        noise = rng.uniform(-amplitude * 0.35, amplitude * 0.35)
        offsets[x] = o1 + o2 + o3 + noise
    return offsets

_tear_top = None
_tear_bot = None

def get_tear_offsets(width, amplitude, frequency):
    """Cached torn-paper offsets for top and bottom edges."""
    global _tear_top, _tear_bot
    if _tear_top is None or len(_tear_top) != width:
        _tear_top = _build_tear_offsets(width, amplitude, frequency, seed=101)
        _tear_bot = _build_tear_offsets(width, amplitude, frequency, seed=202)
    return _tear_top, _tear_bot


# ═══════════════════════════════════════════════════════════════
# IMAGE UTILITIES
# ═══════════════════════════════════════════════════════════════

def cover_resize(arr, w, h):
    """Resize numpy image to cover (w, h), center-cropping any excess."""
    src_h, src_w = arr.shape[:2]
    scale = max(w / src_w, h / src_h)
    nw = max(1, round(src_w * scale))
    nh = max(1, round(src_h * scale))
    resized = np.array(Image.fromarray(arr).resize((nw, nh), Image.LANCZOS))
    x0 = (nw - w) // 2
    y0 = (nh - h) // 2
    crop = resized[max(0, y0):max(0, y0) + h, max(0, x0):max(0, x0) + w]
    if crop.shape[0] != h or crop.shape[1] != w:
        crop = np.array(Image.fromarray(crop).resize((w, h), Image.LANCZOS))
    return crop


def paste_rgba(canvas, overlay_rgba, x, y):
    """Paste RGBA overlay onto RGB canvas using alpha compositing."""
    ch, cw = canvas.shape[:2]
    oh, ow = overlay_rgba.shape[:2]
    sx, sy = max(0, -x), max(0, -y)
    dx, dy = max(0, x), max(0, y)
    pw = min(ow - sx, cw - dx)
    ph = min(oh - sy, ch - dy)
    if pw <= 0 or ph <= 0:
        return
    src = overlay_rgba[sy:sy + ph, sx:sx + pw]
    a = src[:, :, 3:4].astype(np.float32) / 255.0
    rgb = src[:, :, :3].astype(np.float32)
    dst = canvas[dy:dy + ph, dx:dx + pw].astype(np.float32)
    canvas[dy:dy + ph, dx:dx + pw] = (rgb * a + dst * (1 - a)).astype(np.uint8)


def paste(canvas, overlay, x, y, alpha=None):
    """Paste overlay onto canvas at (x, y) with optional alpha mask."""
    ch, cw = canvas.shape[:2]
    oh, ow = overlay.shape[:2]
    sx, sy = max(0, -x), max(0, -y)
    dx, dy = max(0, x), max(0, y)
    pw = min(ow - sx, cw - dx)
    ph = min(oh - sy, ch - dy)
    if pw <= 0 or ph <= 0:
        return
    if alpha is not None:
        a = alpha[sy:sy + ph, sx:sx + pw, np.newaxis]
        dst = canvas[dy:dy + ph, dx:dx + pw].astype(np.float32)
        src = overlay[sy:sy + ph, sx:sx + pw].astype(np.float32)
        canvas[dy:dy + ph, dx:dx + pw] = (src * a + dst * (1 - a)).astype(np.uint8)
    else:
        canvas[dy:dy + ph, dx:dx + pw] = overlay[sy:sy + ph, sx:sx + pw]


# ═══════════════════════════════════════════════════════════════
# CUTOUT + SILHOUETTE OUTLINE BUILDER
# ═══════════════════════════════════════════════════════════════

def remove_background(frame_rgb):
    """Remove background from a video frame using rembg. Returns RGBA numpy array."""
    if not HAS_REMBG:
        print("Error: rembg is required for background removal.\n  pip install rembg")
        sys.exit(1)
    pil_img = Image.fromarray(frame_rgb)
    result = rembg_remove(pil_img)  # returns RGBA PIL Image
    return np.array(result)


def clean_mask(alpha):
    """Hard-threshold alpha to remove soft leftover background edges."""
    return np.where(alpha > 200, 255, 0).astype(np.uint8)


def build_outlined_cutout(cutout_rgba, outline_px, feather_px,
                          shadow_blur, shadow_opacity, shadow_offset_y):
    """
    Build subject cutout with white silhouette outline + subtle drop shadow.
    Uses mask dilation (not rectangle border).
    Returns RGBA numpy array.
    """
    import cv2

    h, w = cutout_rgba.shape[:2]
    alpha = cutout_rgba[:, :, 3].copy()
    alpha = clean_mask(alpha)
    rgb = cutout_rgba[:, :, :3]

    # Pad everything to fit outline + shadow
    pad = outline_px + shadow_blur + abs(shadow_offset_y) + feather_px
    pw, ph = w + 2 * pad, h + 2 * pad

    # ── Dilate mask to create outline region ──
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                       (outline_px * 2 + 1, outline_px * 2 + 1))
    dilated = cv2.dilate(alpha, kernel, iterations=1)

    # Outline = dilated - original mask
    outline_mask = np.clip(dilated.astype(np.int16) - alpha.astype(np.int16), 0, 255).astype(np.uint8)

    # Optional feather on the outline outer edge
    if feather_px > 0:
        outline_mask = cv2.GaussianBlur(outline_mask, (0, 0), feather_px)

    # ── Build output image (padded) ──
    result = np.zeros((ph, pw, 4), dtype=np.uint8)

    # Drop shadow: dilated mask shifted down, blurred, at low opacity
    shadow_layer = np.zeros((ph, pw), dtype=np.float32)
    sy = pad + shadow_offset_y
    sx = pad
    shadow_layer[sy:sy + h, sx:sx + w] = dilated.astype(np.float32) / 255.0
    shadow_layer = cv2.GaussianBlur(shadow_layer, (0, 0), shadow_blur)
    shadow_alpha = (shadow_layer * shadow_opacity * 255).clip(0, 255).astype(np.uint8)
    result[:, :, 3] = np.maximum(result[:, :, 3], shadow_alpha)
    # shadow is black (rgb stays 0)

    # White outline
    result[pad:pad + h, pad:pad + w, 0] = np.maximum(
        result[pad:pad + h, pad:pad + w, 0], outline_mask)
    result[pad:pad + h, pad:pad + w, 1] = np.maximum(
        result[pad:pad + h, pad:pad + w, 1], outline_mask)
    result[pad:pad + h, pad:pad + w, 2] = np.maximum(
        result[pad:pad + h, pad:pad + w, 2], outline_mask)
    result[pad:pad + h, pad:pad + w, 3] = np.maximum(
        result[pad:pad + h, pad:pad + w, 3], outline_mask)

    # Subject on top
    subj_alpha = alpha.astype(np.float32) / 255.0
    for c in range(3):
        existing = result[pad:pad + h, pad:pad + w, c].astype(np.float32)
        result[pad:pad + h, pad:pad + w, c] = (
            rgb[:, :, c].astype(np.float32) * subj_alpha +
            existing * (1 - subj_alpha)
        ).astype(np.uint8)
    result[pad:pad + h, pad:pad + w, 3] = np.maximum(
        result[pad:pad + h, pad:pad + w, 3], alpha)

    # Do NOT trim/crop — keep full canvas so subject stays at original position
    return result


_vignette_cache = {}

def vignette_overlay(w, h, strength):
    """Pre-compute darkening vignette (radial gradient), cached."""
    key = (w, h, int(strength * 100))
    if key not in _vignette_cache:
        Y, X = np.ogrid[:h, :w]
        cx, cy = w / 2, h / 2
        r = np.sqrt(((X - cx) / cx) ** 2 + ((Y - cy) / cy) ** 2)
        v = np.clip(r - 0.5, 0, 1) * strength
        _vignette_cache[key] = v.astype(np.float32)
    return _vignette_cache[key]


# ═══════════════════════════════════════════════════════════════
# BACKGROUND ENGINE
# ═══════════════════════════════════════════════════════════════

def load_bg_image(path, out_size, blur, dim, grayscale, max_zoom):
    """Load, process (grayscale, blur, dim), and oversize one background image."""
    ow, oh = out_size
    margin = max_zoom * 1.2
    img = Image.open(path).convert('RGB')
    if grayscale:
        img = img.convert('L').convert('RGB')
    if blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=blur))
    tw, th = int(ow * margin), int(oh * margin)
    ratio = img.width / img.height
    tr = tw / th
    if ratio > tr:
        nw, nh = int(th * ratio), th
    else:
        nw, nh = tw, int(tw / ratio)
    img = img.resize((nw, nh), Image.LANCZOS)
    arr = (np.array(img, dtype=np.float32) * dim).clip(0, 255).astype(np.uint8)
    return arr


def build_schedule(start, total_dur, n_images, seed=42):
    """Pre-compute the background image timeline (deterministic)."""
    rng = random.Random(seed)
    entries = []
    t, idx = start, 0
    intensity_t = total_dur * INTENSITY_RATIO
    while t < total_dur:
        intense = t >= intensity_t
        dur = INTENSE_IMAGE_DUR if intense else BG_IMAGE_DURATION
        zr = INTENSE_ZOOM if intense else BG_ZOOM
        zoom = zr if rng.random() > 0.5 else (zr[1], zr[0])
        pan = (rng.uniform(-BG_PAN_MAX, BG_PAN_MAX),
               rng.uniform(-BG_PAN_MAX, BG_PAN_MAX))
        entries.append(dict(start=t, end=t + dur, dur=dur,
                            img=idx % n_images, zoom=zoom, pan=pan))
        t += dur - BG_CROSSFADE
        idx += 1
    return entries


def kb_frame(img, t, dur, out_size, zoom, pan):
    """Render one Ken-Burns frame (zoom + pan on still image)."""
    ow, oh = out_size
    ih, iw = img.shape[:2]
    p = min(1.0, t / max(dur, 1e-6))
    z = zoom[0] + (zoom[1] - zoom[0]) * p
    crop_h = int(ih / z)
    crop_w = int(crop_h * (ow / oh))
    crop_w, crop_h = min(crop_w, iw), min(crop_h, ih)
    cx = iw // 2 + int(pan[0] * iw * p)
    cy = ih // 2 + int(pan[1] * ih * p)
    x1 = max(0, min(cx - crop_w // 2, iw - crop_w))
    y1 = max(0, min(cy - crop_h // 2, ih - crop_h))
    crop = img[y1:y1 + crop_h, x1:x1 + crop_w]
    return np.array(Image.fromarray(crop).resize((ow, oh), Image.LANCZOS))


def bg_at(t, schedule, images, out_size):
    """Background frame at time t, with stacking slide-in between images."""
    active = [e for e in schedule if e['start'] <= t < e['end']]
    if not active:
        e = schedule[-1]
        return kb_frame(images[e['img']], t - e['start'],
                        e['dur'], out_size, e['zoom'], e['pan'])
    if len(active) == 1:
        e = active[0]
        return kb_frame(images[e['img']], t - e['start'],
                        e['dur'], out_size, e['zoom'], e['pan'])
    # Stacking transition: new image slides in from top over old one
    f0 = kb_frame(images[active[0]['img']], t - active[0]['start'],
                  active[0]['dur'], out_size, active[0]['zoom'], active[0]['pan'])
    f1 = kb_frame(images[active[1]['img']], t - active[1]['start'],
                  active[1]['dur'], out_size, active[1]['zoom'], active[1]['pan'])
    a = min(1.0, (t - active[1]['start']) / BG_CROSSFADE)
    p = ease_out(a)
    ow, oh = out_size
    # Slide new image from top: starts at -oh, ends at 0
    offset_y = int(oh * (1 - p))
    canvas = f0.copy()
    if offset_y < oh:
        visible = oh - offset_y
        canvas[0:visible, :] = f1[offset_y:offset_y + visible, :]
    return canvas


# ═══════════════════════════════════════════════════════════════
# VIDEO GENERATOR
# ═══════════════════════════════════════════════════════════════

def generate(video_path, image_paths, output_path, freeze_time=None, duration=None, seed=42):
    ow, oh = OUTPUT_WIDTH, OUTPUT_HEIGHT
    out_size = (ow, oh)
    ft = freeze_time if freeze_time is not None else FREEZE_TIME

    print(f"[1/6] Loading video: {video_path}")
    video = VideoFileClip(video_path)
    total = video.duration
    if duration is not None and 0 < duration < total:
        total = duration
    ft = min(ft, total - 0.1)  # clamp freeze time

    print(f"[2/6] Extracting freeze frame at t={ft:.2f}s...")
    freeze_rgb = video.get_frame(ft)
    freeze_rgb = cover_resize(freeze_rgb, ow, oh)

    print("[3/6] Removing background (subject cutout)...")
    cutout_rgba = remove_background(freeze_rgb)

    print("[4/6] Building outlined cutout...")
    fg_rgba = build_outlined_cutout(cutout_rgba, OUTLINE_THICKNESS, OUTLINE_FEATHER,
                                     SHADOW_BLUR, SHADOW_OPACITY, SHADOW_OFFSET_Y)

    # Position at (0,0) — NO repositioning, NO scaling
    # The cutout is full-canvas size so subject stays exactly where it was in the video
    fg_h, fg_w = fg_rgba.shape[:2]
    fg_x = (ow - fg_w) // 2   # center the padded canvas (padding is symmetric)
    fg_y = (oh - fg_h) // 2

    # Build blurred freeze frame (background for reveal phase)
    print("[5/7] Building blurred freeze background...")
    blur_freeze = np.array(
        Image.fromarray(freeze_rgb).filter(
            ImageFilter.GaussianBlur(radius=FREEZE_BG_BLUR)
        )
    )
    # Keep it brighter than the slideshow so the wipe boundary is clearly visible
    blur_freeze = (blur_freeze.astype(np.float32) * 0.70).clip(0, 255).astype(np.uint8)

    print(f"[6/7] Loading {len(image_paths)} background images (dark cinematic)...")
    max_z = max(BG_ZOOM[1], INTENSE_ZOOM[1])
    bg_imgs = [load_bg_image(p, out_size, BG_BLUR, BG_DIM, BG_GRAYSCALE, max_z)
               for p in image_paths]

    print("[7/7] Building timeline & rendering...")
    sched = build_schedule(ft, total, len(bg_imgs), seed)
    vig = vignette_overlay(ow, oh, VIGNETTE_STRENGTH) if VIGNETTE_STRENGTH > 0 else None
    wipe_duration = total - ft - FREEZE_HOLD  # wipe spans rest of video

    def make_frame(t):
        # ═══ Phase 1: Play video full-screen (before freeze) ═══
        if t < ft:
            p = t / ft
            s = HOOK_ZOOM[0] + (HOOK_ZOOM[1] - HOOK_ZOOM[0]) * ease_out(p)
            cw_f = max(1, int(ow * s))
            ch_f = max(1, int(oh * s))
            frame = cover_resize(video.get_frame(t), cw_f, ch_f)
            canvas = np.zeros((oh, ow, 3), dtype=np.uint8)
            x = (ow - cw_f) // 2
            y = (oh - ch_f) // 2
            paste(canvas, frame, x, y)
            return canvas

        # ═══ Time since freeze ═══
        dt = t - ft

        # ── Animated slideshow background (always computed) ──
        slideshow_bg = bg_at(t, sched, bg_imgs, out_size)
        if vig is not None:
            slideshow_bg = (slideshow_bg.astype(np.float32) *
                            (1 - vig[:, :, np.newaxis])).clip(0, 255).astype(np.uint8)

        # ═══ Phase 2: Freeze + highlight on blurred bg ═══
        if dt < FREEZE_HOLD:
            # Hold on blurred freeze frame (subject highlighted, no wipe yet)
            canvas = blur_freeze.copy()

            # White flash effect (brief pop on freeze)
            if dt < FLASH_DURATION:
                flash_p = dt / FLASH_DURATION
                flash_alpha = FLASH_PEAK * (1.0 - abs(2.0 * flash_p - 1.0))
                canvas = (canvas.astype(np.float32) * (1 - flash_alpha) +
                          255.0 * flash_alpha).clip(0, 255).astype(np.uint8)

        # ═══ Phase 3: Barn-door wipe — center-out vertical expand (rest of video) ═══
        else:
            canvas = blur_freeze.copy()

            # Wipe progress (0→1) — ease-in: starts slow then accelerates
            wipe_t = dt - FREEZE_HOLD
            progress = min(1.0, wipe_t / max(wipe_duration, 0.1))

            # Growing strip from center
            half_h = int((oh / 2) * progress)
            center = oh // 2
            top_base = max(0, center - half_h)
            bot_base = min(oh, center + half_h)

            if top_base < bot_base:
                # Get torn paper offsets (vectorized)
                tear_top, tear_bot = get_tear_offsets(ow, TEAR_AMPLITUDE, TEAR_FREQUENCY)
                tear_scale = min(progress * 3, 1.0)

                # Build per-column top/bottom arrays
                col_tops = np.clip((top_base + (tear_top * tear_scale)).astype(np.int32), 0, oh)
                col_bots = np.clip((bot_base + (tear_bot * tear_scale)).astype(np.int32), 0, oh)

                # Build 2D mask: row_indices (oh, 1) vs col_tops/col_bots (1, ow)
                rows = np.arange(oh)[:, np.newaxis]  # (oh, 1)
                mask = (rows >= col_tops[np.newaxis, :]) & (rows < col_bots[np.newaxis, :])  # (oh, ow)

                # Apply mask: copy slideshow pixels where mask is True
                mask3 = mask[:, :, np.newaxis]  # (oh, ow, 1)
                np.copyto(canvas, slideshow_bg, where=mask3)

                # Edge glow: thin bright line along torn edges
                if progress < 0.95:
                    glow_w = WIPE_EDGE_WIDTH
                    # Top edge glow band
                    top_lo = np.clip(col_tops - glow_w, 0, oh).astype(np.int32)
                    top_hi = np.clip(col_tops + glow_w, 0, oh).astype(np.int32)
                    top_mask = (rows >= top_lo[np.newaxis, :]) & (rows < top_hi[np.newaxis, :])
                    # Bottom edge glow band
                    bot_lo = np.clip(col_bots - glow_w, 0, oh).astype(np.int32)
                    bot_hi = np.clip(col_bots + glow_w, 0, oh).astype(np.int32)
                    bot_mask = (rows >= bot_lo[np.newaxis, :]) & (rows < bot_hi[np.newaxis, :])
                    edge_mask = (top_mask | bot_mask)[:, :, np.newaxis]
                    canvas = np.where(edge_mask,
                                      np.minimum(canvas.astype(np.int16) + 120, 255).astype(np.uint8),
                                      canvas)

        # ── Subject cutout (always on top, with subtle shake) ──
        # Scale pop: brief 1.0 → 1.05 → 1.0 ease on freeze
        if 0 < dt < SCALE_POP_DURATION:
            pop_p = dt / SCALE_POP_DURATION
            pop_s = 1.0 + (SCALE_POP - 1.0) * (1.0 - abs(2.0 * pop_p - 1.0))
            pop_h = int(fg_rgba.shape[0] * pop_s)
            pop_w = int(fg_rgba.shape[1] * pop_s)
            popped = np.array(Image.fromarray(fg_rgba).resize((pop_w, pop_h), Image.LANCZOS))
            px = fg_x - (pop_w - fg_rgba.shape[1]) // 2
            py = fg_y - (pop_h - fg_rgba.shape[0]) // 2
            paste_rgba(canvas, popped, px, py)
        else:
            # Subtle shake: sinusoidal x/y jitter
            shake_x = int(SHAKE_AMPLITUDE * math.sin(dt * SHAKE_FREQUENCY * 2 * math.pi))
            shake_y = int(SHAKE_AMPLITUDE * math.cos(dt * SHAKE_FREQUENCY * 2.7 * math.pi) * 0.6)
            paste_rgba(canvas, fg_rgba, fg_x + shake_x, fg_y + shake_y)

        return canvas

    print(f"     Rendering {total:.1f}s @ {FPS}fps -> {output_path}")
    result = VideoClip(make_frame, duration=total)
    if video.audio:
        audio = video.audio.subclipped(0, total) if hasattr(video.audio, 'subclipped') else video.audio.subclip(0, total)
        if hasattr(result, 'with_audio'):
            result = result.with_audio(audio)
        else:
            result = result.set_audio(audio)
    result.write_videofile(output_path, fps=FPS, codec='libx264',
                           audio_codec='aac', bitrate='8000k', logger='bar')
    video.close()
    print(f"\nDone! -> {output_path}")


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff'}

def collect_images(paths):
    """Expand directories and validate image paths."""
    images = []
    for p in paths:
        if os.path.isdir(p):
            for f in sorted(os.listdir(p)):
                if os.path.splitext(f)[1].lower() in IMAGE_EXTS:
                    images.append(os.path.join(p, f))
        elif os.path.isfile(p):
            images.append(p)
        else:
            print(f"Warning: '{p}' not found, skipping")
    return images


def main():
    parser = argparse.ArgumentParser(
        description='Viral Edit Video Generator — Premium Edition',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python generate_video.py -v clip.mp4 -i bg1.jpg bg2.jpg bg3.jpg
  python generate_video.py -v clip.mp4 -i ./backgrounds/ -o result.mp4
  python generate_video.py -v clip.mp4 -i ./backgrounds/ --freeze 2.0 --seed 123
""")
    parser.add_argument('-v', '--video', required=True, help='Foreground video file')
    parser.add_argument('-i', '--images', required=True, nargs='+',
                        help='Background images (files and/or a directory)')
    parser.add_argument('-o', '--output', default='output.mp4', help='Output video path')
    parser.add_argument('--freeze', type=float, default=None,
                        help=f'Freeze frame time in seconds (default: {FREEZE_TIME})')
    parser.add_argument('--duration', type=float, default=None,
                        help='Output video duration in seconds (default: full video length)')
    parser.add_argument('--seed', type=int, default=42, help='Random seed for reproducibility')
    args = parser.parse_args()

    if not os.path.exists(args.video):
        print(f"Error: video not found: {args.video}")
        sys.exit(1)

    if not HAS_REMBG:
        print("Error: rembg is required for background removal.")
        print("  pip install rembg")
        sys.exit(1)

    images = collect_images(args.images)
    if not images:
        print("Error: no valid background images found")
        sys.exit(1)

    print(f"Video:  {args.video}")
    print(f"Images: {len(images)} files")
    print(f"Freeze: {args.freeze or FREEZE_TIME}s")
    if args.duration:
        print(f"Duration: {args.duration}s")
    print(f"Output: {args.output}\n")

    generate(args.video, images, args.output, args.freeze, args.duration, args.seed)


if __name__ == '__main__':
    main()
