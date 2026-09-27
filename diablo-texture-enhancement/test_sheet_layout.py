import unittest

import numpy as np
from PIL import Image

import sheet_layout as sl
import source_tree
import testkit

GREY = sl.BACKGROUNDS["grey"]


def mask_at(x0, y0, x1, y1, w=32, h=24):
    mask = np.zeros((h, w), bool)
    mask[y0:y1, x0:x1] = True
    return mask


def rgba(mask, colour=(200, 40, 40)):
    out = np.zeros(mask.shape + (4,), np.uint8)
    out[mask] = colour + (255,)
    return Image.fromarray(out, "RGBA")


def cell_rect(cell):
    """The cell's footprint on the canvas: box at SCALE plus the margin."""
    bw = sl.SCALE * (cell.box[2] - cell.box[0])
    bh = sl.SCALE * (cell.box[3] - cell.box[1])
    x, y = cell.at
    return (x - sl.CELL_MARGIN, y - sl.CELL_MARGIN, x + bw + sl.CELL_MARGIN,
            y + bh + sl.CELL_MARGIN)


class PlanTests(unittest.TestCase):
    def frames(self, groups=2, per_group=4):
        return [(g, mask_at(4 + i, 4, 18 + i, 20)) for g in range(groups) for i in range(per_group)]

    def test_direction_packing_gives_each_direction_its_own_aligned_sheet(self):
        sheets = sl.plan_sheets(self.frames(), "direction", gutter=16)
        self.assertEqual([(s.label, s.groups) for s in sheets], [("s01", (0,)), ("s02", (1,))])
        self.assertEqual([c.frame for c in sheets[1].cells], [4, 5, 6, 7])
        for sheet in sheets:
            w, h = sheet.size
            self.assertEqual((w % sl.ALIGN, h % sl.ALIGN), (0, 0))
            self.assertEqual({c.box for c in sheet.cells}, {(4, 4, 21, 20)},
                             msg="one union box per direction")
            rects = [cell_rect(c) for c in sheet.cells]
            for k, (x0, y0, x1, y1) in enumerate(rects):
                self.assertTrue(x0 >= 16 and y0 >= 16 and x1 <= w - 16 and y1 <= h - 16,
                                msg="a gutter at the canvas edge")
                for other in rects[k + 1:]:
                    apart = (x1 + 16 <= other[0] or other[2] + 16 <= x0
                             or y1 + 16 <= other[1] or other[3] + 16 <= y0)
                    self.assertTrue(apart, msg="cells never overlap and keep the gutter")

    def test_packed_stacks_directions_until_the_canvas_limit(self):
        small = sl.plan_sheets(self.frames(groups=8), "packed")
        self.assertEqual([s.groups for s in small], [tuple(range(8))])
        self.assertLessEqual(small[0].size[0] * small[0].size[1], sl.MAX_CANVAS_PX)
        big = [(g, mask_at(0, 0, 200, 156, 200, 156)) for g in range(3) for _ in range(16)]
        sheets = sl.plan_sheets(big, "packed")
        self.assertEqual([s.groups for s in sheets], [(0,), (1,), (2,)],
                         msg="a direction larger than the limit gets a sheet of its own")
        self.assertGreater(sheets[0].size[0] * sheets[0].size[1], sl.MAX_CANVAS_PX)

    def test_an_empty_direction_still_gets_cells(self):
        empty = np.zeros((24, 32), bool)
        sheets = sl.plan_sheets([(0, empty), (0, empty)])
        self.assertEqual([c.box for c in sheets[0].cells], [(0, 0, 1, 1)] * 2)


class RoundTripTests(unittest.TestCase):
    def test_a_guide_canvas_cut_back_gives_each_frame_its_guide(self):
        masks = [mask_at(4 + i, 4, 18 + i, 20) for i in range(3)]
        rng = np.random.default_rng(0)
        frames = []
        for mask in masks:
            pixels = np.zeros((24, 32, 4), np.uint8)
            pixels[..., :3] = rng.integers(0, 256, (24, 32, 3))
            pixels[..., 3] = np.where(mask, 255, 0)
            frames.append(Image.fromarray(pixels, "RGBA"))
        guides = [sl.guide_frame(f, GREY) for f in frames]
        sheet = sl.plan_sheets([(0, m) for m in masks])[0]
        canvas = sl.guide_canvas(sheet, guides, GREY)
        for cell in sheet.cells:
            with self.subTest(frame=cell.frame):
                cut = sl.frame_rgb(canvas, cell, (32, 24), GREY)
                self.assertEqual(cut.tobytes(), guides[cell.frame].tobytes())
        self.assertTrue((np.asarray(canvas)[sl.gutter_mask(sheet)] == GREY).all(),
                        msg="the gutters are the flat background")


class AlphaTests(unittest.TestCase):
    def test_soft_alpha_only_touches_one_hd_pixel_around_the_hard_edge(self):
        mask = mask_at(8, 6, 20, 16)
        hard = sl.hard_alpha(mask).astype(int)
        soft = sl.soft_alpha(mask).astype(int)
        self.assertEqual(soft.shape, (48, 64))
        partial = (soft > 0) & (soft < 255)
        near = np.zeros_like(partial)
        edge = np.abs(np.diff(hard, axis=0, prepend=hard[:1])) + np.abs(
            np.diff(hard, axis=1, prepend=hard[:, :1]))
        ys, xs = np.nonzero(edge)
        for y, x in zip(ys, xs):
            near[max(0, y - 2):y + 2, max(0, x - 2):x + 2] = True
        self.assertTrue(partial.any())
        self.assertFalse((partial & ~near).any(), msg="nothing soft away from the edge")
        self.assertTrue(((soft == 255) == ((hard == 255) & ~partial)).all())

    def test_finish_frame_colours_the_edge_from_the_figure_not_the_background(self):
        mask = mask_at(8, 6, 20, 16)
        rgb = np.zeros((48, 64, 3), np.uint8)
        rgb[:] = GREY
        rgb[sl.hard_alpha(mask) > 0] = (200, 40, 40)
        out = np.asarray(sl.finish_frame(Image.fromarray(rgb), mask))
        alpha = out[..., 3]
        np.testing.assert_array_equal(alpha, sl.soft_alpha(mask))
        self.assertTrue((out[alpha > 0][:, :3] == (200, 40, 40)).all())
        self.assertEqual(int(out[alpha == 0].max()), 0)

    def test_keep_shadow_paints_the_sources_pure_black_pixels_black(self):
        mask = mask_at(8, 6, 20, 16)
        frame = np.asarray(rgba(mask)).copy()
        frame[12:16, 8:14, :3] = 0                      # a black ground shadow
        painted = Image.new("RGB", (64, 48), (90, 90, 90))
        out = np.asarray(sl.keep_shadow(painted, Image.fromarray(frame, "RGBA")))
        shadow = np.zeros((48, 64), bool)
        shadow[24:32, 16:28] = True
        self.assertTrue((out[shadow] == 0).all())
        self.assertTrue((out[~shadow] == 90).all(), msg="transparent black is not shadow")

    def test_an_empty_frame_comes_out_fully_transparent(self):
        empty = np.zeros((24, 32), bool)
        out = np.asarray(sl.finish_frame(Image.new("RGB", (64, 48), GREY), empty))
        self.assertEqual((out.shape, int(out.max())), ((48, 64, 4), 0))


@testkit.needs_real_corpus
class RealCorpusTests(unittest.TestCase):
    def test_every_real_animation_lays_out(self):
        source = source_tree.load(testkit.REAL_SRC)
        count, largest = 0, (0, None, None)
        for anim in source.animations:
            masks = [source_tree.frame_pixels(testkit.REAL_SRC, anim, f)[1] for f in anim.frames]
            sheets = sl.plan_sheets([(f.group, m) for f, m in zip(anim.frames, masks)])
            self.assertEqual(sorted(c.frame for s in sheets for c in s.cells),
                             list(range(len(anim.frames))), msg=anim.key)
            count += len(sheets)
            for sheet in sheets:
                area = sheet.size[0] * sheet.size[1]
                if area > largest[0]:
                    largest = (area, sheet.size, anim.key)
        self.assertEqual(count, 11394)
        self.assertEqual(largest[1:], ((1952, 1440), "monsters/nkr/nkrd.cl2"))


if __name__ == "__main__":
    unittest.main()
