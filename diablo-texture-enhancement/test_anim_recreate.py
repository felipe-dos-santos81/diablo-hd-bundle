import json
import random
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

import anim_recreate as a
import comfy_client
import sheet_layout
import source_tree
import testkit
from characters_file import Character, load_characters, load_reviews, save_characters

ZN, ZW = "monsters/zombie/zombien.cl2", "monsters/zombie/zombiew.cl2"
GREY = f"@trn/{testkit.GREY_TRN}"
# Every sheet of the miniature source, in the order batch renders them: the
# anchors of the characters in key order, the other base animations, the variants.
ORDER = ["missiles/fireba1.cl2/s01", f"{ZN}/s01", f"{ZN}/s02", "missiles/fireba2.cl2/s01",
         f"{ZW}/s01", f"{ZW}/s02", f"{ZN}/{GREY}/s01", f"{ZN}/{GREY}/s02",
         f"{ZW}/{GREY}/s01", f"{ZW}/{GREY}/s02"]


def mark_corner(image):
    """A render that differs from the guide by one gutter pixel: a new canvas
    that still passes every check."""
    image.putpixel((0, 0), (0, 0, 0))
    return image


class DriverTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.src = testkit.make_source(self.root)
        self.dst = self.root / "dst"
        self.chars = self.root / "characters.yaml"
        self.reviews = self.root / "reviews.yaml"
        self.comfy = self.root / "comfy"
        testkit.write_characters(self.chars, self.src)

    def argv(self, command, *extra):
        return [command, "--src", str(self.src), "--dst", str(self.dst), "--characters-file",
                str(self.chars), "--reviews", str(self.reviews), *extra]

    def batch(self, *extra, render=None):
        with testkit.comfy_stub(comfy_dir=self.comfy,
                                render=render or testkit.fake_render()) as mocks:
            code, out, err = testkit.run_cli(self.argv("batch", *extra))
        return code, out, err, mocks

    def record(self, key, attempt):
        return json.loads((self.dst / ".quality" / key / f"attempt-{attempt}.json").read_text())


class BatchTests(DriverTest):
    def test_batch_renders_anchors_first_and_promotes_every_frame(self):
        code, out, err, mocks = self.batch()
        self.assertEqual(code, 0, err)
        names = [c.kwargs["name"] for c in mocks.render.call_args_list]
        self.assertEqual(names, [comfy_client.comfy_name(k) + "_a1-sheet" for k in ORDER])
        anchors = {k: (self.record(k, 1)["anchor"] or {}).get("key") for k in ORDER}
        self.assertEqual(anchors, {
            f"{ZN}/s01": None, f"{ZN}/s02": f"{ZN}/s01", "missiles/fireba1.cl2/s01": None,
            f"{ZW}/s01": f"{ZN}/s01", f"{ZW}/s02": f"{ZN}/s01",
            "missiles/fireba2.cl2/s01": "missiles/fireba1.cl2/s01",
            f"{ZN}/{GREY}/s01": f"{ZN}/s01", f"{ZN}/{GREY}/s02": f"{ZN}/s02",
            f"{ZW}/{GREY}/s01": f"{ZW}/s01", f"{ZW}/{GREY}/s02": f"{ZW}/s02"})
        calls = {c.kwargs["name"]: c.kwargs for c in mocks.render.call_args_list}
        self.assertIsNone(calls[f"{comfy_client.comfy_name(ZN)}+s01_a1-sheet"]["anchor"])
        self.assertTrue(str(calls[f"{comfy_client.comfy_name(ZN)}+s02_a1-sheet"]["anchor"])
                        .endswith("sheet.anchor.png"))
        prompt = mocks.render.call_args_list[6].kwargs["positive"]
        self.assertIn("colour variant", prompt)
        self.assertNotIn("red and blue", prompt, msg="a variant drops the caption's COLOURS")
        source = source_tree.load(self.src)
        for key in (ZN, ZW, f"{ZN}/{GREY}"):
            anim = source.animation(key.split("/@trn/")[0])
            for frame in anim.frames:
                with Image.open(self.dst / key / frame.png) as im:
                    self.assertEqual((im.size, im.mode), ((64, 48), "RGBA"))
        self.assertIn("done: promoted=10 rejected=0 failed=0 done=0 blocked=0", out)
        mocks.freed.assert_called_once()
        code, out, _, mocks = self.batch()
        self.assertEqual((code, mocks.render.call_count), (0, 0), msg="a second batch is a no-op")
        self.assertIn("done=10", out)

    def test_a_shifted_anchor_is_rejected_and_its_dependants_wait(self):
        code, out, _, mocks = self.batch("--character", "monsters/zombie",
                                         render=testkit.fake_render(testkit.shift_right))
        self.assertEqual(code, 0)
        self.assertEqual(mocks.render.call_count, 1)
        self.assertIn("rejected=1", out)
        self.assertIn("blocked=7", out)
        review = load_reviews(self.reviews)[f"{ZN}/s01"]
        self.assertEqual((review.attempt, review.source), (1, "geometry"))
        self.assertTrue(any("is shifted" in issue for issue in review.issues))
        code, out, _, mocks = self.batch("--character", "monsters/zombie")
        self.assertIn(a.GEOMETRY_CORRECTION, mocks.render.call_args_list[0].kwargs["positive"])
        self.assertIn("promoted=8", out)

    def test_stuck_sheets_get_the_fallback_once_then_report_stuck(self):
        shifted = testkit.fake_render(testkit.shift_right)
        args = ("--anim", "missiles/fireba1.cl2")
        for _ in range(a.MAX_ATTEMPTS):
            self.batch(*args, render=shifted)
        code, out, _, mocks = self.batch(*args, render=shifted)
        self.assertEqual(mocks.render.call_args.args[0].name, "qwen-image-2.1-i2i-faithful")
        code, out, err, mocks = self.batch(*args, render=shifted)
        self.assertEqual((code, mocks.render.call_count), (1, 0))
        self.assertIn("STUCK   missiles/fireba1.cl2/s01", err)

    def test_a_new_anchor_makes_its_dependants_stale(self):
        self.batch()
        code, out, _, mocks = self.batch("--anim", ZN, "--no-variants", "--force",
                                         render=testkit.fake_render(mark_corner))
        self.assertEqual(mocks.render.call_count, 2)
        code, out, _, mocks = self.batch()
        rendered = [c.kwargs["name"].split("_a")[0] for c in mocks.render.call_args_list]
        self.assertEqual(rendered, [comfy_client.comfy_name(k) for k in (
            f"{ZW}/s01", f"{ZW}/s02", f"{ZN}/{GREY}/s01", f"{ZN}/{GREY}/s02")])
        self.assertIn("(its anchor changed)", out)

    def test_force_never_renders_a_dependant_whose_anchor_is_not_done(self):
        # Regression: --force rendered done dependants with anchor=None while
        # the character anchor's new attempt had just been rejected. The four
        # sheets anchored directly to it (the other zombien sheet, both
        # zombiew sheets, and zombien's own grey variant s01) must wait;
        # sheets anchored to an untouched sibling sheet may still render, but
        # never anchorless.
        self.batch("--character", "monsters/zombie")
        anchor_name = comfy_client.comfy_name(f"{ZN}/s01")

        def shift_the_anchor(workflow, **kw):
            return testkit.fake_render(testkit.shift_right if kw["name"].startswith(anchor_name + "_")
                                       else None)(workflow, **kw)
        code, out, _, mocks = self.batch("--character", "monsters/zombie", "--force",
                                         render=shift_the_anchor)
        self.assertEqual(code, 0)
        self.assertIn("rejected=1", out)
        self.assertIn("blocked=4", out)
        for call in mocks.render.call_args_list:
            if call.kwargs["name"] != f"{anchor_name}_a2-sheet":
                self.assertIsNotNone(call.kwargs["anchor"],
                                     msg=f"{call.kwargs['name']} rendered anchorless")

    def test_a_failed_render_leaves_an_error_and_no_record(self):
        def boom(workflow, **kw):
            raise RuntimeError("ComfyUI execution failed: out of memory")
        audit = self.dst / ".quality" / "missiles/fireba1.cl2/s01"
        cases = {"a ComfyUI error": (boom, "out of memory"),
                 "a render of the wrong size": (
                     testkit.fake_render(lambda im: im.resize((64, 64))), "came back 64x64")}
        for attempt, (label, (render, message)) in enumerate(cases.items(), 1):
            with self.subTest(label):
                code, out, err, mocks = self.batch("--anim", "missiles/fireba1.cl2", render=render)
                self.assertEqual(code, 1)
                self.assertIn(message, (audit / f"attempt-{attempt}.error.txt").read_text())
                self.assertFalse((audit / f"attempt-{attempt}.json").exists())
                mocks.sweep.assert_called_once_with("missiles+fireba1.cl2+s01", self.comfy)
                self.assertEqual(a.sheet_status(self.dst, "missiles/fireba1.cl2/s01", {}),
                                 ("failed", attempt))

    def test_ctrl_c_sweeps_frees_and_stops(self):
        def ctrl_c(workflow, **kw):
            raise KeyboardInterrupt
        with testkit.comfy_stub(comfy_dir=self.comfy, render=ctrl_c) as mocks:
            with self.assertRaises(KeyboardInterrupt):
                testkit.run_cli(self.argv("batch"))
        self.assertEqual(mocks.render.call_count, 1)
        mocks.sweep.assert_called_once()
        mocks.freed.assert_called_once()
        error = self.dst / ".quality" / "missiles/fireba1.cl2/s01" / "attempt-1.error.txt"
        self.assertIn("KeyboardInterrupt", error.read_text())

    def test_batch_refuses_without_comfyui_its_models_or_memory(self):
        cases = {"ComfyUI down": (dict(up=False), "not answering"),
                 "a missing model file": (dict(missing=["models/vae/x"]), "missing model files"),
                 "too little memory": (dict(mem=10.0), "stop vLLM first")}
        for label, (stub, message) in cases.items():
            with self.subTest(label):
                with testkit.comfy_stub(comfy_dir=self.comfy, render=testkit.fake_render(),
                                        **stub) as mocks:
                    code, _, err = testkit.run_cli(self.argv("batch"))
                self.assertEqual((code, mocks.render.call_count), (2, 0))
                self.assertIn(message, err)

    def test_characters_yaml_must_match_the_manifest(self):
        characters = load_characters(self.chars)
        zombie, mage = characters["monsters/zombie"], "monsters/darkmage/dmagew.cl2"
        cases = {
            "an anchor without frames": ({**characters, "monsters/zombie": Character(
                zombie.animations + (mage,), mage, zombie.caption)}, "has no frames"),
            "an animation left out": ({k: c for k, c in characters.items()
                                       if k != "missiles/fireba"}, "no character for"),
        }
        for label, (edited, message) in cases.items():
            with self.subTest(label):
                if label == "an anchor without frames":
                    del edited["monsters/darkmage"]
                save_characters(self.chars, edited)
                code, _, err, mocks = self.batch()
                self.assertEqual((code, mocks.render.call_count), (2, 0))
                self.assertIn(message, err)

    def test_skipped_animations_are_copied_with_their_variants(self):
        testkit.write_characters(self.chars, self.src, skip={"monsters/zombie": [ZW]})
        code, out, _, mocks = self.batch("--character", "monsters/zombie")
        self.assertEqual(code, 0)
        self.assertEqual(mocks.render.call_count, 4, msg="zombien and its variant only")
        with Image.open(self.dst / ZW / GREY / "d1/f003.png") as im:
            alpha = np.asarray(im.getchannel("A"))
        self.assertEqual(set(np.unique(alpha)), {0, 255}, msg="a copy keeps the hard outline")

    def test_uncaptioned_characters_stop_the_batch_but_not_the_dry_run(self):
        testkit.write_characters(self.chars, self.src, caption="")
        code, _, err, mocks = self.batch()
        self.assertEqual((code, mocks.render.call_count), (2, 0))
        self.assertIn("no caption", err)
        code, out, _, mocks = self.batch("--dry-run")
        self.assertEqual((code, mocks.render.call_count), (0, 0))
        self.assertIn(f"blocked  {ZW}/s01", out)
        self.assertIn(f"new      {ZN}/s01  3 frames", out)
        self.assertIn("no caption - run: make caption", out)
        self.assertIn("sheets: blocked=8 new=2", out)


class SelectionTests(DriverTest):
    def test_character_anim_and_variant_select_the_sheets(self):
        cases = {("--character", "missiles/fireba"): "2 sheet(s)",
                 ("--anim", ZW): "4 sheet(s)",
                 ("--anim", ZW, "--no-variants"): "2 sheet(s)",
                 ("--variant", testkit.GREY_TRN): "10 sheet(s)"}
        for extra, expected in cases.items():
            with self.subTest(extra=extra):
                code, out, _, _ = self.batch("--dry-run", *extra)
                self.assertEqual(code, 0)
                self.assertIn(expected, out)
        for extra, message in ((("--variant", "x.trn"), "no selected animation has variant x.trn"),
                               (("--character", "nobody"), "no character nobody"),
                               (("--anim", "a.cl2"), "no selected character has animation a.cl2")):
            with self.subTest(extra=extra):
                code, _, err, _ = self.batch("--dry-run", *extra)
                self.assertEqual(code, 2)
                self.assertIn(message, err)


class CaptionReviewTests(DriverTest):
    def test_caption_seeds_the_file_and_fills_blank_captions(self):
        self.chars.unlink()
        with testkit.vlm_stub(caption=lambda images, *rest: "SUBJECT: seen") as mocks:
            code, out, _ = testkit.run_cli(self.argv("caption"))
        self.assertEqual(code, 0)
        self.assertIn("seeded 3 character(s)", out)
        characters = load_characters(self.chars)
        self.assertEqual({k: c.caption for k, c in characters.items()},
                         {"missiles/fireba": "SUBJECT: seen", "monsters/darkmage": "",
                          "monsters/zombie": "SUBJECT: seen"},
                         msg="a character with no frames is not captioned")
        images = mocks.caption.call_args_list[-1].args[0]
        self.assertEqual(len(images), 2, msg="the anchor's directions, then the other animations")

    def test_review_judges_done_sheets_and_a_rejection_comes_back_as_corrections(self):
        self.batch("--character", "missiles/fireba")

        def review(guide, render, anchor, count, *rest):
            return ({"accepted": False, "issues": ["cell 2 grew a tail"]} if anchor is not None
                    else {"accepted": True, "issues": []})
        with testkit.vlm_stub(review=review, free=None):
            code, out, _ = testkit.run_cli(self.argv("review", "--concurrency", "2"))
        self.assertEqual(code, 0)
        self.assertIn("accepted=1 rejected=1", out)
        code, out, _, mocks = self.batch("--character", "missiles/fireba")
        self.assertEqual(mocks.render.call_count, 1)
        self.assertIn("cell 2 grew a tail", mocks.render.call_args.kwargs["positive"])


@testkit.needs_real_corpus
class RealCorpusTests(unittest.TestCase):
    """A perfect render (the guide canvas itself) of real animations passes every
    check: the gate never rejects a faithful sheet."""

    def test_perfect_renders_of_a_real_sample_pass(self):
        source = source_tree.load(testkit.REAL_SRC)
        sample = random.Random(7).sample([an for an in source.animations if an.frames], 50)
        background = sheet_layout.BACKGROUNDS[sheet_layout.BACKGROUND]
        args = type("Args", (), {"src": testkit.REAL_SRC})()
        failures = []
        for anim in sample:
            masks = [source_tree.frame_pixels(testkit.REAL_SRC, anim, f)[1] for f in anim.frames]
            sheets = sheet_layout.plan_sheets([(f.group, m) for f, m in zip(anim.frames, masks)])
            for sheet in sheets:
                sj = a.SheetJob(a.Job(anim, None, "x"), sheet)
                frames, guides, canvas = a.sheet_inputs(args, sj, background)
                _, result = a.finish_sheet(canvas, sheet, anim, frames, guides,
                                           a.DEFAULT_MATCH_STRENGTH, background)
                if not result.passed:
                    failures.append((sj.key, result.issues[:2]))
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
