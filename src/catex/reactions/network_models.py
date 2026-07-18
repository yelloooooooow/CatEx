"""Versioned reaction-network identities and explicit review gates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from catex.models import Diagnostic, Severity


class ReactionNetworkReviewDecision(StrEnum):
    """Explicit human decision for one immutable reaction network."""

    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class NetworkStateEntry:
    """State identity included in a reaction network."""

    state_id: str
    state_identity_sha256: str

    def to_dict(self) -> dict[str, str]:
        return {
            "state_id": self.state_id,
            "state_identity_sha256": self.state_identity_sha256,
        }


@dataclass(frozen=True, slots=True)
class NetworkReactionEntry:
    """Balanced reaction identity and directed state connectivity."""

    reaction_id: str
    reaction_identity_sha256: str
    reactant_state_ids: tuple[str, ...]
    product_state_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "reaction_id": self.reaction_id,
            "reaction_identity_sha256": self.reaction_identity_sha256,
            "reactant_state_ids": list(self.reactant_state_ids),
            "product_state_ids": list(self.product_state_ids),
        }


@dataclass(frozen=True, slots=True)
class ReactionNetwork:
    """Connected directed network of immutable balanced reactions."""

    network_id: str
    states: tuple[NetworkStateEntry, ...]
    reactions: tuple[NetworkReactionEntry, ...]
    required_start_state_ids: tuple[str, ...]
    required_terminal_state_ids: tuple[str, ...]
    connected_component_count: int
    identity_sha256: str
    all_required_terminals_reachable: bool = True
    manual_review_required: bool = True
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.reaction-network.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "network_id": self.network_id,
            "states": [item.to_dict() for item in self.states],
            "reactions": [item.to_dict() for item in self.reactions],
            "required_start_state_ids": list(self.required_start_state_ids),
            "required_terminal_state_ids": list(self.required_terminal_state_ids),
            "connected_component_count": self.connected_component_count,
            "all_required_terminals_reachable": self.all_required_terminals_reachable,
            "identity_sha256": self.identity_sha256,
            "manual_review_required": self.manual_review_required,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }


@dataclass(frozen=True, slots=True)
class ReactionNetworkReport:
    """Fail-closed reaction-network construction result."""

    network_id: str
    network: ReactionNetwork | None
    diagnostics: tuple[Diagnostic, ...]
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.reaction-network-report.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def status(self) -> str:
        return "review_required" if self.network is not None and not self.has_errors else "error"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "network_id": self.network_id,
            "network": self.network.to_dict() if self.network else None,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }


@dataclass(frozen=True, slots=True)
class ReactionNetworkReview:
    """Human review bound to one immutable reaction-network hash."""

    decision: ReactionNetworkReviewDecision
    network_id: str
    network_identity_sha256: str
    reviewer: str
    reviewed_at_utc: str
    note: str
    review_sha256: str
    human_review_recorded: bool = True
    automatic_approval_performed: bool = False
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.reaction-network-review.v1"

    @property
    def approved(self) -> bool:
        return self.decision is ReactionNetworkReviewDecision.APPROVED

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision": self.decision.value,
            "approved": self.approved,
            "network_id": self.network_id,
            "network_identity_sha256": self.network_identity_sha256,
            "reviewer": self.reviewer,
            "reviewed_at_utc": self.reviewed_at_utc,
            "note": self.note,
            "review_sha256": self.review_sha256,
            "human_review_recorded": self.human_review_recorded,
            "automatic_approval_performed": self.automatic_approval_performed,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }


@dataclass(frozen=True, slots=True)
class ReactionNetworkReadinessReport:
    """Unique-approval gate before a network can drive calculation planning."""

    network_id: str
    network_identity_sha256: str
    ready_for_pathway_planning: bool
    accepted_review_sha256: str | None
    diagnostics: tuple[Diagnostic, ...]
    execution_authorized: bool = False
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.reaction-network-readiness.v1"

    @property
    def status(self) -> str:
        return "ready" if self.ready_for_pathway_planning else "blocked"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "network_id": self.network_id,
            "network_identity_sha256": self.network_identity_sha256,
            "ready_for_pathway_planning": self.ready_for_pathway_planning,
            "accepted_review_sha256": self.accepted_review_sha256,
            "execution_authorized": self.execution_authorized,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }
