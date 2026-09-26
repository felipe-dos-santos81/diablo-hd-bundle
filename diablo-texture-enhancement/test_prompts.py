import json
import unittest

from PIL import Image

import prompts

CAPTION = ("**SUBJECT:** a rotting zombie\nBODY AND MATERIALS: grey flesh, torn rags\n"
           "COLOURS: green-grey skin, brown rags\nSHADOW: a dark blot to the lower left\n"
           "INVARIANTS: arms forward")


class RenderPromptTests(unittest.TestCase):
    def test_a_base_sheet_with_an_anchor_and_corrections(self):
        text = prompts.render_prompt(CAPTION, 16, reference="<image1>",
                                     anchor_reference="<image2>",
                                     corrections=["cell 3 lost its left arm"])
        self.assertTrue(text.startswith("<image1> is a sheet of 16 frames"))
        self.assertIn("<image2> shows the same figure already painted", text)
        self.assertIn("REFERENCE OBSERVATIONS:\n" + CAPTION, text)
        self.assertIn("PREVIOUS ATTEMPT WHILE KEEPING THE REFERENCE LAYOUT:\ncell 3 lost its left "
                      "arm", text)
        self.assertNotIn("colour variant", text)

    def test_a_variant_drops_the_caption_colours(self):
        text = prompts.render_prompt(CAPTION, 4, reference="<image1>", variant=True)
        self.assertIn("take its colours from <image1>", text)
        self.assertNotIn("green-grey", text)
        self.assertIn("SHADOW: a dark blot", text)
        self.assertNotIn("already painted", text, msg="no anchor, no anchor note")

    def test_sections(self):
        self.assertEqual(prompts.section(CAPTION, "SUBJECT"), "a rotting zombie")
        self.assertEqual(prompts.section(CAPTION, "EQUIPMENT"), None)
        self.assertEqual(prompts.without_colours("SUBJECT: x"), "SUBJECT: x")


class ReviewTests(unittest.TestCase):
    def test_parse_review_tolerates_fences_and_refuses_contradictions(self):
        self.assertEqual(prompts.parse_review('```json\n{"accepted": false, "issues": ["cell 2"]}'
                                              '\n```'),
                         {"accepted": False, "issues": ["cell 2"]})
        for text in ('{"accepted": true, "issues": ["x"]}', '{"accepted": "yes", "issues": []}'):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    prompts.parse_review(text)

    def test_review_sheet_sends_guide_render_and_anchor(self):
        sent = {}

        def http(url, data=None, timeout=60, token=None):
            sent.update(json.loads(data))
            return {"choices": [{"finish_reason": "stop", "message": {
                "content": '{"accepted": true, "issues": []}'}}]}
        image = Image.new("RGB", (64, 32))
        verdict = prompts.review_sheet(image, image, image, 12, http, "http://v/v1", "m", "")
        self.assertEqual(verdict, {"accepted": True, "issues": []})
        content = sent["messages"][1]["content"]
        self.assertTrue(content[0]["text"].endswith("This sheet has 12 cell(s)."))
        self.assertEqual(len(content), 4, msg="question, guide, render, anchor")


if __name__ == "__main__":
    unittest.main()
