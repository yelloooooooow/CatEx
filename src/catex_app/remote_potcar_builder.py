"""Small stdlib-only POTCAR builder uploaded into one new remote run directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

_LABEL = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")


def build(*, potcar_root: Path, metadata_path: Path, output_path: Path) -> dict[str, object]:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    datasets = metadata.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        raise ValueError("POTCAR metadata has no datasets")
    root = potcar_root.resolve(strict=True)
    if output_path.exists():
        raise FileExistsError("POTCAR already exists; overwrite is forbidden")

    labels: list[str] = []
    hashes: list[str] = []
    combined = hashlib.sha256()
    with output_path.open("xb") as target:
        for dataset in datasets:
            label = str(dataset.get("potential_label", ""))
            expected = str(dataset.get("sha256", ""))
            if _LABEL.fullmatch(label) is None or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
                raise ValueError("POTCAR metadata contains an unsafe label or hash")
            source = (root / label / "POTCAR").resolve(strict=True)
            if source.parent.parent != root or not source.is_file():
                raise ValueError("POTCAR dataset escaped the approved library root")
            digest = hashlib.sha256()
            with source.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    combined.update(chunk)
                    target.write(chunk)
            actual = digest.hexdigest()
            if actual != expected:
                raise ValueError("POTCAR dataset hash does not match approved metadata")
            labels.append(label)
            hashes.append(actual)
    return {
        "schema_version": "catex.remote-potcar-build.v1",
        "datasets": labels,
        "dataset_sha256": hashes,
        "sha256": combined.hexdigest(),
        "overwrite_performed": False,
        "deletion_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--potcar-root", required=True, type=Path)
    parser.add_argument("--metadata", default=Path("catex-potcar-metadata.json"), type=Path)
    parser.add_argument("--output", default=Path("POTCAR"), type=Path)
    arguments = parser.parse_args()
    report = build(
        potcar_root=arguments.potcar_root,
        metadata_path=arguments.metadata,
        output_path=arguments.output,
    )
    print(json.dumps(report, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
