"""Test de sante du worker : un battement de coeur trop ancien le declare malade."""

import os
import time
from pathlib import Path

import pytest

from lorakus import worker


def test_healthcheck_reads_the_heartbeat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    beat = tmp_path / "beat"
    monkeypatch.setattr(worker, "HEARTBEAT_FILE", beat)
    assert worker.main(["healthcheck"]) == 1
    beat.touch()
    assert worker.main(["healthcheck"]) == 0
    old = time.time() - worker.HEARTBEAT_MAX_AGE_S - 5
    os.utime(beat, (old, old))
    assert worker.main(["healthcheck"]) == 1
