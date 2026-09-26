import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import comfy_client


class FakeComfy:
    """Answers /prompt, /history and /interrupt like ComfyUI, saving one render.
    `staged` is what the input folder held when the prompt was queued."""

    def __init__(self, comfy_dir, status="success", history=True):
        self.comfy_dir, self.status, self.history, self.calls = comfy_dir, status, history, []
        self.staged = None

    def __call__(self, url, data=None, timeout=60, token=None):
        self.calls.append((url, json.loads(data) if data else None))
        if url.endswith("/prompt"):
            self.staged = sorted(p.name for p in (self.comfy_dir / "input").iterdir())
            return {"prompt_id": "p1"}
        if url.endswith("/interrupt"):
            return {}
        if "/history/" in url:
            if not self.history:
                return {}
            prefix = self.calls[0][1]["prompt"]["15"]["inputs"]["filename_prefix"]
            folder, stem = prefix.split("/")
            out = self.comfy_dir / "output" / folder
            out.mkdir(parents=True, exist_ok=True)
            name = f"{stem}_00001_.png"
            Image.new("RGB", (32, 32)).save(out / name)
            return {"p1": {"status": {"status_str": self.status, "messages": ["boom"]},
                           "outputs": {"15": {"images": [{"filename": name, "subfolder": folder,
                                                          "type": "output"}]}}}}
        raise AssertionError(f"unexpected request {url}")


def links(prompt):
    return [(node_id, value[0]) for node_id, node in prompt.items()
            for value in node["inputs"].values()
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)]


class TemplateTests(unittest.TestCase):
    def test_each_record_matches_its_template(self):
        self.assertIn(comfy_client.DEFAULT_WORKFLOW, comfy_client.WORKFLOWS)
        for name, wf in comfy_client.WORKFLOWS.items():
            with self.subTest(name):
                prompt = comfy_client.load_template(wf)
                for node, key in (wf.guide, wf.anchor, wf.anchor_input, wf.positive,
                                  wf.negative, wf.seed):
                    self.assertIn(key, prompt[node]["inputs"])
                self.assertEqual(prompt[wf.guide[0]]["class_type"], "LoadImage")
                self.assertEqual(prompt[wf.anchor[0]]["class_type"], "LoadImage")
                self.assertEqual(prompt[wf.anchor_input[0]]["inputs"][wf.anchor_input[1]],
                                 [wf.anchor[0], 0])
                # The 2.1 encoder's autogrow slots: a flat "image_1" key kills the render.
                self.assertEqual(prompt["9"]["inputs"]["images.image_1"], [wf.guide[0], 0])
                for _folder, node, key in wf.model_files:
                    self.assertIn(key, prompt[node]["inputs"])
                classes = {node["class_type"] for node in prompt.values()}
                self.assertTrue(set(wf.node_classes) <= classes)
                sampler = prompt[wf.seed[0]]
                encode = prompt[sampler["inputs"]["latent_image"][0]]
                self.assertEqual((encode["class_type"], encode["inputs"]["pixels"]),
                                 ("VAEEncode", [wf.guide[0], 0]))
                self.assertEqual(prompt[wf.save]["class_type"], "SaveImage")
                for node_id, target in links(prompt):
                    self.assertIn(target, prompt, f"node {node_id} links to {target}")

    def test_the_fallback_is_the_template_at_denoise_0_9(self):
        full = comfy_client.WORKFLOWS["qwen-image-2.1-i2i"]
        faithful = comfy_client.WORKFLOWS[full.fallback]
        expected = comfy_client.load_template(full)
        self.assertEqual(expected["13"]["inputs"]["denoise"], 1.0)
        expected["13"]["inputs"]["denoise"] = 0.9
        self.assertEqual(comfy_client.load_template(faithful), expected)
        self.assertIsNone(faithful.fallback)


class RenderSheetTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.comfy_dir = Path(tmp.name) / "comfy"
        self.inputs = Path(tmp.name) / "in"
        self.inputs.mkdir()
        for part in ("guide", "anchor"):
            Image.new("RGB", (32, 32)).save(self.inputs / f"{part}.png")

    def render(self, anchor=True, http=None, timeout=60, sleep=lambda s: None):
        http = http or FakeComfy(self.comfy_dir)
        path = comfy_client.render_sheet(
            comfy_client.WORKFLOWS["qwen-image-2.1-i2i"], guide=self.inputs / "guide.png",
            anchor=self.inputs / "anchor.png" if anchor else None, positive="paint it",
            negative="no photo", seed=43, name="monsters+zombie+zombiew.cl2+s01_a1-sheet",
            url="http://c", comfy_dir=self.comfy_dir, http=http, timeout=timeout, sleep=sleep)
        return path, http

    def test_render_sheet_fills_the_graph(self):
        path, http = self.render()
        name = "monsters+zombie+zombiew.cl2+s01_a1-sheet"
        self.assertEqual(path, self.comfy_dir / "output" / "dia" / f"{name}_00001_.png")
        prompt = http.calls[0][1]["prompt"]
        for node, part in (("1", "guide"), ("2", "anchor")):
            self.assertEqual(prompt[node]["inputs"]["image"], f"__dia_{name}_{part}.png")
        self.assertEqual(http.staged, [f"__dia_{name}_anchor.png", f"__dia_{name}_guide.png"])
        self.assertEqual(list((self.comfy_dir / "input").iterdir()), [],
                         msg="the staged inputs are removed once the render is over")
        inputs = prompt["9"]["inputs"]
        self.assertEqual((inputs["prompt"], inputs["negative_prompt"]), ("paint it", "no photo"))
        self.assertEqual(prompt["13"]["inputs"]["seed"], 43)
        self.assertEqual(prompt["15"]["inputs"]["filename_prefix"], f"dia/{name}")

    def test_without_an_anchor_the_second_reference_is_removed(self):
        _, http = self.render(anchor=False)
        prompt = http.calls[0][1]["prompt"]
        self.assertNotIn("2", prompt)
        self.assertNotIn("images.image_2", prompt["9"]["inputs"])
        self.assertEqual([t for _, t in links(prompt) if t not in prompt], [])

    def test_failures_and_interrupts(self):
        with self.subTest("a failed execution"):
            with self.assertRaisesRegex(RuntimeError, "ComfyUI execution failed"):
                self.render(http=FakeComfy(self.comfy_dir, status="error"))
        with self.subTest("a timeout interrupts the prompt"):
            http = FakeComfy(self.comfy_dir, history=False)
            with self.assertRaises(TimeoutError):
                self.render(http=http, timeout=0)
            self.assertEqual(http.calls[-1], ("http://c/interrupt", {"prompt_id": "p1"}))

        def ctrl_c(seconds):
            raise KeyboardInterrupt
        with self.subTest("Ctrl-C interrupts the prompt"):
            http = FakeComfy(self.comfy_dir, history=False)
            with self.assertRaises(KeyboardInterrupt):
                self.render(http=http, sleep=ctrl_c)
            self.assertEqual(http.calls[-1], ("http://c/interrupt", {"prompt_id": "p1"}))
        self.assertEqual(list((self.comfy_dir / "input").iterdir()), [],
                         msg="a failed render removes its staged inputs too")


class PreflightTests(unittest.TestCase):
    def test_missing_model_files_and_nodes(self):
        wf = comfy_client.WORKFLOWS["qwen-image-2.1-i2i"]
        with tempfile.TemporaryDirectory() as tmp:
            missing = comfy_client.missing_model_files(wf, tmp)
            self.assertEqual(missing, ["models/diffusion_models/qwen_image_2.1_bf16.safetensors",
                                       "models/text_encoders/qwen3vl_8b_bf16.safetensors",
                                       "models/vae/qwen_image_2.1_vae_bf16.safetensors"])

        def http(url, timeout=60):
            raise RuntimeError("HTTP 500")
        self.assertEqual(comfy_client.missing_nodes(wf, "http://c", http),
                         ["TextEncodeQwenImage21"])

    def test_is_up_and_free(self):
        calls = []

        def http(url, data=None, timeout=60):
            calls.append((url, data))
            return {}
        self.assertTrue(comfy_client.is_up("http://c", http))
        comfy_client.free_models("http://c", http)
        self.assertEqual(calls[-1], ("http://c/free",
                                     b'{"unload_models": true, "free_memory": true}'))


class SweepTests(unittest.TestCase):
    def test_sweep_removes_only_the_sheets_own_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "output" / "dia"
            out.mkdir(parents=True)
            name = comfy_client.comfy_name("monsters/zombie/zombiew.cl2/s01")
            self.assertEqual(name, "monsters+zombie+zombiew.cl2+s01")
            for file in (f"{name}_a1-sheet_00001_.png", f"{name}_a3-sheet_00002_.png",
                         "monsters+zombie+zombiew.cl2+@trn+monsters+zombie+grey.trn+s01"
                         "_a1-sheet_00001_.png",
                         "monsters+zombie+zombiew.cl2+s02_a1-sheet_00001_.png"):
                (out / file).touch()
            self.assertEqual(comfy_client.sweep_outputs(name, tmp), 2)
            self.assertEqual(len(list(out.iterdir())), 2)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(comfy_client.sweep_outputs(name, tmp), 0)


if __name__ == "__main__":
    unittest.main()
