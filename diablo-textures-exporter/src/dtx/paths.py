"""Name helpers. Canonical MPQ names are lower-case with backslash separators."""


def canonical(name: str) -> str:
    return name.replace("/", "\\").lower()


def rel_path(name: str) -> str:
    return canonical(name).replace("\\", "/")


def directory(name: str) -> str:
    c = canonical(name)
    return c.rsplit("\\", 1)[0] if "\\" in c else ""


def extension(name: str) -> str:
    base = canonical(name).rsplit("\\", 1)[-1]
    return base.rsplit(".", 1)[1] if "." in base else ""


def stem(name: str) -> str:
    c = canonical(name)
    ext = extension(c)
    return c[: -(len(ext) + 1)] if ext else c
