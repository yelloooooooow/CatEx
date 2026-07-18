from __future__ import annotations

import hashlib

from pymatgen.core import Structure

from catex.hashing import artifact_record, canonical_structure_payload, structure_hash


def test_artifact_record_uses_file_bytes(tmp_path) -> None:
    source = tmp_path / "artifact.txt"
    source.write_bytes(b"catex\n")

    record = artifact_record(source)

    assert record.sha256 == hashlib.sha256(b"catex\n").hexdigest()
    assert record.size_bytes == 6
    assert record.schema_version == "catex.artifact.v1"


def test_structure_hash_is_site_order_independent(nacl_structure) -> None:
    reordered = Structure.from_sites(list(reversed(nacl_structure.sites)))

    assert structure_hash(reordered) == structure_hash(nacl_structure)
    assert canonical_structure_payload(reordered) == canonical_structure_payload(nacl_structure)


def test_structure_hash_is_not_used_as_translation_invariant_identity(nacl_structure) -> None:
    translated = nacl_structure.copy()
    translated.translate_sites(
        range(len(translated)), [0.123, 0.234, 0.345], frac_coords=True, to_unit_cell=True
    )

    assert structure_hash(translated) != structure_hash(nacl_structure)
