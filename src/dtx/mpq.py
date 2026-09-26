from __future__ import annotations

import ctypes
import ctypes.util
import os
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from dtx.paths import canonical

MPQ_OPEN_READ_ONLY = 0x00000100
SFILE_OPEN_FROM_MPQ = 0
FIND_DATA_BYTES = 8192  # larger than SFILE_FIND_DATA; only cFileName (offset 0) is read
PSEUDO_NAME = re.compile(r"^File\d{8}\.\w+$")
GRAPHICS_ARCHIVES = ("hfmonk.mpq", "hellfire.mpq", "DIABDAT.MPQ")
_LIB_NAMES = ("libstorm.dylib", "libstorm.so")

_lib = None


class StormLibError(RuntimeError):
    pass


def _find_library() -> str:
    env = os.environ.get("DTX_STORMLIB")
    if env:
        return env
    try:
        prefix = subprocess.run(
            ["brew", "--prefix", "stormlib"], capture_output=True, text=True, check=True
        ).stdout.strip()
        for name in _LIB_NAMES:
            candidate = Path(prefix) / "lib" / name
            if candidate.exists():
                return str(candidate)
    except (OSError, subprocess.CalledProcessError):
        pass
    found = ctypes.util.find_library("storm")
    if found:
        return found
    raise StormLibError(
        "StormLib not found. Install it with `brew install stormlib` or set DTX_STORMLIB to the library path."
    )


def storm():
    global _lib
    if _lib is None:
        lib = ctypes.CDLL(_find_library())
        H, D, S, B = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_bool
        signatures = {
            "SFileOpenArchive": ([S, D, D, ctypes.POINTER(H)], B),
            "SFileCloseArchive": ([H], B),
            "SFileOpenFileEx": ([H, S, D, ctypes.POINTER(H)], B),
            "SFileGetFileSize": ([H, ctypes.POINTER(D)], D),
            "SFileReadFile": ([H, ctypes.c_void_p, D, ctypes.POINTER(D), ctypes.c_void_p], B),
            "SFileCloseFile": ([H], B),
            "SFileHasFile": ([H, S], B),
            "SFileAddListFile": ([H, S], D),
            "SFileFindFirstFile": ([H, S, ctypes.c_void_p, S], H),
            "SFileFindNextFile": ([H, ctypes.c_void_p], B),
            "SFileFindClose": ([H], B),
            "SErrGetLastError": ([], D),
        }
        for name, (args, res) in signatures.items():
            fn = getattr(lib, name)
            fn.argtypes, fn.restype = args, res
        _lib = lib
    return _lib


class MpqArchive:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.name = self.path.name
        handle = ctypes.c_void_p()
        if not storm().SFileOpenArchive(str(self.path).encode(), 0, MPQ_OPEN_READ_ONLY, ctypes.byref(handle)):
            raise StormLibError(f"cannot open {self.path}: StormLib error {storm().SErrGetLastError()}")
        self._handle = handle

    def close(self) -> None:
        if self._handle:
            storm().SFileCloseArchive(self._handle)
            self._handle = None

    def has(self, name: str) -> bool:
        return bool(storm().SFileHasFile(self._handle, canonical(name).encode("ascii")))

    def read(self, name: str) -> bytes | None:
        lib = storm()
        file_handle = ctypes.c_void_p()
        if not lib.SFileOpenFileEx(self._handle, canonical(name).encode("ascii"), SFILE_OPEN_FROM_MPQ,
                                   ctypes.byref(file_handle)):
            return None
        try:
            high = ctypes.c_uint32(0)
            size = lib.SFileGetFileSize(file_handle, ctypes.byref(high))
            buffer = ctypes.create_string_buffer(size)
            got = ctypes.c_uint32(0)
            lib.SFileReadFile(file_handle, buffer, size, ctypes.byref(got), None)
            if got.value != size:
                raise StormLibError(f"read {got.value} of {size} bytes of {name} from {self.name}")
            return buffer.raw[:size]
        finally:
            lib.SFileCloseFile(file_handle)

    def add_listfile(self, listfile: Path) -> None:
        error = storm().SFileAddListFile(self._handle, str(listfile).encode())
        if error:
            raise StormLibError(f"cannot add listfile {listfile} to {self.name}: error {error}")

    def names(self) -> list[str]:
        lib = storm()
        data = ctypes.create_string_buffer(FIND_DATA_BYTES)
        find = lib.SFileFindFirstFile(self._handle, b"*", data, None)
        if not find:
            return []
        names = []
        try:
            while True:
                names.append(data.value.decode("latin-1"))
                if not lib.SFileFindNextFile(find, data):
                    break
        finally:
            lib.SFileFindClose(find)
        return names


class Archive(Protocol):
    name: str

    def read(self, name: str) -> bytes | None: ...
    def has(self, name: str) -> bool: ...
    def names(self) -> list[str]: ...
    def close(self) -> None: ...


class ArchiveStack:
    """Archives in priority order, highest first."""

    def __init__(self, archives: Sequence[Archive]):
        self.archives = list(archives)

    @classmethod
    def open_game(cls, game_dir: Path, listfile: Path | None = None) -> ArchiveStack:
        files = {p.name.lower(): p for p in Path(game_dir).expanduser().iterdir() if p.is_file()}
        missing = [n for n in GRAPHICS_ARCHIVES if n.lower() not in files]
        if missing:
            raise FileNotFoundError(f"missing archives in {game_dir}: {', '.join(missing)}")
        archives = [MpqArchive(files[n.lower()]) for n in GRAPHICS_ARCHIVES]
        if listfile is not None:
            for archive in archives:
                archive.add_listfile(listfile)
        return cls(archives)

    def __enter__(self) -> ArchiveStack:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        for archive in self.archives:
            archive.close()

    def read(self, name: str) -> tuple[str, bytes] | None:
        for archive in self.archives:
            data = archive.read(name)
            if data is not None:
                return archive.name, data
        return None

    def versions(self, name: str) -> list[tuple[str, bytes]]:
        out = []
        for archive in self.archives:
            data = archive.read(name)
            if data is not None:
                out.append((archive.name, data))
        return out

    def has(self, name: str) -> bool:
        return any(a.has(name) for a in self.archives)

    def names(self) -> tuple[list[str], dict[str, list[str]]]:
        named: set[str] = set()
        unnamed: dict[str, list[str]] = {}
        for archive in self.archives:
            pseudo = []
            for name in archive.names():
                if name.startswith("("):
                    continue
                if PSEUDO_NAME.match(name):
                    pseudo.append(name)
                else:
                    named.add(canonical(name))
            unnamed[archive.name] = sorted(pseudo)
        return sorted(named), unnamed
