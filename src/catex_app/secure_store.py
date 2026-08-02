"""System-backed credential storage for the local CatEx workbench.

Secrets are stored through the operating-system keyring and are never written
to CatEx projects, configuration files, exports, or logs. Environment
variables remain the higher-priority source for automated deployments.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from threading import RLock
from typing import Literal, Protocol

CredentialProvider = Literal["materials_project", "openai"]
CredentialSource = Literal["environment", "system_keyring"]

_SERVICE_NAME = "CatEx Workbench"
_PROVIDER_ACCOUNTS: dict[CredentialProvider, str] = {
    "materials_project": "materials-project-api-key",
    "openai": "openai-api-key",
}
_PROVIDER_ENVIRONMENT_VARIABLES: dict[CredentialProvider, str] = {
    "materials_project": "MP_API_KEY",
    "openai": "OPENAI_API_KEY",
}
_SECURE_BACKEND_MODULE_PREFIXES = (
    "keyring.backends.Windows",
    "keyring.backends.macOS",
    "keyring.backends.SecretService",
    "keyring.backends.kwallet",
    "keyring.backends.libsecret",
)


class CredentialStoreError(RuntimeError):
    """Raised when a system credential-store operation cannot be completed."""


@dataclass(frozen=True, slots=True)
class CredentialStoreStatus:
    """Non-secret status of the operating-system credential backend."""

    available: bool
    persistent: bool
    backend: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "persistent": self.persistent,
            "backend": self.backend,
            "reason": self.reason,
        }


class CredentialStore(Protocol):
    """Narrow injectable boundary used by the application service and tests."""

    def status(self) -> CredentialStoreStatus: ...

    def get(self, provider: CredentialProvider) -> str | None: ...

    def set(self, provider: CredentialProvider, secret: str) -> None: ...

    def delete(self, provider: CredentialProvider) -> bool: ...


class SystemCredentialStore:
    """Store CatEx secrets in a supported operating-system keyring backend."""

    def __init__(self, *, service_name: str = _SERVICE_NAME) -> None:
        self.service_name = service_name
        self._lock = RLock()

    @staticmethod
    def _backend() -> tuple[object | None, CredentialStoreStatus]:
        try:
            import keyring

            backend = keyring.get_keyring()
        except Exception:
            return None, CredentialStoreStatus(
                available=False,
                persistent=False,
                reason="system_keyring_unavailable",
            )
        backend_type = type(backend)
        backend_name = f"{backend_type.__module__}.{backend_type.__name__}"
        priority = getattr(backend, "priority", 0)
        if (
            not isinstance(priority, int | float)
            or priority <= 0
            or not backend_type.__module__.startswith(_SECURE_BACKEND_MODULE_PREFIXES)
        ):
            return None, CredentialStoreStatus(
                available=False,
                persistent=False,
                backend=backend_name,
                reason="secure_system_keyring_not_detected",
            )
        return backend, CredentialStoreStatus(
            available=True,
            persistent=True,
            backend=backend_name,
        )

    def status(self) -> CredentialStoreStatus:
        return self._backend()[1]

    def _require_backend(self) -> object:
        backend, status = self._backend()
        if backend is None or not status.available:
            raise CredentialStoreError(
                "a supported operating-system credential store is not available"
            )
        return backend

    @staticmethod
    def _account(provider: CredentialProvider) -> str:
        try:
            return _PROVIDER_ACCOUNTS[provider]
        except KeyError as exc:
            raise CredentialStoreError("unsupported credential provider") from exc

    def get(self, provider: CredentialProvider) -> str | None:
        with self._lock:
            backend = self._require_backend()
            try:
                value = backend.get_password(self.service_name, self._account(provider))
            except Exception as exc:
                raise CredentialStoreError(
                    "the operating-system credential store could not be read"
                ) from exc
        return value if isinstance(value, str) and value else None

    def set(self, provider: CredentialProvider, secret: str) -> None:
        with self._lock:
            backend = self._require_backend()
            try:
                backend.set_password(self.service_name, self._account(provider), secret)
            except Exception as exc:
                raise CredentialStoreError(
                    "the operating-system credential store could not save the credential"
                ) from exc

    def delete(self, provider: CredentialProvider) -> bool:
        with self._lock:
            backend = self._require_backend()
            account = self._account(provider)
            try:
                if not backend.get_password(self.service_name, account):
                    return False
                backend.delete_password(self.service_name, account)
            except Exception as exc:
                raise CredentialStoreError(
                    "the operating-system credential store could not delete the credential"
                ) from exc
        return True


@dataclass(frozen=True, slots=True)
class ResolvedCredential:
    """One secret and its non-secret source label."""

    value: str
    source: CredentialSource


def environment_variable(provider: CredentialProvider) -> str:
    """Return the documented environment-variable fallback for a provider."""

    return _PROVIDER_ENVIRONMENT_VARIABLES[provider]


def resolve_credential(
    store: CredentialStore,
    provider: CredentialProvider,
) -> ResolvedCredential | None:
    """Resolve an environment override or a system-keyring credential."""

    environment_value = os.environ.get(environment_variable(provider), "").strip()
    if environment_value:
        return ResolvedCredential(environment_value, "environment")
    try:
        stored_value = store.get(provider)
    except CredentialStoreError:
        return None
    if stored_value:
        return ResolvedCredential(stored_value, "system_keyring")
    return None
