# ADR 0008: Operating-system credential storage

- Status: accepted
- Date: 2026-07-31
- Supersedes: credential-handling portion of ADR 0007
- Extends: ADR 0007

## Context

Environment variables keep provider credentials outside projects and source
control, but they create unnecessary friction for a local desktop workbench.
Re-entering a key for every run is not acceptable routine interaction, while
storing it in a project, JSON preference, `.env` file, browser storage, or log
would create avoidable disclosure paths.

## Decision

CatEx uses the Python `keyring` abstraction only when it resolves to a supported
operating-system secure backend. On Windows this is Windows Credential Manager.
The Web workbench provides separate password inputs for Materials Project and
OpenAI, verifies a submitted key through a bounded read-only provider request,
and stores it only after successful verification.

Credential requests are global to the local workbench rather than project
routes. Pydantic `SecretStr` prevents routine request-object representation from
revealing values. The browser keeps the submitted key only in component memory,
clears the field before awaiting the request, and never uses local/session
storage. API responses expose status and source only.

Environment variables remain supported and take precedence for automated
deployment. Runtime provider adapters accept one ephemeral resolved key so the
system entry is not copied into `os.environ`. A failed verification cannot
replace a previous key. Delete operations remove only the system entry and
cannot modify the parent process environment.

Backends identified as fail, null, plaintext, or ordinary file stores are not
accepted as secure persistence. If no supported system backend is present, the
credential form is disabled and environment-variable operation remains
available.

## Consequences

- Users normally enter each provider key once per operating-system account.
- CatEx projects, exports, browser storage, logs, and Git remain credential-free.
- Anyone able to run code as the same signed-in operating-system user may ask
  that user's credential manager for the secret; this design does not defend
  against a fully compromised account.
- Credential verification performs an explicit network read before storage.
- Headless systems without a supported keyring continue to use environment
  variables.
- Key rotation remains the provider's responsibility; CatEx can replace or
  remove the local entry but cannot revoke a remote key.
