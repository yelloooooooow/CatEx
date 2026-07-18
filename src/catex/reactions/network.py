"""Deterministic reaction-network construction and explicit review gates."""

from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any

from catex.models import Diagnostic, Severity
from catex.reactions.core import is_intact_reaction_definition
from catex.reactions.models import ReactionDefinition
from catex.reactions.network_models import (
    NetworkReactionEntry,
    NetworkStateEntry,
    ReactionNetwork,
    ReactionNetworkReadinessReport,
    ReactionNetworkReport,
    ReactionNetworkReview,
    ReactionNetworkReviewDecision,
)

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _identifier(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field} must be a safe identifier of at most 100 characters")
    return value


def _one_line(value: str, *, field: str, maximum: int) -> str:
    if not isinstance(value, str) or any(character in value for character in "\r\n"):
        raise ValueError(f"{field} must be one line")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field} must be non-empty and at most {maximum} characters")
    return normalized


def _timestamp(value: str) -> None:
    if not isinstance(value, str) or _UTC_TIMESTAMP.fullmatch(value) is None:
        raise ValueError("reviewed_at_utc must use YYYY-MM-DDTHH:MM:SSZ")
    try:
        datetime.strptime(value, _UTC_FORMAT)
    except ValueError as exc:
        raise ValueError("reviewed_at_utc must be a valid UTC timestamp") from exc


def _network_payload(network: ReactionNetwork) -> dict[str, Any]:
    return {
        "schema": "catex.reaction-network-content.v1",
        "network_id": network.network_id,
        "states": [item.to_dict() for item in network.states],
        "reactions": [item.to_dict() for item in network.reactions],
        "required_start_state_ids": list(network.required_start_state_ids),
        "required_terminal_state_ids": list(network.required_terminal_state_ids),
        "connected_component_count": network.connected_component_count,
        "all_required_terminals_reachable": network.all_required_terminals_reachable,
    }


def _components(state_ids: set[str], undirected: dict[str, set[str]]) -> int:
    remaining = set(state_ids)
    count = 0
    while remaining:
        count += 1
        queue = deque((next(iter(remaining)),))
        while queue:
            state = queue.popleft()
            if state not in remaining:
                continue
            remaining.remove(state)
            queue.extend(undirected[state] & remaining)
    return count


def _reachable(starts: tuple[str, ...], directed: dict[str, set[str]]) -> set[str]:
    reached = set(starts)
    queue = deque(starts)
    while queue:
        state = queue.popleft()
        for target in directed[state]:
            if target not in reached:
                reached.add(target)
                queue.append(target)
    return reached


def create_reaction_network(
    reactions: Sequence[ReactionDefinition],
    *,
    network_id: str,
    required_start_state_ids: Sequence[str] = (),
    required_terminal_state_ids: Sequence[str] = (),
) -> ReactionNetworkReport:
    """Create a deterministic network from intact balanced reaction definitions."""

    network_id_value = _identifier(network_id, field="network_id")
    candidates = tuple(reactions)
    diagnostics: list[Diagnostic] = []
    if not candidates or any(not is_intact_reaction_definition(item) for item in candidates):
        diagnostics.append(
            Diagnostic(
                "REACTION_NETWORK_MEMBER_INVALID",
                Severity.ERROR,
                "A network requires non-empty intact balanced reaction definitions.",
            )
        )
        return ReactionNetworkReport(network_id_value, None, tuple(diagnostics))
    reaction_ids = [item.reaction_id for item in candidates]
    if len(set(reaction_ids)) != len(reaction_ids):
        diagnostics.append(
            Diagnostic(
                "REACTION_NETWORK_REACTION_ID_DUPLICATE",
                Severity.ERROR,
                "Reaction IDs must be unique within a network.",
            )
        )
    state_hashes: dict[str, str] = {}
    entries: list[NetworkReactionEntry] = []
    for reaction in candidates:
        reactants = tuple(
            sorted(item.state_id for item in reaction.terms if item.coefficient.fraction < 0)
        )
        products = tuple(
            sorted(item.state_id for item in reaction.terms if item.coefficient.fraction > 0)
        )
        for term in reaction.terms:
            existing = state_hashes.setdefault(term.state_id, term.state_identity_sha256)
            if existing != term.state_identity_sha256:
                diagnostics.append(
                    Diagnostic(
                        "REACTION_NETWORK_STATE_IDENTITY_CONFLICT",
                        Severity.ERROR,
                        "One state ID refers to multiple immutable state identities.",
                        {"state_id": term.state_id},
                    )
                )
        entries.append(
            NetworkReactionEntry(
                reaction_id=reaction.reaction_id,
                reaction_identity_sha256=reaction.identity_sha256,
                reactant_state_ids=reactants,
                product_state_ids=products,
            )
        )
    starts = tuple(sorted(required_start_state_ids))
    terminals = tuple(sorted(required_terminal_state_ids))
    if (
        len(set(starts)) != len(starts)
        or len(set(terminals)) != len(terminals)
        or any(_IDENTIFIER.fullmatch(item) is None for item in (*starts, *terminals))
    ):
        raise ValueError("required start and terminal state IDs must be unique safe identifiers")
    if terminals and not starts:
        raise ValueError("required terminal states require at least one required start state")
    unknown = (set(starts) | set(terminals)) - set(state_hashes)
    if unknown:
        diagnostics.append(
            Diagnostic(
                "REACTION_NETWORK_REQUIRED_STATE_MISSING",
                Severity.ERROR,
                "A required start or terminal state is absent from the network.",
                {"state_ids": sorted(unknown)},
            )
        )
    undirected = {state_id: set() for state_id in state_hashes}
    directed = {state_id: set() for state_id in state_hashes}
    for entry in entries:
        for reactant in entry.reactant_state_ids:
            for product in entry.product_state_ids:
                directed[reactant].add(product)
                undirected[reactant].add(product)
                undirected[product].add(reactant)
    component_count = _components(set(state_hashes), undirected) if state_hashes else 0
    if component_count != 1:
        diagnostics.append(
            Diagnostic(
                "REACTION_NETWORK_DISCONNECTED",
                Severity.ERROR,
                "The reaction network must contain exactly one connected component.",
                {"connected_component_count": component_count},
            )
        )
    reachable = _reachable(starts, directed) if starts and not unknown else set()
    unreachable_terminals = set(terminals) - reachable
    if unreachable_terminals:
        diagnostics.append(
            Diagnostic(
                "REACTION_NETWORK_TERMINAL_UNREACHABLE",
                Severity.ERROR,
                "Every required terminal must be directionally reachable from a required start.",
                {"state_ids": sorted(unreachable_terminals)},
            )
        )
    if diagnostics:
        return ReactionNetworkReport(network_id_value, None, tuple(diagnostics))
    state_entries = tuple(
        NetworkStateEntry(state_id, state_hash)
        for state_id, state_hash in sorted(state_hashes.items())
    )
    reaction_entries = tuple(sorted(entries, key=lambda item: item.reaction_id))
    provisional = ReactionNetwork(
        network_id=network_id_value,
        states=state_entries,
        reactions=reaction_entries,
        required_start_state_ids=starts,
        required_terminal_state_ids=terminals,
        connected_component_count=component_count,
        identity_sha256="0" * 64,
    )
    network = replace(provisional, identity_sha256=_digest(_network_payload(provisional)))
    return ReactionNetworkReport(network_id_value, network, ())


def _valid_network(network: object) -> bool:
    try:
        state_ids = {item.state_id for item in network.states}
        undirected = {state_id: set() for state_id in state_ids}
        directed = {state_id: set() for state_id in state_ids}
        connections_valid = True
        for entry in network.reactions:
            reactants = set(entry.reactant_state_ids)
            products = set(entry.product_state_ids)
            connections_valid = connections_valid and bool(reactants) and bool(products)
            connections_valid = connections_valid and not (reactants & products)
            connections_valid = connections_valid and (reactants | products) <= state_ids
            for reactant in reactants:
                for product in products:
                    directed[reactant].add(product)
                    undirected[reactant].add(product)
                    undirected[product].add(reactant)
        starts = tuple(network.required_start_state_ids)
        terminals = tuple(network.required_terminal_state_ids)
        component_count = _components(state_ids, undirected) if state_ids else 0
        reachable = _reachable(starts, directed) if starts else set()
        return (
            isinstance(network, ReactionNetwork)
            and network.schema_version == "catex.reaction-network.v1"
            and _IDENTIFIER.fullmatch(network.network_id) is not None
            and bool(network.states)
            and bool(network.reactions)
            and tuple(sorted(network.states, key=lambda item: item.state_id)) == network.states
            and tuple(sorted(network.reactions, key=lambda item: item.reaction_id))
            == network.reactions
            and len({item.state_id for item in network.states}) == len(network.states)
            and len({item.reaction_id for item in network.reactions}) == len(network.reactions)
            and all(_IDENTIFIER.fullmatch(item.state_id) for item in network.states)
            and all(_IDENTIFIER.fullmatch(item.reaction_id) for item in network.reactions)
            and all(_SHA256.fullmatch(item.state_identity_sha256) for item in network.states)
            and all(_SHA256.fullmatch(item.reaction_identity_sha256) for item in network.reactions)
            and connections_valid
            and starts == tuple(sorted(set(starts)))
            and terminals == tuple(sorted(set(terminals)))
            and set(starts) <= state_ids
            and set(terminals) <= state_ids
            and (not terminals or bool(starts))
            and set(terminals) <= reachable
            and network.connected_component_count == component_count == 1
            and network.all_required_terminals_reachable
            and _SHA256.fullmatch(network.identity_sha256) is not None
            and network.identity_sha256 == _digest(_network_payload(network))
            and network.manual_review_required
            and not network.writes_performed
            and not network.commands_executed
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _review_payload(review: ReactionNetworkReview) -> dict[str, Any]:
    return {
        "schema": "catex.reaction-network-review-content.v1",
        "decision": review.decision.value,
        "network_id": review.network_id,
        "network_identity_sha256": review.network_identity_sha256,
        "reviewer": review.reviewer,
        "reviewed_at_utc": review.reviewed_at_utc,
        "note": review.note,
    }


def record_reaction_network_review(
    network: ReactionNetwork,
    *,
    accepted: bool,
    reviewer: str,
    reviewed_at_utc: str,
    note: str,
) -> ReactionNetworkReview:
    """Record one explicit review without mutating the network or executing work."""

    if not _valid_network(network):
        raise ValueError("network must be an intact ReactionNetwork")
    if not isinstance(accepted, bool):
        raise ValueError("accepted must be a boolean")
    _timestamp(reviewed_at_utc)
    provisional = ReactionNetworkReview(
        decision=(
            ReactionNetworkReviewDecision.APPROVED
            if accepted
            else ReactionNetworkReviewDecision.REJECTED
        ),
        network_id=network.network_id,
        network_identity_sha256=network.identity_sha256,
        reviewer=_one_line(reviewer, field="reviewer", maximum=100),
        reviewed_at_utc=reviewed_at_utc,
        note=_one_line(note, field="note", maximum=500),
        review_sha256="0" * 64,
    )
    return replace(provisional, review_sha256=_digest(_review_payload(provisional)))


def _valid_review(review: object, network: ReactionNetwork) -> bool:
    try:
        return (
            isinstance(review, ReactionNetworkReview)
            and review.schema_version == "catex.reaction-network-review.v1"
            and isinstance(review.decision, ReactionNetworkReviewDecision)
            and review.network_id == network.network_id
            and review.network_identity_sha256 == network.identity_sha256
            and _SHA256.fullmatch(review.review_sha256) is not None
            and review.review_sha256 == _digest(_review_payload(review))
            and review.human_review_recorded
            and not review.automatic_approval_performed
            and not review.writes_performed
            and not review.commands_executed
        )
    except (AttributeError, TypeError, ValueError):
        return False


def assess_reaction_network_readiness(
    network: ReactionNetwork,
    reviews: Sequence[ReactionNetworkReview],
) -> ReactionNetworkReadinessReport:
    """Require exactly one valid approval before pathway planning, never execution."""

    diagnostics: list[Diagnostic] = []
    intact = _valid_network(network)
    if not intact:
        diagnostics.append(
            Diagnostic(
                "REACTION_NETWORK_INVALID",
                Severity.ERROR,
                "The reaction-network content or identity hash is invalid.",
            )
        )
    bound = tuple(review for review in reviews if intact and _valid_review(review, network))
    approved = tuple(
        review for review in bound if review.decision is ReactionNetworkReviewDecision.APPROVED
    )
    if len(bound) != 1 or len(approved) != 1:
        diagnostics.append(
            Diagnostic(
                "REACTION_NETWORK_APPROVAL_MISSING_OR_AMBIGUOUS",
                Severity.ERROR,
                "Exactly one valid reaction-network approval is required.",
                {"bound_review_count": len(bound), "valid_approval_count": len(approved)},
            )
        )
    ready = intact and not diagnostics
    return ReactionNetworkReadinessReport(
        network_id=network.network_id,
        network_identity_sha256=network.identity_sha256,
        ready_for_pathway_planning=ready,
        accepted_review_sha256=approved[0].review_sha256 if ready else None,
        diagnostics=tuple(diagnostics),
    )
