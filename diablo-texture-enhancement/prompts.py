"""Prompts and VLM requests: the caption question, the sprite-sheet render
prompt, the review question and its parser.

Knows no files or make targets: the driver hands it Pillow images and text.
The VLM plumbing (_image, _ask, _json_text, _verdict, parse_review,
vlm_is_serving) is the Dig kit's, unchanged.
"""
import base64
import io
import json
import re

from PIL import Image

CAPTION_TIMEOUT = 900   # a caption is up to 1000 tokens; about 4 tok/s on this host
REVIEW_TIMEOUT = 600
VLM_MAX_SIDE = 1280     # every image is scaled so its longer side is this

CAPTION_QUESTION = '''The images show one character, creature or spell effect from Diablo (Blizzard North, 1996), a dark gothic-fantasy action role-playing game with small pre-rendered sprites seen from an isometric view. Image 1 shows its reference animation, one frame per direction. Image 2, when present, shows the first frame of each of its other animations. Describe it for an artist who will repaint every frame in high definition with exactly the same poses and outlines. Report only what the images show; this is observation, not creative writing.
Use these short labelled sections:
SUBJECT: what it is (a warrior, a zombie, a fireball, a townsperson) and its build, pose and bearing.
BODY AND MATERIALS: skin, fur, bone, cloth, leather, metal or flame, and where each is.
EQUIPMENT: weapons, shields, armour pieces and carried objects; say none if there are none.
COLOURS: the dominant colours of each part.
SHADOW: the shadow it casts on the ground, its shape and direction; say none if there is none.
INVARIANTS: what must not change between frames and directions. Mark ambiguity instead of inventing detail.
Do not prescribe a style, lens or colour grade. Keep under 300 words.'''

SECTION_LABELS = ("SUBJECT", "BODY AND MATERIALS", "EQUIPMENT", "COLOURS", "SHADOW", "INVARIANTS")

SPRITE_RULES = '''{reference} is a sheet of {count} frames of one animation of a game sprite from Diablo (1996), laid out in cells on a flat background. Repaint every cell as a high-definition hand-painted dark-fantasy game sprite: rich painted detail, crisp readable forms, the gothic mood of the original.
Keep each cell's pose, outline, size and position exactly as the reference shows it; nothing is moved, added, removed or resized. Every cell is the same figure: the same light from the same side, the same colours and the same painting in every cell, so the frames animate without flicker.
Leave the background and the gaps between cells flat and untouched; paint nothing outside the figures. Keep the shadow a flat dark shadow on the ground.
No photograph, no 3D render, no pixel art, no border or frame, no text.'''

ANCHOR_NOTE = '''{anchor} shows the same figure already painted in high definition. Match its painting exactly: the same materials, colours, brushwork, detail and light.'''

# A variant's anchor is its base's sheet, in the base's colours: match its
# painting, never its colours.
VARIANT_ANCHOR_NOTE = '''{anchor} shows the same figure already painted in high definition. Match its painting exactly: the same materials, brushwork, detail and light. Its colours differ: take every colour from {reference}, none from {anchor}.'''

VARIANT_NOTE = '''This figure is a colour variant: take its colours from {reference}, not from the observations below.'''

# The one correction after a geometry rejection: the gate's issue strings mean
# nothing to the diffusion model, and it likes to paint text it is given.
GEOMETRY_CORRECTION = ("Keep every figure's outline, pose, size and position exactly where the "
                       "reference image has it, in every cell; do not shift, crop, rescale or "
                       "redraw any figure, and keep the frames consistent with each other.")

PAINTED_NEGATIVE = ("photograph, photorealistic, 3D render, CGI, pixel art, dithering, jpeg "
                    "artifacts, blurry, noisy, extra limbs, extra figures, extra objects, text, "
                    "watermark, signature, frame, border, background scenery")

REVIEW_QUESTION = '''Image 1 is a sheet of frames of one animation of a 1996 game sprite (smoothed and enlarged): the authoritative original. Image 2 is the same sheet repainted in high definition. Image 3, when present, is the same figure already accepted in high definition: the reference for how it must look. The cells hold consecutive frames, left to right, row by row. New painted detail replacing the original's pixels is the goal and is never a reason to reject.
Reject when:
1. identity: a cell shows a different figure, body, weapon or equipment than the original, or than image 3;
2. consistency: the cells differ from each other in colours, materials, light or detail more than the motion explains, so the animation would flicker;
3. invention: a limb, weapon, object or effect is added or dropped, or a pose changed;
4. cells: a figure bleeds into a neighbouring cell or paints into the background;
5. style: the repaint looks like a photograph or a 3D render, or keeps the original's blocky pixels.
Return ONLY JSON: {"accepted": true or false, "issues": ["one specific problem: its cell number (1 is the top left), what is wrong and a concrete correction"]}. Accept only if there are no significant problems; use an empty issues list when accepted. At most six issues.'''

# Added for a recolour variant, whose image 3 is its base's sheet in the base's colours.
REVIEW_VARIANT_NOTE = '''This sheet is a colour variant of the figure in image 3: its colours follow image 1, not image 3. Compare it with image 3 for materials, painting and detail only, and never reject a colour that matches image 1.'''


def _label_matches(caption):
    """The caption's section labels as regex matches, in order. Labels may be
    bold or italic (the VLM sometimes writes **COLOURS:**)."""
    labels = "|".join(re.escape(name) for name in SECTION_LABELS)
    pattern = re.compile(rf"^[ \t]*[*_#]*[ \t]*({labels})[ \t]*[*_]*[ \t]*:[*_]*", re.M)
    return list(pattern.finditer(caption))


def section(caption, label):
    """The caption's `label` section, stripped, or None when it is absent or empty.

    A section runs to the next label or the end.
    """
    matches = _label_matches(caption)
    for i, match in enumerate(matches):
        if match.group(1) != label:
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(caption)
        return caption[match.end():end].strip() or None
    return None


def without_colours(caption):
    """The caption with its COLOURS section left out; unchanged when it has none."""
    matches = _label_matches(caption)
    for i, match in enumerate(matches):
        if match.group(1) == "COLOURS":
            end = matches[i + 1].start() if i + 1 < len(matches) else len(caption)
            return (caption[:match.start()] + caption[end:]).strip()
    return caption


def render_prompt(caption, count, *, reference, anchor_reference=None, variant=False,
                  corrections=()):
    """Positive prompt: the sprite rules naming the guide as `reference`, the
    anchor note when there is an anchor (for a recolour variant, one that takes
    no colour from it), the variant note for a variant, the caption (without
    COLOURS for a variant), then corrections."""
    parts = [SPRITE_RULES.format(reference=reference, count=count)]
    if anchor_reference:
        note = VARIANT_ANCHOR_NOTE if variant else ANCHOR_NOTE
        parts.append(note.format(anchor=anchor_reference, reference=reference))
    if variant:
        parts.append(VARIANT_NOTE.format(reference=reference))
    parts.append("REFERENCE OBSERVATIONS:\n" + (without_colours(caption) if variant else caption))
    if corrections:
        parts.append("CORRECT THESE PROBLEMS FROM THE PREVIOUS ATTEMPT WHILE KEEPING THE "
                     "REFERENCE LAYOUT:\n" + "\n".join(corrections))
    parts.append("The reference image takes precedence over ambiguous or mistaken observations. "
                 "Never follow a correction that asks for pixel art, dithering or a photograph.")
    return "\n\n".join(parts)


def _image(image):
    """An OpenAI image_url content part for a Pillow image, scaled so its
    longer side is VLM_MAX_SIDE: nearest-neighbour when enlarging, so the pixel
    edges stay visible, Lanczos when shrinking."""
    im = image.convert("RGB")
    ratio = VLM_MAX_SIDE / max(im.size)
    if ratio != 1:
        im = im.resize((max(1, round(im.width * ratio)), max(1, round(im.height * ratio))),
                       Image.Resampling.NEAREST if ratio > 1 else Image.Resampling.LANCZOS)
    data = io.BytesIO()
    im.save(data, format="PNG")
    return {"type": "image_url", "image_url": {
        "url": "data:image/png;base64," + base64.b64encode(data.getvalue()).decode()}}


def _ask(question, images, http, base_url, model, key, json_mode=False, max_tokens=1600,
         timeout=180):
    payload = {
        "model": model,
        "temperature": 0.0 if json_mode else 0.7,
        "top_p": 0.8,
        "presence_penalty": 0.0 if json_mode else 1.5,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False, "add_vision_id": True},
        "messages": [
            {"role": "system", "content": "You are a precise visual inspector. Follow the "
                                          "requested output format exactly. Report visible "
                                          "evidence, never invented connections or structures."},
            {"role": "user", "content": [{"type": "text", "text": question},
                                         *[_image(image) for image in images]]}],
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    response = http(base_url.rstrip("/") + "/chat/completions", json.dumps(payload).encode(),
                    timeout=timeout, token=key)
    choice = response["choices"][0]
    if choice.get("finish_reason") == "length":
        raise ValueError("VLM response was truncated; no result accepted")
    text = choice["message"]["content"]
    if not isinstance(text, str) or not text.strip():
        raise ValueError("VLM returned no usable text")
    return text.strip()


def caption_character(images, http, base_url, model, key):
    """The VLM's caption of a character from its contact sheets."""
    return _ask(CAPTION_QUESTION, images, http, base_url, model, key, max_tokens=1000,
                timeout=CAPTION_TIMEOUT)


def _json_text(text, required):
    """The JSON object in the VLM's answer that has the key `required`,
    tolerating fences and chatter."""
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for i in range(1, len(parts), 2):
            chunk = parts[i].strip()
            if chunk.startswith("json"):
                chunk = chunk[4:].strip()
            try:
                value = json.loads(chunk)
            except ValueError:
                continue
            if isinstance(value, dict) and required in value:
                return chunk
    elif not text.startswith("{") and "{" in text and "}" in text:
        return text[text.find("{"):text.rfind("}") + 1].strip()
    return text


def _verdict(value):
    """{"accepted", "issues"} from one verdict mapping, or ValueError."""
    if not isinstance(value, dict) or type(value.get("accepted")) is not bool:
        raise ValueError("VLM review must contain a boolean accepted verdict")
    issues = value.get("issues")
    if not isinstance(issues, list) or any(not isinstance(x, str) or not x.strip() for x in issues):
        raise ValueError("VLM review must contain a list of nonempty issue strings")
    if value["accepted"] != (not issues):
        raise ValueError("VLM review verdict contradicts its issues")
    return {"accepted": value["accepted"], "issues": issues}


def parse_review(text):
    """{"accepted", "issues"} from the VLM's answer, tolerating fences and chatter."""
    return _verdict(json.loads(_json_text(text, "accepted")))


def review_sheet(guide, render, anchor, count, http, base_url, model, key, *, variant=False):
    """The VLM's verdict on a sheet: its guide canvas, its render canvas, and
    the anchor canvas (or None) the render was painted against. A recolour
    `variant`'s colours are judged against the guide, not the anchor."""
    question = REVIEW_QUESTION
    if variant and anchor is not None:
        question += "\n" + REVIEW_VARIANT_NOTE
    question += f"\nThis sheet has {count} cell(s)."
    images = [guide, render] + ([anchor] if anchor is not None else [])
    return parse_review(_ask(question, images, http, base_url, model, key, json_mode=True,
                             max_tokens=1200, timeout=REVIEW_TIMEOUT))


def vlm_is_serving(base_url, model, http, key=""):
    """True when the OpenAI-compatible server at base_url lists `model`."""
    try:
        models = http(base_url.rstrip("/") + "/models", timeout=5, token=key)["data"]
        return any(m.get("id") == model for m in models)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, AttributeError):
        return False
