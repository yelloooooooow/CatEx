from __future__ import annotations

from catex.models import Diagnostic, Severity, TransformationRecord


def test_diagnostic_serialization_uses_stable_machine_fields() -> None:
    diagnostic = Diagnostic(
        "EXAMPLE",
        Severity.WARNING,
        "Review this value.",
        {"z": 2, "a": 1},
    )

    assert diagnostic.to_dict() == {
        "code": "EXAMPLE",
        "severity": "warning",
        "message": "Review this value.",
        "context": {"a": 1, "z": 2},
    }


def test_transformation_contract_is_versioned() -> None:
    record = TransformationRecord(
        operation="round-trip",
        input_hashes=("before",),
        output_hashes=("after",),
        parameters={"backend": "synthetic"},
    )

    payload = record.to_dict()

    assert payload["schema_version"] == "catex.transformation.v1"
    assert payload["input_hashes"] == ["before"]
    assert payload["parameters"] == {"backend": "synthetic"}
