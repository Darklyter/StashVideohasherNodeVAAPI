# helpers/phash_generator.py
#
# Pure-Python perceptual hash implementation.
# Matches the goimagehash PerceptionHash algorithm used by Stash.
#
# compute_phash(video_path) returns {"phash": "<16-char hex>"}
#
# Algorithm:
#   1. Extract 25 frames (5×5 grid): offset=5%, window=90%, evenly spaced
#   2. Each frame scaled to 160px wide (FRAME_WIDTH), aspect-ratio preserved
#   3. Assemble into a 5×5 sprite grid
#   4. Resize sprite to 64×64 using nfnt/resize bilinear (integer arithmetic)
#   5. Convert to grayscale via Go float64 luma: 0.299R + 0.587G + 0.114B
#   6. Separable 2D DCT-II (unnormalised — matches goimagehash DCT2DFast64)
#   7. Top-left 8×8 block (64 low-frequency coefficients)
#   8. Median threshold → 64-bit hash, MSB-first
#   9. Return as 16-character lowercase hex string
#
# Resize note: PIL bilinear diverges from nfnt/resize (used by goimagehash) because
# nfnt uses integer truncation for coefficients (int16(kernel*256)) and integer
# division for the final pixel value, while PIL uses float arithmetic throughout.
# The _nfnt_resize_bilinear() function reimplements the exact nfnt arithmetic.
#
# VAAPI note: accelerates hardware decode + scale for the 25 frame extractions.
# Gains are modest (no encode step in phash) but worthwhile on HEVC/high-bitrate
# content where decode is the bottleneck.  Falls back to software automatically.

import math
import os
import subprocess
import threading

import numpy as np
from PIL import Image
from scipy.fft import dct

import config
from helpers import ffmpeg_utils

# ─────────────────────────────────────────────
# Constants (must match goimagehash PerceptionHash)
# ─────────────────────────────────────────────
COLUMNS     = 5
ROWS        = 5
FRAME_COUNT = COLUMNS * ROWS   # 25
FRAME_WIDTH = 160               # px — screenshotSize in Go source
HASH_SIZE   = 8                 # 8×8 = 64-bit output
FRAME_HEIGHT_EXPR = '-2'        # scale height: even, as the videohashes binary / Stash use (scale=160:-2)


# ─────────────────────────────────────────────
# nfnt/resize bilinear reimplementation
# ─────────────────────────────────────────────

def _nfnt_resize_bilinear(img_pil, dst_w, dst_h):
    """
    Reimplements nfnt/resize Bilinear — the library used by goimagehash.

    Critical differences from PIL bilinear:
      - Coefficients:  int16(linear(x) * 256) — integer truncation, not rounding
      - Accumulation:  int32(coeff) * int32(pixel), summed in int32
      - Final pixel:   int32_acc // int32_sum (integer division) then clampUint8
      - Separable:     horizontal pass (output transposed) → vertical pass

    Mirrors createWeights8 / resizeNRGBA in nfnt/resize converter.go.
    Alpha premultiplication is omitted — video frames are always fully opaque.
    """
    src = np.array(img_pil.convert('RGB'), dtype=np.uint8)

    def _weights(src_len, dst_len):
        scale = src_len / dst_len
        flen  = 2 * max(int(math.ceil(scale)), 1)
        ff    = min(1.0 / scale, 1.0)

        coeffs  = np.zeros((dst_len, flen), dtype=np.int16)
        offsets = np.zeros(dst_len, dtype=np.int32)

        for y in range(dst_len):
            ix = scale * (y + 0.5) - 0.5
            offsets[y] = int(ix) - flen // 2 + 1
            ix -= float(offsets[y])
            for i in range(flen):
                v = abs((ix - i) * ff)
                coeffs[y, i] = int(max(0.0, 1.0 - v) * 256.0)

        return coeffs, offsets, flen

    def _pass(arr, dst_len):
        h, w   = arr.shape[:2]
        coeffs, offsets, flen = _weights(w, dst_len)

        src_idx  = np.clip(
            offsets[:, None] + np.arange(flen, dtype=np.int32)[None, :],
            0, w - 1
        )
        gathered = arr[:, src_idx, :].astype(np.int32)   # (h, dst_len, flen, 3)
        c32      = coeffs.astype(np.int32)                # (dst_len, flen)
        acc      = (gathered * c32[None, :, :, None]).sum(axis=2)  # (h, dst_len, 3)
        total    = c32.sum(axis=1)                        # (dst_len,)
        result   = np.clip(acc // total[None, :, None], 0, 255).astype(np.uint8)
        return result.transpose(1, 0, 2)                  # (dst_len, h, 3)

    temp = _pass(src, dst_w)    # (dst_w, src_h, 3)
    return _pass(temp, dst_h)   # (dst_h, dst_w, 3)


# ─────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────

def _get_duration(video_path):
    """Return video duration in seconds via ffprobe."""
    return ffmpeg_utils.probe_duration(video_path)


def _frame_command(video_path, timestamp, output, vaapi_device=None):
    if vaapi_device:
        return [config.ffmpeg,
                '-vaapi_device', vaapi_device,
                '-hwaccel', 'vaapi',
                '-hwaccel_output_format', 'vaapi',
                '-ss', f'{timestamp:.6f}',
                '-i', video_path,
                '-frames:v', '1',
                '-vf', f'scale_vaapi={FRAME_WIDTH}:{FRAME_HEIGHT_EXPR},hwdownload,format=bgr0',
                '-y', '-loglevel', 'error',
                output]
    return [config.ffmpeg,
            '-ss', f'{timestamp:.6f}',
            '-i', video_path,
            '-frames:v', '1',
            '-vf', f'scale={FRAME_WIDTH}:{FRAME_HEIGHT_EXPR}',
            '-y', '-loglevel', 'error',
            output]


def _extract_frame(video_path, timestamp, vaapi_device=None):
    """
    Extract one frame at `timestamp` (VAAPI decode when a device is given,
    software otherwise). Returns a PIL Image; raises on failure.
    """
    tmp = ffmpeg_utils.tmp_path(f'phash_{os.getpid()}_{threading.get_ident()}.bmp')
    try:
        ffmpeg_utils.run(_frame_command(video_path, timestamp, tmp, vaapi_device), timeout=60)
        with Image.open(tmp) as img:
            return img.copy()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(
            f"ffmpeg frame extraction failed at {timestamp:.1f}s: {ffmpeg_utils.error_detail(e)}"
        ) from e
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _build_sprite(video_path, duration, vaapi_device=None):
    """
    Extract FRAME_COUNT frames and assemble into a COLUMNS×ROWS sprite grid.
    Returns a PIL Image.
    """
    offset    = 0.05 * duration
    step_size = (0.90 * duration) / FRAME_COUNT

    frames = []
    for i in range(FRAME_COUNT):
        ts = offset + i * step_size
        if vaapi_device:
            try:
                frames.append(_extract_frame(video_path, ts, vaapi_device=vaapi_device))
                continue
            except Exception:
                # VAAPI decode may fail for unsupported codecs (e.g. AV1, VP9 on
                # older drivers) — use software for the rest of this video.
                vaapi_device = None
        frames.append(_extract_frame(video_path, ts))

    frame_w = frames[0].width
    frame_h = frames[0].height
    sprite  = Image.new('RGB', (COLUMNS * frame_w, ROWS * frame_h))

    for i, frame in enumerate(frames):
        if frame.width != frame_w or frame.height != frame_h:
            frame = frame.resize((frame_w, frame_h), Image.BILINEAR)
        sprite.paste(frame, ((i % COLUMNS) * frame_w, (i // COLUMNS) * frame_h))

    return sprite


def _phash_from_sprite(sprite):
    """
    Compute 64-bit DCT perceptual hash from sprite. Returns 16-char hex string.

    Resize:      nfnt/resize bilinear (exact integer arithmetic)
    Grayscale:   Go float64 luma: 0.299R + 0.587G + 0.114B
    DCT:         separable 2D DCT-II, unnormalised (goimagehash DCT2DFast64)
    Threshold:   median of top-left 8×8 DCT block
    """
    # Resize via nfnt bilinear reimplementation
    resized_arr = _nfnt_resize_bilinear(sprite, 64, 64)  # (64, 64, 3) uint8

    # Go float64 grayscale — matches goimagehash Rgb2GrayFast
    rgb    = resized_arr.astype(np.float64)
    pixels = 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]

    # Separable 2D DCT-II, unnormalised
    dct_2d = dct(dct(pixels, type=2, axis=1, norm=None), type=2, axis=0, norm=None)
    flat   = dct_2d[:HASH_SIZE, :HASH_SIZE].flatten()
    median = np.median(flat)

    hash_val = 0
    for idx, coeff in enumerate(flat):
        if coeff > median:
            hash_val |= (1 << (63 - idx))

    return f'{hash_val:016x}'


# ─────────────────────────────────────────────
# Public interface
# ─────────────────────────────────────────────

def compute_phash(video_path, vaapi_device=None):
    """
    Compute the perceptual hash of a video file.

    Args:
        video_path:   Absolute path to the video file.
        vaapi_device: VAAPI device path (e.g. '/dev/dri/renderD128'), or None
                      for software decode.  Pass the value returned by
                      vaapi_available() from the main script.

    Returns:
        dict: {"phash": "<16-char lowercase hex>"}

    Raises:
        Exception on ffprobe/ffmpeg failure or unreadable file.
    """
    duration = _get_duration(video_path)
    if duration <= 0:
        raise RuntimeError(f"Invalid video duration ({duration}s) for {video_path}")
    sprite   = _build_sprite(video_path, duration, vaapi_device=vaapi_device)
    phash    = _phash_from_sprite(sprite)
    return {"phash": phash}


