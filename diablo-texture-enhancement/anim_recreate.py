#!/usr/bin/env python3
"""Regenerate Diablo's animated sprites as painted high-definition art at
exactly 2x, frame by frame, with the outline locked.

Human-paced stages, each a subcommand:

  caption   seed characters.yaml when it is missing, then describe every
            character with the local vLLM and write its caption
  batch     render every sheet of every selected animation through ComfyUI:
            anchors first, then the other base animations, then the recolour
            variants; colour-match, slice and check each frame; promote a
            sheet's frames when all of them pass; re-render the sheets
            reviews.yaml rejects; write skipped animations as a nearest 2x
  review    compare every promoted sheet with its guide and its anchor
            through the vLLM and write reviews.yaml
  verify    audit the output tree against the manifest, the 2x rule, the
            outline and the attempt records
  preview   write an animated GIF per direction: source and render side by side

The source tree is diablo-textures-exporter's output; its manifest.json (read by
source_tree) decides which animations exist. Services are external: vLLM
(Qwen/Qwen3.8-27B on :8000) and ComfyUI (:8188) are started by the user; this
driver only checks that they answer.
"""
import argparse
import json
import os
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from PIL import Image

import colour_match
import comfy_client
import geometry_check
import sheet_layout
import source_tree
from characters_file import (CharactersFileError, Review, check_coverage, load_characters,
                             load_reviews, save_characters, save_reviews, seed_characters)
from prompts import (GEOMETRY_CORRECTION, PAINTED_NEGATIVE, caption_character, render_prompt,
                     review_sheet, vlm_is_serving)
from source_tree import SourceError

REPO = Path(__file__).resolve().parent


def _env_path(name, default):
    return Path(os.environ.get(name) or default).expanduser()


SRC_ROOT = _env_path("DIA_SRC", REPO.parent / "diablo-textures-exporter" / "out")
DST_ROOT = _env_path("DIA_DST", REPO / "data" / "anims-ai")
PREVIEW_ROOT = _env_path("DIA_PREVIEW", REPO / "data" / "preview")
CHARACTERS_FILE = _env_path("DIA_CHARACTERS", REPO / "characters.yaml")
REVIEWS_FILE = _env_path("DIA_REVIEWS", REPO / "reviews.yaml")
COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
COMFY_DIR = _env_path("COMFY_DIR", Path.home() / "ComfyUI")
VLM_BASE_URL = os.environ.get("VLM_BASE_URL", "http://127.0.0.1:8000/v1")
VLM_MODEL = os.environ.get("VLM_MODEL", "Qwen/Qwen3.8-27B")
VLM_API_KEY = os.environ.get("VLM_API_KEY", "")
MEMORY_FLOOR_GB = 45
SEED = 42                   # attempt N of a sheet uses SEED + N - 1
MAX_ATTEMPTS = 4            # a sheet with this many rejected attempts, the latest among them, waits
MAX_CONSECUTIVE_FAILURES = 3  # batch stops after this many failed sheets in a row
DEFAULT_MATCH_STRENGTH = 0.5
DEFAULT_CONCURRENCY = 8     # review requests in flight at once
CAPTION_SCALE = 4           # the caption contact sheets enlarge frames this much
CONTACT_COLUMNS = 8
PREVIEW_BACKGROUND = (24, 24, 24)
PREVIEW_MS = 100            # GIF frame duration
SCALE = source_tree.SCALE
_ATTEMPT = re.compile(r"^attempt-(\d+)(\.|$)")


class UsageError(Exception):
    """Bad arguments or a precondition the user must fix; reported without a traceback."""


def fail(msg):
    print(f"error: {msg}", file=sys.stderr)
    return 2


def write_atomic(path, text):
    """Write `text` to `path` through <path>.tmp and a rename."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def save_image_atomic(image, path, format="PNG", **options):
    """Save `image` at `path` through <path>.pending and a rename; `options`
    go to Image.save (e.g. save_all for an animated GIF)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + ".pending")
    image.save(pending, format=format, **options)
    os.replace(pending, path)


# ---- jobs and sheets --------------------------------------------------------

@dataclass(frozen=True)
class Job:
    """One animation to regenerate: a base animation, or one recolour variant of it."""
    anim: source_tree.Animation
    trn: object             # the TRN asset path of a variant, or None
    character: str
    skip: bool = False

    @property
    def key(self):
        return self.anim.key if self.trn is None else f"{self.anim.key}/@trn/{self.trn}"


@dataclass(frozen=True)
class SheetJob:
    job: Job
    sheet: sheet_layout.Sheet

    @property
    def key(self):
        return f"{self.job.key}/{self.sheet.label}"


def load_characters_checked(args):
    """characters.yaml, checked to cover exactly the manifest's animations, with
    no anchor that lacks frames while its character has some."""
    characters = load_characters(args.characters_file)
    check_coverage(characters, [a.key for a in args.source.animations], args.characters_file)
    for key, character in characters.items():
        counts = {a: len(args.source.animation(a).frames) for a in character.animations}
        if not counts[character.anchor] and any(counts.values()):
            raise UsageError(f"{args.characters_file}: {key}'s anchor {character.anchor} has no "
                             "frames - choose an animation with frames")
    return characters


def select_jobs(args, characters):
    """The selected jobs in render order: every anchor animation, then the other
    base animations, then (unless --no-variants) the variants in the same order,
    only the --variant TRNs when given, and only the jobs of the --sheet keys
    when given."""
    names = args.character or sorted(characters)
    unknown = sorted(set(names) - set(characters))
    if unknown:
        raise UsageError("no character " + ", ".join(unknown) + f" in {args.characters_file}")
    wanted = set(args.anim or ())
    known = {a for name in names for a in characters[name].animations}
    if wanted - known:
        raise UsageError("no selected character has animation "
                         + ", ".join(sorted(wanted - known)))
    anchors, others = [], []
    for name in names:
        character = characters[name]
        for key in character.animations:
            if wanted and key not in wanted:
                continue
            job = Job(args.source.animation(key), None, name, key in character.skip)
            (anchors if key == character.anchor else others).append(job)
    bases = anchors + others
    trns = {trn for job in bases for trn in job.anim.variants}
    if args.variant and set(args.variant) - trns:
        raise UsageError("no selected animation has variant "
                         + ", ".join(sorted(set(args.variant) - trns)))
    variants = [] if args.no_variants else [
        replace(job, trn=trn) for job in bases for trn in job.anim.variants
        if not args.variant or trn in args.variant]
    jobs = bases + variants
    if args.sheet:
        # A sheet key is <job key>/sNN: keep the jobs that own one, then check
        # that each key is one of their sheets.
        owners = {key.rpartition("/")[0] for key in args.sheet}
        jobs = [job for job in jobs if job.key in owners]
        unknown = set(args.sheet) - {sj.key for sj in sheet_jobs(args, jobs)}
        if unknown:
            raise UsageError("no selected animation has sheet " + ", ".join(sorted(unknown)))
    return jobs


def layout(args, anim):
    """(sheets, masks) of an animation under the run's packing and gutter, cached."""
    cached = args.layouts.get(anim.key)
    if cached is None:
        masks = [source_tree.frame_pixels(args.src, anim, frame)[1] for frame in anim.frames]
        sheets = sheet_layout.plan_sheets([(f.group, m) for f, m in zip(anim.frames, masks)],
                                          args.packing, args.gutter)
        cached = args.layouts[anim.key] = (sheets, masks)
    return cached


def job_sheets(args, job):
    """The job's sheets, only the --sheet ones when given."""
    return [sheet for sheet in layout(args, job.anim)[0]
            if not args.sheet or SheetJob(job, sheet).key in args.sheet]


def sheet_jobs(args, jobs):
    return [SheetJob(job, sheet) for job in jobs if not job.skip for sheet in job_sheets(args, job)]


def anchor_key(sj, characters):
    """The key of the sheet `sj` is painted against, or None: a variant's base
    sheet of the same number; else the character's anchor animation's first
    sheet, except for that sheet itself."""
    if sj.job.trn is not None:
        return f"{sj.job.anim.key}/{sj.sheet.label}"
    character = characters[sj.job.character]
    if sj.job.anim.key == character.anchor and sj.sheet.number == 1:
        return None
    return f"{character.anchor}/s01"


# ---- audit folder -----------------------------------------------------------

def audit_dir(dst_root, key):
    return dst_root / ".quality" / key


def latest_attempt(audit):
    """The highest N among the audit folder's attempt-N.* entries, 0 when none.
    A failed attempt leaves attempt-N.tiles/ behind and still uses up N."""
    if not audit.is_dir():
        return 0
    return max((int(m.group(1)) for p in audit.iterdir() if (m := _ATTEMPT.match(p.name))),
               default=0)


def read_record(audit, attempt, suffix="json"):
    """attempt-N.json (or attempt-N.<suffix>, e.g. review.json) as a mapping, or
    None when it is missing or unreadable."""
    try:
        value = json.loads((audit / f"attempt-{attempt}.{suffix}").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def current_review(reviews, key, latest):
    """reviews.yaml's verdict on the sheet, or None when there is none or it is
    stale: an attempt later than the audit folder's latest."""
    review = reviews.get(key)
    return None if review is None or review.attempt > latest else review


def judged_attempts(dst, key, reviews):
    """{N: (record, rejected)} for every attempt of the sheet that has a record.
    An attempt is rejected when the gate did not promote it, or its review
    rejected it: reviews.yaml's current verdict when it is about N, else the
    attempt's own attempt-N.review.json. A promoted attempt that was only
    replaced (a stale or forced re-render) is not rejected; a failed attempt
    has no record and is not judged at all."""
    audit = audit_dir(dst, key)
    latest = latest_attempt(audit)
    review = current_review(reviews, key, latest)
    judged = {}
    for n in range(1, latest + 1):
        record = read_record(audit, n)
        if record is None:
            continue
        if review is not None and review.attempt == n:
            accepted = review.accepted
        else:
            accepted = (read_record(audit, n, "review.json") or {}).get("accepted")
        judged[n] = (record, not record.get("promoted") or accepted is False)
    return judged


def sheet_status(dst, key, reviews):
    """(status, latest attempt) of a sheet, from its audit folder alone:
    new       never attempted
    stuck     its latest judged attempt was rejected, and MAX_ATTEMPTS or more
              of its attempts were rejected
    failed    the latest attempt never finished (it has no record)
    rejected  the latest attempt failed the gate, or its review rejected it
    missing   promoted and not rejected, but a frame it wrote is gone
    done      promoted and not rejected (reviewed, or waiting for review)
    Only rejected attempts count toward STUCK (judged_attempts): never a
    failed one, nor a promoted one a stale or forced re-render replaced."""
    attempt = latest_attempt(audit_dir(dst, key))
    if attempt == 0:
        return "new", 0
    judged = judged_attempts(dst, key, reviews)
    rejections = sum(rejected for _, rejected in judged.values())
    if judged and judged[max(judged)][1] and rejections >= MAX_ATTEMPTS:
        return "stuck", attempt
    if attempt not in judged:
        return "failed", attempt
    record, rejected = judged[attempt]
    if rejected:
        return "rejected", attempt
    if any(not (dst / rel).is_file() for rel in record.get("frames", {})):
        return "missing", attempt
    return "done", attempt


def status_of(args, sj, reviews, characters):
    """(status, attempt, anchor) of a sheet, with the anchor rules on top of
    sheet_status. `anchor` is (key, canvas path, canvas sha256) of the anchor
    sheet's promoted attempt, or None when the sheet has no anchor or it is not
    done. A sheet that still needs rendering waits as `blocked` while its
    anchor is not done; a done sheet painted against another anchor canvas than
    the current one is `stale`."""
    status, attempt = sheet_status(args.dst, sj.key, reviews)
    key = None if args.no_anchor else anchor_key(sj, characters)
    if key is None:
        return status, attempt, None
    a_status, a_attempt = sheet_status(args.dst, key, reviews)
    anchor = None
    if a_status == "done":
        record = read_record(audit_dir(args.dst, key), a_attempt)
        anchor = (key, audit_dir(args.dst, key) / f"attempt-{a_attempt}.png",
                  record.get("canvas_sha256"))
    elif status != "done":
        return "blocked", attempt, None
    if status == "done" and anchor is not None:
        record = read_record(audit_dir(args.dst, sj.key), attempt)
        if (record.get("anchor") or {}).get("sha256") != anchor[2]:
            return "stale", attempt, anchor
    return status, attempt, anchor


def layout_changes(args, sj):
    """The layout fields (packing, gutter, background, canvas, groups) in which
    the sheet's latest attempt record differs from the sheet as now planned;
    empty when they agree or the sheet has no record. One output tree holds
    one layout: a switch would mix sheets of both under the same keys."""
    audit = audit_dir(args.dst, sj.key)
    record = next((r for n in range(latest_attempt(audit), 0, -1)
                   if (r := read_record(audit, n)) is not None), None)
    if record is None:
        return []
    planned = {"packing": args.packing, "gutter": args.gutter, "background": args.background,
               "canvas": list(sj.sheet.size), "groups": list(sj.sheet.groups)}
    return [field for field, value in planned.items() if record.get(field) != value]


def layout_refusal(args, mismatched):
    """The message for sheets ({key: changed fields}) rendered with another layout."""
    lines = [f"{key} ({', '.join(fields)})" for key, fields in list(mismatched.items())[:5]]
    if len(mismatched) > 5:
        lines.append(f"... and {len(mismatched) - 5} more")
    return (f"{args.dst}: this output tree was rendered with a different layout "
            f"({len(mismatched)} sheet(s)); use another dst= or restore the settings "
            "(packing=, gutter=, background=):\n  " + "\n  ".join(lines))


def corrections_for(dst, key, reviews):
    """What the sheet's next attempt must correct: the issues of its current
    review when that review rejected an attempt and no later attempt was
    promoted. After a geometry rejection it is the one GEOMETRY_CORRECTION
    sentence: the gate's own strings mean nothing to the diffusion model."""
    audit = audit_dir(dst, key)
    latest = latest_attempt(audit)
    review = current_review(reviews, key, latest)
    if review is None or review.accepted:
        return []
    if any((read_record(audit, n) or {}).get("promoted")
           for n in range(review.attempt + 1, latest + 1)):
        return []
    return [GEOMETRY_CORRECTION] if review.source == "geometry" else list(review.issues)


def fallback_for(dst, key, workflow, reviews):
    """The workflow to render a stuck sheet through once more: `workflow`'s
    fallback while no rejected attempt of the sheet (as sheet_status counts
    them) has used it; else None."""
    if workflow.fallback is None:
        return None
    used = {record.get("workflow")
            for record, rejected in judged_attempts(dst, key, reviews).values() if rejected}
    return None if workflow.fallback in used else comfy_client.WORKFLOWS[workflow.fallback]


# ---- render one sheet -------------------------------------------------------

def finish_sheet(canvas, sheet, anim, frames_rgba, guides, strength, background):
    """Cut the rendered `canvas` into its frames, colour-match each toward its
    guide over its outline, lock the outline, and check them all.
    Returns ({frame index: RGBA image at SCALE}, SheetResult)."""
    items, outputs = [], {}
    for cell in sheet.cells:
        frame = anim.frames[cell.frame]
        size = (frame.w, frame.h)
        mask = np.asarray(frames_rgba[cell.frame])[..., 3] > 0
        raw = sheet_layout.frame_rgb(canvas, cell, size, background)
        matched = colour_match.match(raw, guides[cell.frame], strength,
                                     mask=sheet_layout.hard_alpha(mask) > 0)
        items.append((frame.png, frame.group, matched.resize(size, Image.Resampling.BOX),
                      sheet_layout.guide_native(frames_rgba[cell.frame], background), mask))
        outputs[cell.frame] = sheet_layout.finish_frame(matched, mask)
    result = geometry_check.check_sheet(items, canvas, sheet_layout.gutter_mask(sheet), background)
    return outputs, result


def sheet_inputs(args, sj, background):
    """(frames_rgba, guides, guide canvas) of a sheet: each cell's native RGBA
    frame (through the job's TRN) and its guide at SCALE, keyed by frame index."""
    anim = sj.job.anim
    frames = {c.frame: source_tree.frame_rgba(args.src, anim, anim.frames[c.frame], sj.job.trn)
              for c in sj.sheet.cells}
    guides = {i: sheet_layout.guide_frame(f, background) for i, f in frames.items()}
    return frames, guides, sheet_layout.guide_canvas(sj.sheet, guides, background)


def render_sheet_job(args, workflow, sj, character, corrections, anchor):
    """Render one sheet, finish and check its frames, and promote them when
    every frame passes. Returns (attempt, SheetResult).

    Raises when the render fails or comes back the wrong size: the attempt
    number stays used, attempt-N.error.txt says what failed, and no
    attempt-N.json is written, so the attempt reads as failed.
    """
    audit = audit_dir(args.dst, sj.key)
    audit.mkdir(parents=True, exist_ok=True)
    attempt = latest_attempt(audit) + 1
    tiles = audit / f"attempt-{attempt}.tiles"
    tiles.mkdir()
    seed = SEED + attempt - 1
    started = time.monotonic()
    stage = None
    background = sheet_layout.BACKGROUNDS[args.background]
    try:
        anim = sj.job.anim
        frames_rgba, guides, canvas = sheet_inputs(args, sj, background)
        guide_path = tiles / "sheet.guide.png"
        canvas.save(guide_path)
        anchor_path = None
        if anchor is not None:
            anchor_path = tiles / "sheet.anchor.png"
            shutil.copyfile(anchor[1], anchor_path)
        positive = render_prompt(
            character.caption, len(sj.sheet.cells), reference=workflow.reference,
            anchor_reference=workflow.anchor_reference if anchor is not None else None,
            variant=sj.job.trn is not None, corrections=corrections)
        stage = "sheet"
        saved = comfy_client.render_sheet(
            workflow, guide=guide_path, anchor=anchor_path, positive=positive,
            negative=PAINTED_NEGATIVE, seed=seed,
            # The attempt in the name keeps ComfyUI's cache from answering a rerun of
            # the same inputs and seed with an old render.
            name=f"{comfy_client.comfy_name(sj.key)}_a{attempt}-sheet", url=COMFY_URL,
            comfy_dir=COMFY_DIR)
        raw = audit / f"attempt-{attempt}.png"
        shutil.move(saved, raw)
        with Image.open(raw) as im:
            rendered = im.convert("RGB")
        if rendered.size != sj.sheet.size:
            raise RuntimeError(f"the sheet came back {rendered.width}x{rendered.height}, "
                               f"expected {sj.sheet.size[0]}x{sj.sheet.size[1]}")
        stage = None
        write_atomic(audit / f"attempt-{attempt}.prompt.txt",
                     f"workflow: {workflow.name}\n\n{positive}\n\n--- negative ---\n"
                     f"{PAINTED_NEGATIVE}\n")
        outputs, result = finish_sheet(rendered, sj.sheet, anim, frames_rgba, guides,
                                       args.match_strength, background)
        if result.bleed > geometry_check.GUTTER_WARN:
            print(f"  warning: {sj.key} painted into its gutters ({result.bleed:.1f} levels from "
                  "the background)", flush=True)
        frames = {}
        if result.passed:
            for index, image in outputs.items():
                rel = f"{sj.job.key}/{anim.frames[index].png}"
                save_image_atomic(image, args.dst / rel)
                frames[rel] = source_tree.file_sha256(args.dst / rel)
        record = {
            "attempt": attempt, "workflow": workflow.name, "seed": seed,
            "packing": args.packing, "gutter": args.gutter, "background": args.background,
            "canvas": list(sj.sheet.size), "groups": list(sj.sheet.groups),
            "cells": len(sj.sheet.cells),
            "anchor": None if anchor is None else {"key": anchor[0], "sha256": anchor[2]},
            "match": {"rule": colour_match.RULE, "strength": args.match_strength},
            "geometry": result.as_dict(), "promoted": result.passed,
            "canvas_sha256": source_tree.file_sha256(raw), "frames": frames,
            "seconds": round(time.monotonic() - started, 1),
        }
        write_atomic(audit / f"attempt-{attempt}.json", json.dumps(record, indent=2))
        return attempt, result
    except BaseException as error:
        write_atomic(audit / f"attempt-{attempt}.error.txt",
                     f"workflow: {workflow.name}\nseed: {seed}\nstage: {stage or 'none'}\n"
                     f"seconds: {time.monotonic() - started:.1f}\n"
                     f"error: {type(error).__name__}: {error}\n")
        raise


# ---- batch ------------------------------------------------------------------

def memory_available_gb(meminfo=Path("/proc/meminfo")):
    """MemAvailable in GiB. On this unified-memory host it is the GPU budget too."""
    for line in meminfo.read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 2 ** 20
    raise RuntimeError(f"MemAvailable not found in {meminfo}")


def vlm_preflight():
    """None when vLLM serves VLM_MODEL; else fail(...)'s exit code."""
    if not vlm_is_serving(VLM_BASE_URL, VLM_MODEL, comfy_client.http_json, VLM_API_KEY):
        return fail(f"vLLM is not serving {VLM_MODEL} at {VLM_BASE_URL} - start it first")
    return None


def free_comfy_models():
    """Ask ComfyUI to unload its models; a warning, never an error, when it cannot."""
    try:
        comfy_client.free_models(COMFY_URL)
    except Exception as error:
        print(f"warning: failed to free ComfyUI's models: {error}", file=sys.stderr)


def comfy_preflight(workflow, no_memory_check):
    """None when ComfyUI answers, has the model files, knows the node classes
    and there is memory to render; else fail(...)'s exit code."""
    if not comfy_client.is_up(COMFY_URL):
        return fail(f"ComfyUI is not answering at {COMFY_URL} - start it first (make server)")
    missing = comfy_client.missing_model_files(workflow, COMFY_DIR)
    if missing:
        return fail(f"ComfyUI is missing model files under {COMFY_DIR}:\n  " + "\n  ".join(missing))
    unknown = comfy_client.missing_nodes(workflow, COMFY_URL)
    if unknown:
        return fail(f"ComfyUI at {COMFY_URL} does not know {', '.join(unknown)} - update the "
                    f"checkout (git -C {COMFY_DIR} pull) and restart it")
    if not no_memory_check:
        available = memory_available_gb()
        if available < MEMORY_FLOOR_GB:
            return fail(f"only {available:.0f} GB of memory available, a render needs about "
                        f"{MEMORY_FLOOR_GB} GB: stop vLLM first (or pass --no-memory-check)")
    return None


def write_nearest(args, job):
    """A skipped animation's output: every frame at SCALE, nearest-neighbour."""
    for frame in job.anim.frames:
        save_image_atomic(sheet_layout.nearest_frame(
            source_tree.frame_rgba(args.src, job.anim, frame, job.trn)),
            args.dst / job.key / frame.png)


def sweep_sheet(sj):
    """Delete the sheet's leftover ComfyUI outputs. Returns a note for its error
    line; a sweep that raises is reported there, never raised."""
    try:
        swept = comfy_client.sweep_outputs(comfy_client.comfy_name(sj.key), COMFY_DIR)
    except Exception as error:
        return f" (sweeping its outputs failed: {error})"
    return f" (removed {swept} stray output file(s))" if swept else ""


def stuck_line(sj):
    return (f"  STUCK   {sj.key}: rejected {MAX_ATTEMPTS} times - fix {sj.job.character}'s "
            f"caption in characters.yaml, then: make batch sheet={sj.key} force=1")


def cmd_batch(args):
    workflow = comfy_client.WORKFLOWS[args.workflow]
    characters = load_characters_checked(args)
    reviews = load_reviews(args.reviews, optional=True)
    jobs = select_jobs(args, characters)
    copies = [job for job in jobs if job.skip and (args.force or any(
        not (args.dst / job.key / f.png).is_file() for f in job.anim.frames))]
    items = sheet_jobs(args, jobs)
    uncaptioned = sorted({sj.job.character for sj in items
                          if not characters[sj.job.character].caption.strip()})
    mismatched = {sj.key: changes for sj in items if (changes := layout_changes(args, sj))}
    print(f"workflow: {workflow.name}  match strength: {args.match_strength}  packing: "
          f"{args.packing}  gutter: {args.gutter}  background: {args.background}"
          + ("  no anchor" if args.no_anchor else ""))
    print(f"{len(jobs)} animation(s) and variant(s): {len(items)} sheet(s), "
          f"copy {len(copies)} (skip)")
    if args.dry_run:
        return dry_run(args, items, copies, characters, reviews, uncaptioned, mismatched)
    if mismatched:
        return fail(layout_refusal(args, mismatched))
    if uncaptioned:
        return fail(f"{len(uncaptioned)} selected character(s) have no caption in "
                    f"{args.characters_file} - run: make caption\n  " + "\n  ".join(uncaptioned))
    for job in copies:
        write_nearest(args, job)
        print(f"  copy    {job.key} (nearest {SCALE}x)")
    if not items:
        return 0
    code = comfy_preflight(workflow, args.no_memory_check)
    if code is not None:
        return code
    # ComfyUI keeps its models loaded after rendering (~40 GB); free them on the
    # way out, even after a failure, so vLLM has room to start for `make review`.
    try:
        counts = dict.fromkeys(("promoted", "rejected", "failed", "done", "blocked"), 0)
        stuck = []
        failures = 0        # failed sheets in a row
        for i, sj in enumerate(items, 1):
            status, _, anchor = status_of(args, sj, reviews, characters)
            if status == "done" and not args.force:
                counts["done"] += 1
                continue
            if status == "blocked" or (anchor is None and not args.no_anchor
                                       and anchor_key(sj, characters) is not None):
                counts["blocked"] += 1
                continue
            sheet_workflow = workflow
            if status == "stuck" and not args.force:
                sheet_workflow = fallback_for(args.dst, sj.key, workflow, reviews)
                if sheet_workflow is None:
                    stuck.append(sj)
                    continue
            corrections = corrections_for(args.dst, sj.key, reviews)
            note = f" with {len(corrections)} correction(s)" if corrections else ""
            if sheet_workflow is not workflow:
                note += f" through the fallback {sheet_workflow.name}"
            if status == "stale":
                note += " (its anchor changed)"
            print(f"[{i}/{len(items)}] render {sj.key} ({len(sj.sheet.cells)} frames){note}",
                  flush=True)
            try:
                attempt, result = render_sheet_job(args, sheet_workflow, sj,
                                                   characters[sj.job.character], corrections,
                                                   anchor)
            except KeyboardInterrupt:
                sweep_sheet(sj)
                raise
            except Exception as error:
                counts["failed"] += 1
                failures += 1
                print(f"  ERROR rendering {sj.key}: {error}{sweep_sheet(sj)}", file=sys.stderr,
                      flush=True)
                # Every later sheet would fail the same way: stop, and let the
                # finally free ComfyUI's models.
                if not comfy_client.is_up(COMFY_URL):
                    print(f"ComfyUI stopped answering at {COMFY_URL} - stopping the batch",
                          file=sys.stderr, flush=True)
                    break
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    print(f"{failures} sheets failed in a row - stopping the batch; fix the "
                          "cause (see the errors above) and run it again", file=sys.stderr,
                          flush=True)
                    break
                continue
            failures = 0
            if result.passed:
                counts["promoted"] += 1
                print(f"  promoted attempt {attempt}", flush=True)
                continue
            counts["rejected"] += 1
            reviews[sj.key] = Review(attempt, False, result.issues, "geometry")
            save_reviews(args.reviews, reviews)
            print(f"  rejected attempt {attempt}: " + "; ".join(result.issues[:3])
                  + (f" (+{len(result.issues) - 3} more)" if len(result.issues) > 3 else ""),
                  flush=True)
            if sheet_status(args.dst, sj.key, reviews)[0] == "stuck":
                fallback = fallback_for(args.dst, sj.key, sheet_workflow, reviews)
                if fallback is None:
                    stuck.append(sj)
                else:
                    print(f"  next batch renders it through the fallback {fallback.name}",
                          flush=True)
        for sj in stuck:
            print(stuck_line(sj), file=sys.stderr)
        print("done: " + " ".join(f"{k}={v}" for k, v in counts.items())
              + f" copied={len(copies)} stuck={len(stuck)}")
        return 1 if counts["failed"] or stuck else 0
    finally:
        free_comfy_models()


def dry_run(args, items, copies, characters, reviews, uncaptioned, mismatched):
    """Print what batch would do: every sheet not done, with its size, anchor
    and corrections, then the counts by status. A sheet rendered with another
    layout (`mismatched`, {key: changed fields}) reads `layout`, and batch
    would refuse the run."""
    counts = {}
    for job in copies:
        print(f"  copy    {job.key} ({len(job.anim.frames)} frames, nearest {SCALE}x)")
    for sj in items:
        if sj.key in mismatched:
            counts["layout"] = counts.get("layout", 0) + 1
            print(f"  layout   {sj.key}  rendered with another {', '.join(mismatched[sj.key])}")
            continue
        status, _, _ = status_of(args, sj, reviews, characters)
        counts[status] = counts.get(status, 0) + 1
        if status == "done":
            continue
        w, h = sj.sheet.size
        extras = [f"{len(sj.sheet.cells)} frames", f"{w}x{h}"]
        key = None if args.no_anchor else anchor_key(sj, characters)
        if key:
            extras.append(f"anchor {key}")
        corrections = corrections_for(args.dst, sj.key, reviews)
        if corrections:
            extras.append(f"{len(corrections)} correction(s)")
        if sj.job.character in uncaptioned:
            extras.append("no caption - run: make caption")
        print(f"  {status:8} {sj.key}  " + "; ".join(extras))
    largest = max((sj.sheet for sj in items), key=lambda s: s.size[0] * s.size[1], default=None)
    if largest is not None:
        print(f"largest canvas: {largest.size[0]}x{largest.size[1]}")
    print("sheets: " + " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if mismatched:
        print("batch would refuse: " + layout_refusal(args, mismatched))
    return 0


# ---- caption ----------------------------------------------------------------

def contact_sheet(frames, columns=CONTACT_COLUMNS, scale=CAPTION_SCALE,
                  background=PREVIEW_BACKGROUND):
    """Native RGBA `frames` enlarged `scale` times, nearest-neighbour, on a grid
    of up to `columns` over `background`, 8 px apart."""
    cw = max(f.width for f in frames) * scale
    ch = max(f.height for f in frames) * scale
    cols = min(columns, len(frames))
    rows = -(-len(frames) // cols)
    out = Image.new("RGB", (cols * (cw + 8) + 8, rows * (ch + 8) + 8), background)
    for k, frame in enumerate(frames):
        big = frame.convert("RGBA").resize((frame.width * scale, frame.height * scale),
                                           Image.Resampling.NEAREST)
        out.paste(big, (8 + (k % cols) * (cw + 8), 8 + (k // cols) * (ch + 8)), big)
    return out


def caption_images(args, character):
    """What the VLM sees: the anchor animation's first frame in each direction,
    then the first frame of every other animation with frames."""
    anchor = args.source.animation(character.anchor)
    firsts = [f for f in anchor.frames if f.i == 0]
    images = [contact_sheet([source_tree.frame_rgba(args.src, anchor, f) for f in firsts])]
    others = [args.source.animation(k) for k in character.animations if k != character.anchor]
    others = [a for a in others if a.frames]
    if others:
        images.append(contact_sheet([source_tree.frame_rgba(args.src, a, a.frames[0])
                                     for a in others]))
    return images


def cmd_caption(args):
    if not args.characters_file.exists():
        seeded = seed_characters([(a.key, a.kind, len(a.frames)) for a in args.source.animations])
        save_characters(args.characters_file, seeded)
        print(f"seeded {len(seeded)} character(s) -> {args.characters_file}")
    characters = load_characters_checked(args)
    names = args.character or sorted(characters)
    unknown = sorted(set(names) - set(characters))
    if unknown:
        raise UsageError("no character " + ", ".join(unknown) + f" in {args.characters_file}")
    code = vlm_preflight()
    if code is not None:
        return code
    done = skipped = failed = 0
    for i, name in enumerate(names, 1):
        character = characters[name]
        if (character.caption.strip() and not args.force) or not any(
                args.source.animation(k).frames for k in character.animations):
            skipped += 1
            continue
        print(f"[{i}/{len(names)}] caption {name}", flush=True)
        try:
            caption = caption_character(caption_images(args, character), comfy_client.http_json,
                                        VLM_BASE_URL, VLM_MODEL, VLM_API_KEY)
        except Exception as error:
            failed += 1
            print(f"  ERROR captioning {name}: {error}", file=sys.stderr, flush=True)
            continue
        characters[name] = replace(character, caption=caption)
        save_characters(args.characters_file, characters)
        done += 1
    print(f"done: captioned={done} skipped={skipped} failed={failed} -> {args.characters_file}")
    return 1 if failed else 0


# ---- review -----------------------------------------------------------------

def judge(args, sj, attempt):
    """The VLM's verdict on one promoted attempt of a sheet."""
    audit = audit_dir(args.dst, sj.key)
    tiles = audit / f"attempt-{attempt}.tiles"
    with Image.open(tiles / "sheet.guide.png") as g, Image.open(audit / f"attempt-{attempt}.png") as r:
        guide, render = g.convert("RGB"), r.convert("RGB")
    anchor = None
    if (tiles / "sheet.anchor.png").is_file():
        with Image.open(tiles / "sheet.anchor.png") as a:
            anchor = a.convert("RGB")
    return review_sheet(guide, render, anchor, len(sj.sheet.cells), comfy_client.http_json,
                        VLM_BASE_URL, VLM_MODEL, VLM_API_KEY, variant=sj.job.trn is not None)


def cmd_review(args):
    characters = load_characters_checked(args)
    items = sheet_jobs(args, select_jobs(args, characters))
    code = vlm_preflight()
    if code is not None:
        return code
    free_comfy_models()     # give the VLM room; ComfyUI may be down
    reviews = load_reviews(args.reviews, optional=True)
    todo, skipped = [], 0
    for sj in items:
        status, attempt, _ = status_of(args, sj, reviews, characters)
        review = current_review(reviews, sj.key, attempt)
        # Only a done sheet (promoted, not stale) is judged: a gate rejection already has
        # its verdict, and a failed attempt has nothing to show.
        if status != "done" or (review is not None and review.attempt >= attempt
                                and not args.force):
            skipped += 1
            continue
        todo.append((sj, attempt))
    accepted = rejected = failed = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(judge, args, sj, attempt): (sj, attempt) for sj, attempt in todo}
        try:
            for n, future in enumerate(as_completed(futures), 1):
                sj, attempt = futures[future]
                audit = audit_dir(args.dst, sj.key)
                try:
                    verdict = future.result()
                except Exception as error:
                    failed += 1
                    write_atomic(audit / f"attempt-{attempt}.review-error.txt", str(error))
                    print(f"[{n}/{len(todo)}] ERROR reviewing {sj.key}: {error}",
                          file=sys.stderr, flush=True)
                    continue
                write_atomic(audit / f"attempt-{attempt}.review.json",
                             json.dumps(verdict, indent=2))
                reviews[sj.key] = Review(attempt, verdict["accepted"], tuple(verdict["issues"]),
                                         "review")
                save_reviews(args.reviews, reviews)
                if verdict["accepted"]:
                    accepted += 1
                    print(f"[{n}/{len(todo)}] {sj.key}: accepted", flush=True)
                else:
                    rejected += 1
                    print(f"[{n}/{len(todo)}] {sj.key}: rejected: "
                          + "; ".join(verdict["issues"]), flush=True)
        except KeyboardInterrupt:
            # Drop the queued requests; leaving the `with` waits only for the ones
            # in flight. The verdicts already saved stay.
            pool.shutdown(wait=False, cancel_futures=True)
            raise
    print(f"done: accepted={accepted} rejected={rejected} skipped={skipped} failed={failed} "
          f"-> {args.reviews}")
    return 1 if failed else 0


# ---- verify -----------------------------------------------------------------

def frame_problem(path, mask, skip):
    """(code, detail) for an output frame that breaks the contract, or None."""
    if not path.is_file():
        return "MISSING", ""
    try:
        with Image.open(path) as im:
            size, mode = im.size, im.mode
            alpha = np.asarray(im.getchannel("A")) if mode == "RGBA" else None
    except OSError:
        return "UNREADABLE", ""
    want = (mask.shape[1] * SCALE, mask.shape[0] * SCALE)
    if size != want:
        return "WRONGSIZE", f"is {size[0]}x{size[1]}, expected {want[0]}x{want[1]}"
    if mode != "RGBA":
        return "WRONGMODE", f"is {mode}, expected RGBA"
    expected = sheet_layout.hard_alpha(mask) if skip else sheet_layout.soft_alpha(mask)
    if not np.array_equal(alpha, expected):
        return "WRONGALPHA", "the alpha is not the source outline at 2x"
    return None


def cmd_verify(args):
    characters = load_characters_checked(args)
    reviews = load_reviews(args.reviews, optional=True)
    jobs = select_jobs(args, characters)
    bad = frames = 0
    for job in jobs:
        masks = layout(args, job.anim)[1]
        sheets = job_sheets(args, job)
        cells = {cell.frame for sheet in sheets for cell in sheet.cells}
        for index, (frame, mask) in enumerate(zip(job.anim.frames, masks)):
            if args.sheet and index not in cells:
                continue
            frames += 1
            problem = frame_problem(args.dst / job.key / frame.png, mask, job.skip)
            if problem:
                bad += 1
                print(f"{problem[0]:10} {job.key}/{frame.png}"
                      + (f"  {problem[1]}" if problem[1] else ""))
        if job.skip:
            continue
        for sheet in sheets:
            sj = SheetJob(job, sheet)
            changes = layout_changes(args, sj)
            if changes:
                bad += 1
                print(f"{'LAYOUT':10} {sj.key}  rendered with another {', '.join(changes)} - use "
                      "another dst= or restore the settings")
                continue
            status, attempt, _ = status_of(args, sj, reviews, characters)
            if status == "done":
                record = read_record(audit_dir(args.dst, sj.key), attempt)
                for rel, sha in record.get("frames", {}).items():
                    if source_tree.file_sha256(args.dst / rel) != sha:
                        bad += 1
                        print(f"{'UNRECORDED':10} {rel}  no attempt record promoted this file - "
                              f"run: make batch sheet={sj.key} force=1")
            elif status not in ("new", "blocked"):
                bad += 1
                print(f"{status.upper():10} {sj.key}")
    print(f"verify: {len(jobs)} animation(s) and variant(s), {frames} frame(s), "
          f"{bad} problem(s)")
    return 1 if bad else 0


# ---- preview ----------------------------------------------------------------

def cmd_preview(args):
    """An animated GIF per direction of each selected job: the source at
    SCALE (nearest) and the output side by side, over a dark background, in
    <preview dir>/<the output tree's directory name>/, so each dst= (a spike
    variant's tree) keeps its own previews."""
    characters = load_characters_checked(args)
    root = args.preview_dir / args.dst.resolve().name
    written = 0
    for job in select_jobs(args, characters):
        # Only --sheet needs the layout (it reads every frame): its sheets' directions.
        wanted = args.sheet and {group for sheet in job_sheets(args, job)
                                 for group in sheet.groups}
        groups = {}
        for frame in job.anim.frames:
            if not wanted or frame.group in wanted:
                groups.setdefault(frame.group, []).append(frame)
        for group, frames in sorted(groups.items()):
            pictures = []
            for frame in frames:
                w, h = frame.w * SCALE, frame.h * SCALE
                picture = Image.new("RGB", (2 * w + 8, h), PREVIEW_BACKGROUND)
                source = sheet_layout.nearest_frame(
                    source_tree.frame_rgba(args.src, job.anim, frame, job.trn))
                picture.paste(source, (0, 0), source)
                out = args.dst / job.key / frame.png
                if out.is_file():
                    with Image.open(out) as im:
                        render = im.convert("RGBA")
                    picture.paste(render, (w + 8, 0), render)
                pictures.append(picture)
            path = root / comfy_client.comfy_name(job.key) / f"d{group}.gif"
            save_image_atomic(pictures[0], path, "GIF", save_all=True, append_images=pictures[1:],
                              duration=PREVIEW_MS, loop=0)
            written += 1
    print(f"preview: {written} GIF(s) -> {root}")
    return 0


# ---- command line -----------------------------------------------------------

def default_workflow(environ=os.environ):
    """--workflow when the flag is absent: DIA_WORKFLOW or comfy_client.DEFAULT_WORKFLOW."""
    name = environ.get("DIA_WORKFLOW") or comfy_client.DEFAULT_WORKFLOW
    if name not in comfy_client.WORKFLOWS:
        raise UsageError(f"DIA_WORKFLOW={name!r} is not a workflow; choose one of "
                         + ", ".join(sorted(comfy_client.WORKFLOWS)))
    return name


def match_strength(text):
    """argparse type for --match-strength: a number from 0 to 1."""
    try:
        value = float(text)
    except ValueError:
        value = -1.0
    if not 0 <= value <= 1:
        raise argparse.ArgumentTypeError(f"{text} is not a number from 0 to 1")
    return value


def default_match_strength(environ=os.environ):
    """--match-strength when the flag is absent: DIA_MATCH_STRENGTH or DEFAULT_MATCH_STRENGTH."""
    text = environ.get("DIA_MATCH_STRENGTH")
    if not text:
        return DEFAULT_MATCH_STRENGTH
    try:
        return match_strength(text)
    except argparse.ArgumentTypeError as error:
        raise UsageError(f"DIA_MATCH_STRENGTH: {error}") from error


def positive_int(text):
    try:
        value = int(text)
    except ValueError:
        value = 0
    if value < 1:
        raise argparse.ArgumentTypeError(f"{text} is not a whole number of 1 or more")
    return value


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p, sheets=True):
        p.add_argument("--src", type=Path, default=SRC_ROOT,
                       help="diablo-textures-exporter output (default: %(default)s, or DIA_SRC)")
        p.add_argument("--dst", type=Path, default=DST_ROOT,
                       help="output tree (default: %(default)s, or DIA_DST)")
        p.add_argument("--characters-file", type=Path, default=CHARACTERS_FILE,
                       help="characters file (default: %(default)s, or DIA_CHARACTERS)")
        p.add_argument("--reviews", type=Path, default=REVIEWS_FILE,
                       help="reviews file (default: %(default)s, or DIA_REVIEWS)")
        p.add_argument("--character", action="append", metavar="KEY",
                       help="process character KEY only (repeatable)")
        p.add_argument("--anim", action="append", metavar="KEY",
                       help="process animation KEY (its record directory) only (repeatable)")
        if sheets:
            p.add_argument("--sheet", action="append", metavar="KEY",
                           help="process sheet KEY only, e.g. monsters/zombie/zombien.cl2/s02 or "
                                "a variant's .../zombien.cl2/@trn/monsters/zombie/grey.trn/s02 "
                                "(repeatable)")
        p.add_argument("--no-variants", action="store_true",
                       help="leave out the recolour variants")
        p.add_argument("--variant", action="append", metavar="TRN",
                       help="of the variants, process TRN (e.g. monsters/zombie/grey.trn) only "
                            "(repeatable)")
        p.add_argument("--packing", choices=sheet_layout.PACKINGS,
                       default=sheet_layout.SHEET_PACKING,
                       help="one direction per sheet, or several (default: %(default)s)")
        p.add_argument("--gutter", type=positive_int, default=sheet_layout.GUTTER, metavar="PX",
                       help="HD px between cells (default: %(default)s)")
        p.add_argument("--background", choices=sorted(sheet_layout.BACKGROUNDS),
                       default=sheet_layout.BACKGROUND,
                       help="the flat colour behind the figures (default: %(default)s)")
        p.add_argument("--no-anchor", action="store_true",
                       help="paint every sheet against its guide only (a spike variant)")

    caption = sub.add_parser("caption", help="seed characters.yaml and caption its characters")
    common(caption, sheets=False)
    caption.add_argument("--force", action="store_true",
                         help="re-caption characters that already have a caption")
    caption.set_defaults(func=cmd_caption)

    batch = sub.add_parser("batch", help="render sheets through ComfyUI")
    common(batch)
    batch.add_argument("--dry-run", action="store_true",
                       help="print the plan without contacting ComfyUI or writing files")
    batch.add_argument("--no-memory-check", action="store_true",
                       help=f"skip the {MEMORY_FLOOR_GB} GB available-memory guard")
    batch.add_argument("--force", action="store_true",
                       help="render the selection again, even when done or stuck")
    batch.add_argument("--match-strength", type=match_strength, default=default_match_strength(),
                       metavar="X", help="how far each frame moves toward its source's colours, "
                                         "0 to 1 (default: %(default)s, or DIA_MATCH_STRENGTH)")
    batch.add_argument("--workflow", choices=sorted(comfy_client.WORKFLOWS),
                       default=default_workflow(), metavar="NAME",
                       help="render workflow: " + ", ".join(sorted(comfy_client.WORKFLOWS))
                            + " (default: %(default)s, or DIA_WORKFLOW)")
    batch.set_defaults(func=cmd_batch)

    review = sub.add_parser("review", help="judge promoted sheets through the local vLLM")
    common(review)
    review.add_argument("--force", action="store_true",
                        help="review sheets whose latest attempt was already reviewed")
    review.add_argument("--concurrency", type=positive_int, default=DEFAULT_CONCURRENCY,
                        metavar="N", help="requests in flight at once (default: %(default)s)")
    review.set_defaults(func=cmd_review)

    verify = sub.add_parser("verify", help="audit the output tree")
    common(verify)
    verify.set_defaults(func=cmd_verify)

    preview = sub.add_parser("preview", help="write an animated GIF per direction")
    common(preview)
    preview.add_argument("--preview-dir", type=Path, default=PREVIEW_ROOT,
                         help="where the GIFs go, under the output tree's directory name "
                              "(default: %(default)s, or DIA_PREVIEW)")
    preview.set_defaults(func=cmd_preview)
    return ap


def main(argv=None):
    try:
        args = build_parser().parse_args(argv)
        if not args.src.is_dir():
            return fail(f"source is not a directory: {args.src} - set DIA_SRC or pass --src")
        args.source = source_tree.load(args.src)
        args.layouts = {}
        return args.func(args)
    except (UsageError, CharactersFileError, SourceError) as error:
        return fail(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
