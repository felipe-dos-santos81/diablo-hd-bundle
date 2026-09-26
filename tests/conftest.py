import os
from pathlib import Path

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("DTX_GAME_DIR"):
        return
    skip = pytest.mark.skip(reason="set DTX_GAME_DIR to run game-data tests")
    for item in items:
        if "game" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def game_dir() -> Path:
    return Path(os.environ["DTX_GAME_DIR"]).expanduser()
