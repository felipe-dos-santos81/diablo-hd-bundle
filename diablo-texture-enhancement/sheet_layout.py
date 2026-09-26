"""Lay an animation's frames out on sheets, and cut a rendered sheet back into frames.

A sheet is one canvas the model repaints in one pass. Every direction (group)
gets one cell size: the union of its frames' opaque boxes at SCALE, plus
CELL_MARGIN on each side. Cells sit on a grid with `gutter` pixels between
them and at the canvas edge; the canvas sides are multiples of ALIGN, the
rest filled with the background. A direction is never split across sheets.

The outline is locked: a frame's alpha is its source mask at SCALE,
nearest-neighbour, softened only within 1 HD pixel of its edge
(`soft_alpha`). A pixel with partial alpha takes the colour of the nearest
fully opaque pixel, so the background never tints the outline.

Pure image maths on numpy arrays and Pillow images; knows no files or services.
"""
import math
from dataclasses import dataclass

import numpy as np
from PIL import Image

SCALE = 2
CELL_MARGIN = 8                 # HD px of context around a direction's union box
GUTTER = 16                     # HD px between cells and at the canvas edge
ALIGN = 32                      # canvas sides are multiples of this (Qwen 2.1 resolution 0)
MAX_CANVAS_PX = 1_048_576       # a packed sheet stays at or under this many pixels
PACKINGS = ("direction", "packed")
SHEET_PACKING = "direction"     # one direction per sheet, or several up to MAX_CANVAS_PX
BACKGROUNDS = {"grey": (128, 128, 128), "dark": (24, 24, 24)}
BACKGROUND = "grey"
GUIDE_FILL_RINGS = 4             # native px of fill under the Lanczos kernel (radius 3)
EDGE_FILL_RINGS = 2              # HD px: every partly transparent pixel is within 2 of an opaque one


@dataclass(frozen=True)
class Cell:
    frame: int          # index into the animation's frames
    box: tuple          # (x0, y0, x1, y1): the direction's union box, native frame px
    at: tuple           # (x, y): where the box's top-left lands on the canvas, HD px


@dataclass(frozen=True)
class Sheet:
    number: int         # 1-based, in direction order
    groups: tuple       # the directions it holds
    size: tuple         # (width, height), HD px, multiples of ALIGN
    cells: tuple        # Cell, in frame order

    @property
    def label(self):
        return f"s{self.number:02d}"


def union_box(masks):
    """(x0, y0, x1, y1) around every opaque pixel of `masks`; (0, 0, 1, 1)
    when none has one (an empty direction still gets a cell)."""
    boxes = []
    for mask in masks:
        ys, xs = np.nonzero(mask)
        if xs.size:
            boxes.append((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    if not boxes:
        return (0, 0, 1, 1)
    return (int(min(b[0] for b in boxes)), int(min(b[1] for b in boxes)),
            int(max(b[2] for b in boxes)), int(max(b[3] for b in boxes)))


def _align(n):
    return -(-n // ALIGN) * ALIGN


def _block(frames, box, gutter):
    """(cells relative to the block, width, height) of one direction: a grid of
    about square shape, `gutter` px above and left of each cell."""
    bw, bh = SCALE * (box[2] - box[0]), SCALE * (box[3] - box[1])
    cw, ch = bw + 2 * CELL_MARGIN, bh + 2 * CELL_MARGIN
    n = len(frames)
    cols = max(1, min(n, math.ceil(math.sqrt(n * ch / cw))))
    rows = -(-n // cols)
    cells = [(index, (gutter + (k % cols) * (cw + gutter) + CELL_MARGIN,
                      gutter + (k // cols) * (ch + gutter) + CELL_MARGIN))
             for k, index in enumerate(frames)]
    return cells, cols * (cw + gutter), rows * (ch + gutter)


def plan_sheets(frames, packing=SHEET_PACKING, gutter=GUTTER):
    """The sheets of one animation. `frames` is [(group, mask), ...] in the
    animation's frame order, mask a native (h, w) bool array. `packing` is
    "direction" (one sheet per direction) or "packed" (consecutive directions
    stacked while the canvas stays within MAX_CANVAS_PX; a direction that alone
    exceeds it gets a sheet that fits it)."""
    if packing not in PACKINGS:
        raise ValueError(f"packing must be one of {', '.join(PACKINGS)}, got {packing!r}")
    groups = {}
    for index, (group, mask) in enumerate(frames):
        groups.setdefault(group, []).append((index, mask))
    blocks = []
    for group in sorted(groups):
        members = groups[group]
        box = union_box([mask for _, mask in members])
        cells, width, height = _block([index for index, _ in members], box, gutter)
        blocks.append((group, box, cells, width, height))

    sheets, current = [], []

    def size(parts):
        return (_align(max(p[3] for p in parts) + gutter),
                _align(sum(p[4] for p in parts) + gutter))

    def close():
        if not current:
            return
        cells, y = [], 0
        for _, box, block_cells, _, height in current:
            cells.extend(Cell(index, box, (x, y + by)) for index, (x, by) in block_cells)
            y += height
        sheets.append(Sheet(len(sheets) + 1, tuple(p[0] for p in current), size(current),
                            tuple(sorted(cells, key=lambda c: c.frame))))
        current.clear()

    for block in blocks:
        if current and (packing == "direction"
                        or math.prod(size(current + [block])) > MAX_CANVAS_PX):
            close()
        current.append(block)
    close()
    return tuple(sheets)


def frame_region(cell, size):
    """(x0, y0, x1, y1): the part of the frame at SCALE, in HD frame px, that
    the cell holds: its box grown by CELL_MARGIN, clipped to the frame. `size`
    is the native (w, h)."""
    x0, y0, x1, y1 = cell.box
    return (max(0, SCALE * x0 - CELL_MARGIN), max(0, SCALE * y0 - CELL_MARGIN),
            min(SCALE * size[0], SCALE * x1 + CELL_MARGIN),
            min(SCALE * size[1], SCALE * y1 + CELL_MARGIN))


def _canvas_origin(cell):
    """Where the frame's HD origin (0, 0) lands on the canvas."""
    return cell.at[0] - SCALE * cell.box[0], cell.at[1] - SCALE * cell.box[1]


def gutter_mask(sheet):
    """(H, W) bool: the canvas pixels outside every cell (box plus margin)."""
    w, h = sheet.size
    out = np.ones((h, w), bool)
    for cell in sheet.cells:
        bw = SCALE * (cell.box[2] - cell.box[0])
        bh = SCALE * (cell.box[3] - cell.box[1])
        x, y = cell.at
        out[max(0, y - CELL_MARGIN):y + bh + CELL_MARGIN,
            max(0, x - CELL_MARGIN):x + bw + CELL_MARGIN] = False
    return out


def fill_transparent(rgb, known, rings=None):
    """`rgb` ((h, w, 3) uint8) with each pixel `known` does not mark set to the
    mean of its known 8-neighbours, ring by ring outward, for at most `rings`
    rings (all when None). A pixel no ring reaches keeps its own colour.
    Returns a new array."""
    out = rgb.astype(np.float64).copy()
    known = known.copy()
    h, w = known.shape
    done = 0
    while not known.all() and (rings is None or done < rings):
        total = np.zeros_like(out)
        count = np.zeros((h, w))
        pv = np.pad(out * known[..., None], ((1, 1), (1, 1), (0, 0)))
        pk = np.pad(known, 1).astype(np.float64)
        for dy in range(3):
            for dx in range(3):
                total += pv[dy:dy + h, dx:dx + w]
                count += pk[dy:dy + h, dx:dx + w]
        grow = ~known & (count > 0)
        if not grow.any():
            break
        out[grow] = total[grow] / count[grow][:, None]
        known = known | grow
        done += 1
    return np.round(out).astype(np.uint8)


def hard_alpha(mask):
    """(2h, 2w) uint8: the native bool `mask` at SCALE, nearest-neighbour, 0 or 255."""
    return np.kron(mask.astype(np.uint8) * 255, np.ones((SCALE, SCALE), np.uint8))


def soft_alpha(mask):
    """(2h, 2w) uint8: hard_alpha softened by a 3x3 box, so partial alpha lies
    only within 1 HD px of the hard edge, on either side of it."""
    hard = hard_alpha(mask).astype(np.float64)
    h, w = hard.shape
    p = np.pad(hard, 1)
    total = sum(p[dy:dy + h, dx:dx + w] for dy in range(3) for dx in range(3))
    return np.round(total / 9).astype(np.uint8)


def guide_frame(frame_rgba, background):
    """The frame's guide at SCALE, RGB: its colours (transparent pixels filled
    from the nearest opaque ones) upscaled with Lanczos, laid over the flat
    `background` colour through the hard mask."""
    rgba = np.asarray(frame_rgba.convert("RGBA"))
    mask = rgba[..., 3] > 0
    size = (frame_rgba.width * SCALE, frame_rgba.height * SCALE)
    big = np.asarray(Image.fromarray(fill_transparent(rgba[..., :3], mask, GUIDE_FILL_RINGS))
                     .resize(size, Image.Resampling.LANCZOS))
    out = np.empty_like(big)
    out[:] = background
    hard = hard_alpha(mask) > 0
    out[hard] = big[hard]
    return Image.fromarray(out)


def guide_native(frame_rgba, background):
    """The native frame over the flat `background` colour, RGB: what a
    render's frame, box-downscaled, is compared with."""
    rgba = np.asarray(frame_rgba.convert("RGBA"))
    out = np.empty(rgba.shape[:2] + (3,), np.uint8)
    out[:] = background
    mask = rgba[..., 3] > 0
    out[mask] = rgba[..., :3][mask]
    return Image.fromarray(out)


def guide_canvas(sheet, guides, background):
    """The sheet's guide canvas, RGB: each cell's region of its frame's guide
    (`guides[frame index]`, guide_frame images) on the flat `background`."""
    canvas = Image.new("RGB", sheet.size, background)
    for cell in sheet.cells:
        guide = guides[cell.frame]
        region = frame_region(cell, (guide.width // SCALE, guide.height // SCALE))
        ox, oy = _canvas_origin(cell)
        canvas.paste(guide.crop(region), (ox + region[0], oy + region[1]))
    return canvas


def frame_rgb(canvas, cell, size, background):
    """The frame at SCALE cut from a rendered `canvas`, RGB: the cell's region
    where it was painted, `background` elsewhere. `size` is the native (w, h)."""
    out = Image.new("RGB", (size[0] * SCALE, size[1] * SCALE), background)
    region = frame_region(cell, size)
    ox, oy = _canvas_origin(cell)
    out.paste(canvas.crop((ox + region[0], oy + region[1], ox + region[2], oy + region[3])),
              region[:2])
    return out


def finish_frame(rgb, mask):
    """The output frame, RGBA at SCALE: `rgb` under the soft outline of the
    native `mask`, each partly transparent pixel coloured from the nearest
    fully opaque one, and fully transparent pixels (0, 0, 0, 0)."""
    alpha = soft_alpha(mask)
    colours = np.asarray(rgb.convert("RGB"))
    colours = fill_transparent(colours, alpha == 255, EDGE_FILL_RINGS)
    colours[alpha == 0] = 0
    return Image.fromarray(np.dstack([colours, alpha]), "RGBA")


def nearest_frame(frame_rgba):
    """A skipped frame's output: the native RGBA frame at SCALE, nearest-neighbour."""
    return frame_rgba.convert("RGBA").resize(
        (frame_rgba.width * SCALE, frame_rgba.height * SCALE), Image.Resampling.NEAREST)
