"""The deterministic check of a rendered sheet's frames against their sources.

The gate before promotion. Every frame is compared at native size: the
render's frame (colour-matched, box-downscaled from SCALE) against the source
frame over the flat background. Numpy maths on Pillow images and arrays;
knows no files, animations or audit tree.

Each measure has one job:
- phase correlation finds a figure that slid (a 1-pixel shift reads as 1.0);
- edge agreement, inside the outline (the mask eroded by 1 px, so the locked
  outline cannot inflate it), finds lost or moved inner structure; it has
  the Atlantis hysteresis (a source edge is strong above EDGE_THRESHOLD and
  kept by a render edge above RENDER_EDGE_THRESHOLD within 1 px);
- consistency finds a frame that changes far more from its neighbour than
  the source does (flicker): the render's mean absolute step between
  consecutive frames of a direction, over the pixels opaque in both, against
  the source's;
- gutter bleed (a warning) finds a model that painted outside the cells.

The starting values are the Atlantis gate's where one exists; the spike
recalibrates every one of them for sprites (AGENTS.md).
"""
from dataclasses import dataclass

import numpy as np

MAX_SHIFT = 0.5             # native px
EDGE_THRESHOLD = 80.0       # Sobel magnitude on 0-255 luminance of a strong source edge
RENDER_EDGE_THRESHOLD = 60.0
MIN_EDGE_AGREEMENT = 0.80
MIN_SHIFT_PIXELS = 200      # a frame with fewer opaque native px is too small to measure a shift
MIN_CELL_EDGES = 30         # a frame with fewer strong interior source edges reads 1.0
FLICKER_FACTOR = 2.0        # a pair fails when render step > FACTOR * source step + FLOOR
FLICKER_FLOOR = 10.0        # levels (0-255, mean over RGB); painted cells shimmer ~8-10
GUTTER_WARN = 12.0          # levels of mean |pixel - background| over all the gutters


def luminance(image):
    return np.asarray(image.convert("L"), dtype=np.float64)


def phase_shift(a, b):
    """(dx, dy) by which luminance array `b` is displaced from `a`, sub-pixel.

    Phase correlation under a Hann window, refined by a parabola through the
    peak. A flat array has no position to measure and reads as (0, 0).
    """
    if a.std() < 1 or b.std() < 1:
        return (0.0, 0.0)
    h, w = a.shape
    window = np.outer(np.hanning(h), np.hanning(w))
    fa = np.fft.fft2((a - a.mean()) * window)
    fb = np.fft.fft2((b - b.mean()) * window)
    cross = fb * np.conj(fa)
    cross /= np.abs(cross) + 1e-9
    corr = np.fft.ifft2(cross).real
    py, px = np.unravel_index(np.argmax(corr), corr.shape)

    def refine(before, peak, after):
        denominator = before - 2 * peak + after
        return 0.0 if denominator == 0 else 0.5 * (before - after) / denominator

    dy = py + refine(corr[(py - 1) % h, px], corr[py, px], corr[(py + 1) % h, px])
    dx = px + refine(corr[py, (px - 1) % w], corr[py, px], corr[py, (px + 1) % w])
    if dy > h / 2:
        dy -= h
    if dx > w / 2:
        dx -= w
    return (round(float(dx), 3) + 0.0, round(float(dy), 3) + 0.0)


def sobel(lum):
    """The Sobel gradient magnitude of the 2-D array `lum`, at its own size;
    edge pixels are repeated at the border."""
    p = np.pad(lum, 1, mode="edge")
    gx = (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])
    gy = (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])
    return np.hypot(gx, gy)


def _grow(mask):
    """`mask` grown by one pixel in every direction."""
    p = np.pad(mask, 1)
    out = np.zeros_like(mask)
    for dy in range(3):
        for dx in range(3):
            out |= p[dy:dy + mask.shape[0], dx:dx + mask.shape[1]]
    return out


def erode(mask):
    """`mask` shrunk by one pixel in every direction."""
    return ~_grow(~mask)


def edge_maps(source, render):
    """(strong, kept): the source's strong edge pixels, and those of them with a
    render edge within 1 px. Arrays are native-size luminance."""
    strong = sobel(source) > EDGE_THRESHOLD
    return strong, strong & _grow(sobel(render) > RENDER_EDGE_THRESHOLD)


@dataclass(frozen=True)
class FrameResult:
    shift: tuple        # (dx, dy), native px
    agreement: float    # interior edge agreement; 1.0 when too sparse to judge
    issues: tuple


def check_frame(render, source, mask, label):
    """Compare one frame: `render` and `source` native RGB images of the same
    size (the source over the flat background), `mask` its native opacity.
    `label` names the frame in the issue strings."""
    small, base = luminance(render), luminance(source)
    issues = []
    shift = (0.0, 0.0)
    if int(mask.sum()) >= MIN_SHIFT_PIXELS:
        shift = phase_shift(base, small)
        if max(abs(shift[0]), abs(shift[1])) >= MAX_SHIFT:
            issues.append(f"geometry: {label} is shifted {shift[0]:+.1f},{shift[1]:+.1f} px")
    strong, kept = edge_maps(base, small)
    inside = erode(mask)
    strong, kept = strong & inside, kept & inside
    count = int(strong.sum())
    agreement = 1.0 if count < MIN_CELL_EDGES else round(float(kept.sum() / count), 4)
    if agreement < MIN_EDGE_AGREEMENT:
        issues.append(f"geometry: {label} edge agreement {agreement:.2f}, needs "
                      f"{MIN_EDGE_AGREEMENT:.2f}")
    return FrameResult(shift, agreement, tuple(issues))


def step(a, b, both):
    """Mean absolute RGB difference of native images `a` and `b` over the bool
    array `both`; 0.0 when it marks nothing."""
    if not both.any():
        return 0.0
    diff = np.abs(np.asarray(a, np.float64) - np.asarray(b, np.float64))
    return float(diff[both].mean())


@dataclass(frozen=True)
class SheetResult:
    frames: tuple       # FrameResult per checked frame, in order
    flicker: tuple      # (label, render step, source step) per consecutive pair of a direction
    bleed: float        # the gutters' mean distance from the background, levels
    issues: tuple

    @property
    def passed(self):
        return not self.issues

    def as_dict(self):
        return {"passed": self.passed,
                "frames": [{"shift": list(f.shift), "agreement": f.agreement}
                           for f in self.frames],
                "flicker": [[label, round(r, 2), round(s, 2)] for label, r, s in self.flicker],
                "bleed": round(self.bleed, 2), "issues": list(self.issues)}


def check_sheet(items, canvas=None, gutters=None, background=None):
    """Check every frame of a sheet. `items` is [(label, group, render, source,
    mask), ...] in frame order: render and source native RGB images, mask the
    native bool opacity. With the rendered `canvas`, its `gutters` (bool) and the
    `background` colour, the gutter bleed is measured too (a warning, never an
    issue)."""
    frames, issues, flicker = [], [], []
    for label, _group, render, source, mask in items:
        result = check_frame(render, source, mask, label)
        frames.append(result)
        issues.extend(result.issues)
    for (label, group, render, source, mask), (_, next_group, r2, s2, m2) in zip(items, items[1:]):
        if group != next_group or render.size != r2.size:
            continue
        both = mask & m2
        rendered, original = step(render, r2, both), step(source, s2, both)
        flicker.append((label, rendered, original))
        if rendered > FLICKER_FACTOR * original + FLICKER_FLOOR:
            issues.append(f"consistency: {label} to the next frame changes {rendered:.1f} levels, "
                          f"the source {original:.1f}")
    bleed = 0.0
    if canvas is not None and gutters is not None and gutters.any():
        pixels = np.asarray(canvas.convert("RGB"), np.float64)[gutters]
        bleed = float(np.abs(pixels - np.array(background, np.float64)).mean())
    return SheetResult(tuple(frames), tuple(flicker), bleed, tuple(issues))
