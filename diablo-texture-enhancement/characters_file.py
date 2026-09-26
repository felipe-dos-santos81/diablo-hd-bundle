"""Read and write characters.yaml and reviews.yaml.

characters.yaml is hand-owned: one entry per character, keyed by a name (the
seed uses the animations' shared directory), with its `animations` (record
directories, in render order), its `anchor` (the animation every other one is
painted against), a `caption` that `make caption` fills and the user edits,
and `skip` (animations written as a nearest-neighbour 2x instead). Every
manifest animation belongs to exactly one character.

reviews.yaml is machine-written: one verdict per sheet (key
`<job key>/sNN`) on its latest judged attempt, from the VLM review
(`source: review`) or from batch's gate (`source: geometry`).

Multi-line strings are written in folded (`>`) style; every save goes to
<file>.tmp and is renamed into place.
"""
import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

REVIEW_SOURCES = ("review", "geometry")
_SHEET_KEY = re.compile(r"^\S+/s\d{2}$")
_TRAILING_DIGITS = re.compile(r"\d+$")


class CharactersFileError(ValueError):
    """A YAML file does not have the shape this kit expects."""


@dataclass(frozen=True)
class Character:
    animations: tuple   # record directories, in render order
    anchor: str         # one of animations, not skipped
    caption: str = ""
    skip: tuple = ()    # animations written as a nearest-neighbour 2x


@dataclass(frozen=True)
class Review:
    attempt: int
    accepted: bool
    issues: tuple
    source: str = "review"


def normalize_text(text):
    """Strip trailing whitespace on each line and trailing blank lines.

    PyYAML refuses block style for text with a space before a line break and
    falls back to a double-quoted scalar; VLM output often has such spaces.
    """
    return "\n".join(line.rstrip() for line in text.splitlines()).rstrip("\n")


class _Dumper(yaml.SafeDumper):
    pass


def _represent_str(dumper, data):
    style = ">" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _represent_str)


def _dump(mapping, path):
    path = Path(path)
    text = yaml.dump(mapping, Dumper=_Dumper, sort_keys=False, allow_unicode=True,
                     width=1_000_000)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _read_mapping(path, optional):
    path = Path(path)
    if not path.exists():
        if optional:
            return {}
        raise CharactersFileError(f"{path}: file not found")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise CharactersFileError(f"{path}: invalid YAML: {error}") from error
    if data is None:
        return {}
    if not isinstance(data, dict) or any(not isinstance(k, str) for k in data):
        raise CharactersFileError(f"{path}: expected a mapping with string keys")
    return data


def _strings(value, where, field):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value):
        raise CharactersFileError(f'{where}: "{field}" must be a list of animation keys')
    return tuple(value)


def load_characters(path):
    """{character key: Character}. A missing or blank caption loads as ""."""
    result = {}
    for key, entry in _read_mapping(path, optional=False).items():
        where = f"{Path(path)}: {key}"
        if not isinstance(entry, dict):
            raise CharactersFileError(f"{where}: expected a mapping")
        unknown = sorted(set(entry) - {"animations", "anchor", "caption", "skip"})
        if unknown:
            raise CharactersFileError(f"{where}: unknown field(s) {', '.join(unknown)}")
        animations = _strings(entry.get("animations"), where, "animations")
        skip = _strings(entry.get("skip") or [], where, "skip")
        anchor = entry.get("anchor")
        if anchor not in animations:
            raise CharactersFileError(f'{where}: "anchor" must be one of its animations')
        if anchor in skip:
            raise CharactersFileError(f'{where}: the anchor {anchor} cannot be skipped')
        if set(skip) - set(animations):
            raise CharactersFileError(f'{where}: "skip" names animations it does not have: '
                                      + ", ".join(sorted(set(skip) - set(animations))))
        caption = entry.get("caption")
        if caption is None:
            caption = ""
        if not isinstance(caption, str):
            raise CharactersFileError(f'{where}: "caption" must be a string')
        result[key] = Character(animations, anchor, caption, skip)
    return result


def save_characters(path, characters):
    def entry(c):
        out = {"animations": list(c.animations), "anchor": c.anchor,
               "caption": normalize_text(c.caption)}
        if c.skip:
            out["skip"] = list(c.skip)
        return out
    _dump({key: entry(characters[key]) for key in sorted(characters)}, path)


def check_coverage(characters, animation_keys, path="characters.yaml"):
    """Raise unless every key in `animation_keys` belongs to exactly one character
    and no character names an animation outside them."""
    owner, problems = {}, []
    for key, character in characters.items():
        for anim in character.animations:
            if anim in owner:
                problems.append(f"{anim} is in both {owner[anim]} and {key}")
            owner[anim] = key
    missing = [k for k in animation_keys if k not in owner]
    extra = sorted(set(owner) - set(animation_keys))
    if missing:
        problems.append("no character for " + ", ".join(missing))
    if extra:
        problems.append("animations not in the manifest: " + ", ".join(extra))
    if problems:
        raise CharactersFileError(f"{path}: " + "; ".join(problems))


def character_key(anim_key, kind):
    """The seed's character for an animation: a missile's directory plus its file
    stem without trailing digits (missiles/acidbf1.cl2 -> missiles/acidbf);
    anything else, its directory (monsters/zombie/zombiew.cl2 -> monsters/zombie)."""
    folder, _, name = anim_key.rpartition("/")
    if kind == "missile":
        stem = _TRAILING_DIGITS.sub("", name.split(".")[0])
        return f"{folder}/{stem}" if folder else stem
    return folder or name


def _natural(key):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", key)]


def seed_anchor(anim_keys, kind, empty=()):
    """The seed's anchor: a player's standing animation (stem ending "st"), a
    monster's neutral one (ending "n"), else the first in natural order;
    never one of `empty` (animations without frames) while another has frames."""
    ordered = sorted(anim_keys, key=_natural)
    ordered = [k for k in ordered if k not in empty] or ordered
    ending = {"player_anim": "st", "monster_anim": "n"}.get(kind)
    if ending:
        for key in ordered:
            if key.rpartition("/")[2].split(".")[0].endswith(ending):
                return key
    return ordered[0]


def seed_characters(animations):
    """{character key: Character} for [(animation key, kind, frame count), ...]:
    the grouping and anchors `make caption` proposes. The one place that reads
    names for meaning; the user may change all of it."""
    groups, kinds, empty = {}, {}, set()
    for key, kind, count in animations:
        ck = character_key(key, kind)
        groups.setdefault(ck, []).append(key)
        kinds.setdefault(ck, kind)
        if not count:
            empty.add(key)
    result = {}
    for ck, keys in groups.items():
        anchor = seed_anchor(keys, kinds[ck], empty)
        rest = [k for k in sorted(keys, key=_natural) if k != anchor]
        result[ck] = Character(tuple([anchor] + rest), anchor)
    return result


def load_reviews(path, optional=False):
    """{sheet key: Review}. A missing file is {} when optional, else an error."""
    result = {}
    for key, entry in _read_mapping(path, optional).items():
        where = f"{Path(path)}: {key}"
        if not _SHEET_KEY.match(key):
            raise CharactersFileError(f"{where}: not a sheet key (<animation>/sNN)")
        if not isinstance(entry, dict):
            raise CharactersFileError(f"{where}: expected a mapping")
        unknown = sorted(set(entry) - {"attempt", "accepted", "issues", "source"})
        if unknown:
            raise CharactersFileError(f"{where}: unknown field(s) {', '.join(unknown)}")
        attempt, accepted = entry.get("attempt"), entry.get("accepted")
        issues, source = entry.get("issues"), entry.get("source", "review")
        if type(attempt) is not int or attempt < 0:
            raise CharactersFileError(f'{where}: "attempt" must be a non-negative integer')
        if type(accepted) is not bool:
            raise CharactersFileError(f'{where}: "accepted" must be true or false')
        if (not isinstance(issues, list)
                or any(not isinstance(x, str) or not x.strip() for x in issues)):
            raise CharactersFileError(f'{where}: "issues" must be a list of non-empty strings')
        if accepted != (not issues):
            raise CharactersFileError(f'{where}: "accepted" contradicts "issues"')
        if source not in REVIEW_SOURCES:
            raise CharactersFileError(f'{where}: "source" must be one of '
                                      f'{", ".join(REVIEW_SOURCES)}')
        result[key] = Review(attempt, accepted, tuple(issues), source)
    return result


def save_reviews(path, reviews):
    _dump({key: {"attempt": r.attempt, "accepted": r.accepted,
                 "issues": [normalize_text(x) for x in r.issues], "source": r.source}
           for key, r in sorted(reviews.items())}, path)
