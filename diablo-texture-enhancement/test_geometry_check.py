import unittest

import numpy as np
from PIL import Image

import geometry_check as gc

GREY = (128, 128, 128)


def figure(x, w=40, h=32, seed=0):
    """A native RGB frame: 2-px random colour squares in a 16x20 block at x,
    over grey, and its mask."""
    rng = np.random.default_rng(seed)
    out = np.empty((h, w, 3), np.uint8)
    out[:] = GREY
    block = np.kron(rng.integers(0, 256, (10, 8, 3)), np.ones((2, 2, 1))).astype(np.uint8)
    out[6:26, x:x + 16] = block
    mask = np.zeros((h, w), bool)
    mask[6:26, x:x + 16] = True
    return Image.fromarray(out), mask


class FrameTests(unittest.TestCase):
    def test_a_perfect_frame_passes_and_a_shifted_one_fails(self):
        source, mask = figure(10)
        self.assertEqual(gc.check_frame(source, source, mask, "d0/f000.png"),
                         gc.FrameResult((0.0, 0.0), 1.0, ()))
        moved, _ = figure(12)
        result = gc.check_frame(moved, source, mask, "d0/f000.png")
        self.assertAlmostEqual(result.shift[0], 2.0, delta=0.1)
        self.assertIn("geometry: d0/f000.png is shifted +2.0,+0.0 px", result.issues)

    def test_the_edge_measure_ignores_the_locked_outline(self):
        source, mask = figure(10)
        flat = np.asarray(source).copy()
        flat[mask] = flat[mask].mean(axis=0).astype(np.uint8)      # a blob: interior lost
        result = gc.check_frame(Image.fromarray(flat), source, mask, "f")
        self.assertLess(result.agreement, gc.MIN_EDGE_AGREEMENT)
        tiny = np.zeros_like(mask)
        tiny[6:9, 10:13] = True
        self.assertEqual(gc.check_frame(Image.fromarray(flat), source, tiny, "f"),
                         gc.FrameResult((0.0, 0.0), 1.0, ()),
                         msg="too few pixels and edges to judge")


class SheetTests(unittest.TestCase):
    def items(self, renders):
        sources = [figure(10 + i) for i in range(len(renders))]
        return [(f"d0/f{i:03d}.png", 0, render, sources[i][0], sources[i][1])
                for i, render in enumerate(renders)]

    def test_consistency_flags_the_frame_that_flickers(self):
        still, mask = figure(10)                                   # an idle: the source never moves
        items = lambda renders: [(f"d0/f{i:03d}.png", 0, render, still, mask)
                                 for i, render in enumerate(renders)]
        self.assertTrue(gc.check_sheet(items([still] * 3)).passed)
        other = figure(10, seed=9)[0]                              # frame 1 repainted differently
        result = gc.check_sheet(items([still, other, still]))
        labels = [issue.split(" to ")[0] for issue in result.issues
                  if issue.startswith("consistency")]
        self.assertEqual(labels, ["consistency: d0/f000.png", "consistency: d0/f001.png"])

    def test_pairs_across_directions_or_sizes_are_not_compared(self):
        a, mask = figure(10)
        b = figure(10, seed=9)[0]
        c = Image.new("RGB", (41, 32), GREY)
        items = [("a", 0, a, a, mask), ("b", 1, b, b, mask),
                 ("c", 1, c, c, np.zeros((32, 41), bool))]
        self.assertEqual(gc.check_sheet(items).flicker, ())

    def test_gutter_bleed_is_measured_but_never_an_issue(self):
        canvas = Image.new("RGB", (64, 64), (160, 128, 128))
        gutters = np.ones((64, 64), bool)
        result = gc.check_sheet([], canvas, gutters, GREY)
        self.assertAlmostEqual(result.bleed, 32 / 3)
        self.assertTrue(result.passed)


if __name__ == "__main__":
    unittest.main()
