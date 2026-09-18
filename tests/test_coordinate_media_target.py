from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location(
        "coordinate_media_target_test_module", ROOT / "scripts/coordinate_media_target.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_allocates_odd_remainder_without_exceeding_supply():
    coordinator = load_module()

    assert coordinator.allocate(13, 50, 50) == (7, 6)
    assert coordinator.allocate(13, 4, 20) == (4, 9)


def test_rejects_unfillable_remainder():
    coordinator = load_module()

    with pytest.raises(ValueError, match="cannot fit"):
        coordinator.allocate(5, 2, 2)
