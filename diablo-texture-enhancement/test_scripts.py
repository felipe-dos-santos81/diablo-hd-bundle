import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent


def dry_make(*args):
    """The ./run_* command lines `make -n` would run, whitespace collapsed."""
    out = subprocess.run(["make", "-n", "-s", *args], cwd=REPO, capture_output=True, text=True,
                         check=True).stdout
    return [" ".join(line.split()) for line in out.splitlines() if line.startswith("./run_")]


class MakeTests(unittest.TestCase):
    def test_targets_forward_their_arguments(self):
        cases = {
            ("caption", "character=monsters/zombie missiles/fireba", "force=1"):
                "./run_batch.sh caption --character monsters/zombie --character missiles/fireba "
                "--force",
            ("dry-run", "variants=0", "packing=packed"):
                "./run_batch.sh batch --dry-run --no-variants --packing packed",
            ("dry-run", "variant=monsters/zombie/grey.trn"):
                "./run_batch.sh batch --dry-run --variant monsters/zombie/grey.trn",
            ("batch", "anim=monsters/zombie/zombiew.cl2", "memcheck=0", "force=1",
             "dst=data/spike/a", "gutter=32", "background=dark", "anchor=0"):
                './run_batch.sh batch --anim monsters/zombie/zombiew.cl2 --dst "data/spike/a" '
                "--gutter 32 --background dark --no-anchor --no-memory-check --force",
            ("batch", "workflow=qwen-image-2.1-i2i-faithful", "strength=0.5"):
                "./run_batch.sh batch --match-strength 0.5 --workflow qwen-image-2.1-i2i-faithful",
            ("review", "concurrency=4"): "./run_batch.sh review --concurrency 4",
            ("verify", "src=/x"): './run_batch.sh verify --src "/x"',
            ("preview", "character=missiles/fireba"):
                "./run_batch.sh preview --character missiles/fireba",
            ("server",): "./run_server.sh",
        }
        for args, expected in cases.items():
            with self.subTest(args=args):
                self.assertEqual(dry_make(*args), [expected])


if __name__ == "__main__":
    unittest.main()
