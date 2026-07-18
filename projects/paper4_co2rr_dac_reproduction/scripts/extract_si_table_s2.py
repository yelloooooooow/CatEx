"""Extract Table S2 from the paper's Supporting Information text export.

The script deliberately keeps the three DeltaGmax column labels exactly as they
are printed in Table S2.  The paper body and the table appear to disagree about
their order; see docs/03_si_notes.md before interpreting these columns.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import re
from pathlib import Path


ELEMENTS = ("Sn", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Mo", "Rh", "Pd", "Ag", "Ir", "Pt")
ROW_PATTERN = re.compile(
    r"^\s*([A-Z][a-z]?[A-Z][a-z]?)\s+"
    r"([+-]?\d+\.\d+)\s+([+-]?\d+\.\d+)\s+([+-]?\d+\.\d+)\s+"
    r"([+-]?\d+\.\d+)\s+([+-]?\d+\.\d+)\s*$",
    re.MULTILINE,
)


def split_pair(label: str) -> tuple[str, str]:
    parts = tuple(re.findall(r"[A-Z][a-z]?", label))
    if len(parts) != 2:
        raise ValueError(f"Cannot split metal-pair label: {label!r}")
    return parts[0], parts[1]


def canonical_pair(label: str) -> tuple[str, str]:
    first, second = split_pair(label)
    order = {symbol: index for index, symbol in enumerate(ELEMENTS)}
    return tuple(sorted((first, second), key=order.__getitem__))


def parse_rows(text: str) -> list[tuple[str, ...]]:
    start = text.index("Table S2.")
    end = text.index("Table S3.", start)
    rows = ROW_PATTERN.findall(text[start:end])

    expected_pairs = set(itertools.combinations_with_replacement(ELEMENTS, 2))
    parsed_pairs = {canonical_pair(row[0]) for row in rows}
    if len(rows) != 91 or len({row[0] for row in rows}) != 91:
        raise ValueError(f"Expected 91 unique Table S2 rows, found {len(rows)} rows")
    if parsed_pairs != expected_pairs:
        missing = sorted(expected_pairs - parsed_pairs)
        extra = sorted(parsed_pairs - expected_pairs)
        raise ValueError(f"Metal-pair validation failed; missing={missing}, extra={extra}")
    return rows


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=project_root / "references" / "si-extracted.txt",
        help="UTF-8 text exported from the SI PDF with pdftotext -layout",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "results" / "reference_table_s2.csv",
        help="Destination CSV",
    )
    args = parser.parse_args()

    rows = parse_rows(args.input.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            (
                "species",
                "source_col1_labeled_dgmax_her_eV",
                "source_col2_labeled_dgmax_co_eV",
                "source_col3_labeled_dgmax_hcooh_eV",
                "e_star_cooh_eV",
                "e_star_ocho_eV",
            )
        )
        writer.writerows(rows)

    print(f"Wrote {len(rows)} validated rows to {args.output}")


if __name__ == "__main__":
    main()
