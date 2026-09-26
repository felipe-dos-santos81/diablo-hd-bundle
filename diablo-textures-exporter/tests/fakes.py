from dtx.paths import canonical


class FakeArchive:
    def __init__(self, name: str, files: dict[str, bytes], unnamed=()):
        self.name = name
        self.files = {canonical(k): v for k, v in files.items()}
        self.unnamed = list(unnamed)

    def read(self, name: str) -> bytes | None:
        return self.files.get(canonical(name))

    def has(self, name: str) -> bool:
        return canonical(name) in self.files

    def names(self) -> list[str]:
        return [n.upper() for n in self.files] + self.unnamed + ["(listfile)"]

    def close(self) -> None:
        pass
