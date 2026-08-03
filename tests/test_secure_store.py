from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from fastapi.testclient import TestClient

from catex.experimental import MPAPISummaryClient, OpenAIResponsesTransport
from catex_app.secure_store import (
    CredentialProvider,
    CredentialStoreStatus,
    SystemCredentialStore,
    resolve_credential,
)
from catex_web.app import create_app


@dataclass
class _MemoryCredentialStore:
    values: dict[str, str] = field(default_factory=dict)

    def status(self) -> CredentialStoreStatus:
        return CredentialStoreStatus(
            available=True,
            persistent=True,
            backend="test.secure.MemoryKeyring",
        )

    def get(self, provider: CredentialProvider) -> str | None:
        return self.values.get(provider)

    def set(self, provider: CredentialProvider, secret: str) -> None:
        self.values[provider] = secret

    def delete(self, provider: CredentialProvider) -> bool:
        return self.values.pop(provider, None) is not None


def test_credential_resolution_prefers_environment_without_exposing_value(
    monkeypatch,
) -> None:
    store = _MemoryCredentialStore({"materials_project": "stored-test-key"})
    monkeypatch.setenv("MP_API_KEY", "environment-test-key")

    resolved = resolve_credential(store, "materials_project")

    assert resolved is not None
    assert resolved.source == "environment"
    assert resolved.value == "environment-test-key"
    assert "environment-test-key" not in str(store.status().to_dict())


def test_system_credential_store_uses_supported_backend(monkeypatch) -> None:
    import keyring

    class _WindowsBackend:
        __module__ = "keyring.backends.Windows"
        priority = 5

        def __init__(self) -> None:
            self.values: dict[tuple[str, str], str] = {}

        def get_password(self, service: str, account: str) -> str | None:
            return self.values.get((service, account))

        def set_password(self, service: str, account: str, password: str) -> None:
            self.values[(service, account)] = password

        def delete_password(self, service: str, account: str) -> None:
            del self.values[(service, account)]

    backend = _WindowsBackend()
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    store = SystemCredentialStore()

    assert store.status().available is True
    assert store.get("materials_project") is None
    store.set("materials_project", "synthetic-key")
    assert store.get("materials_project") == "synthetic-key"
    assert store.delete("materials_project") is True
    assert store.delete("materials_project") is False


def test_web_credentials_are_verified_saved_and_deleted_without_project_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = _MemoryCredentialStore()
    monkeypatch.delenv("MP_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        MPAPISummaryClient,
        "verify_connection",
        lambda self: "2026.07.31",
    )
    monkeypatch.setattr(
        OpenAIResponsesTransport,
        "verify_api_key",
        lambda self: 7,
    )
    application = create_app(data_root=tmp_path, credential_store=store)

    with TestClient(application) as client:
        mp_saved = client.put(
            "/api/v1/experimental-modeling/credentials/materials_project",
            json={"secret": "synthetic-mp-key"},
        )
        openai_saved = client.put(
            "/api/v1/experimental-modeling/credentials/openai",
            json={"secret": "synthetic-openai-key"},
        )
        capabilities = client.get("/api/v1/experimental-modeling/capabilities")
        deleted = client.delete("/api/v1/experimental-modeling/credentials/materials_project")

    assert mp_saved.status_code == 200
    assert mp_saved.json()["verification"]["database_version"] == "2026.07.31"
    assert openai_saved.status_code == 200
    assert openai_saved.json()["verification"]["visible_model_count"] == 7
    assert capabilities.json()["schema_version"].endswith(".v2")
    assert (
        capabilities.json()["providers"]["materials_project"]["credential_source"]
        == "system_keyring"
    )
    assert capabilities.json()["gpt_planner"]["credential_source"] == "system_keyring"
    assert deleted.status_code == 200
    assert deleted.json()["deleted_from_system"] is True
    serialized = str([mp_saved.json(), openai_saved.json(), capabilities.json(), deleted.json()])
    assert "synthetic-mp-key" not in serialized
    assert "synthetic-openai-key" not in serialized
    assert store.values == {"openai": "synthetic-openai-key"}
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


def test_failed_verification_does_not_replace_saved_credential(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = _MemoryCredentialStore({"materials_project": "previous-valid-key"})

    def fail_verification(self) -> str:
        raise ValueError("Materials Project credential verification failed")

    monkeypatch.setattr(MPAPISummaryClient, "verify_connection", fail_verification)
    with TestClient(create_app(data_root=tmp_path, credential_store=store)) as client:
        response = client.put(
            "/api/v1/experimental-modeling/credentials/materials_project",
            json={"secret": "replacement-invalid-key"},
        )

    assert response.status_code == 400
    assert store.values["materials_project"] == "previous-valid-key"
    assert "replacement-invalid-key" not in response.text
