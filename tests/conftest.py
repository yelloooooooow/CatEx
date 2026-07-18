"""Shared synthetic periodic structures for CatEx tests."""

from __future__ import annotations

import pytest
from pymatgen.core import Lattice, Structure


@pytest.fixture
def nacl_structure() -> Structure:
    return Structure(
        Lattice.cubic(5.64),
        ["Na", "Cl"],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
    )
