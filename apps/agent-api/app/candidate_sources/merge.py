"""Merge and deduplicate candidate cards across sources.

A physical person may appear as several Boond records and/or a LinkedIn
profile. This module collapses cards that are the SAME person on strong,
deterministic evidence only:

- a shared canonical LinkedIn URL (the strongest cross-source key), or
- an identical Boond id.

It never merges on name alone (homonyms), matching the SIJO identity rule.
When a Boond card and a LinkedIn card share a canonical LinkedIn URL, they are
merged into one card carrying both sources; the Boond card (richer data) is the
base, enriched with the external SIJO qualification.

Pure functions — order-preserving (highest-ranked card wins the slot).
"""

from __future__ import annotations

from app.candidate_sources.linkedin_web.url_utils import canonical_identifier
from app.models.api import CandidateCard


def _url_key(card: CandidateCard) -> str | None:
    if not card.linkedin_url:
        return None
    return canonical_identifier(card.linkedin_url) or card.linkedin_url


def _merge_into(base: CandidateCard, other: CandidateCard) -> None:
    """Fold ``other`` into ``base`` in place (base keeps its slot/order)."""
    for src in other.sources:
        if src not in base.sources:
            base.sources.append(src)
    for bid in other.boond_ids:
        if bid not in base.boond_ids:
            base.boond_ids.append(bid)
    base.linkedin_url = base.linkedin_url or other.linkedin_url
    # Carry the external SIJO qualification onto the (richer) Boond base when
    # the base does not already have it.
    if base.consulting_status is None:
        base.consulting_status = other.consulting_status
    if base.long_mission_status is None:
        base.long_mission_status = other.long_mission_status
    if base.longest_mission_months is None:
        base.longest_mission_months = other.longest_mission_months
    if not base.external_evidence:
        base.external_evidence = other.external_evidence
    # Fill only genuinely-missing scalars from the external card.
    base.location = base.location or other.location
    if not base.skills:
        base.skills = other.skills


def merge_candidate_cards(cards: list[CandidateCard]) -> list[CandidateCard]:
    """Return cards with same-person duplicates merged (strong evidence only)."""
    merged: list[CandidateCard] = []
    by_url: dict[str, CandidateCard] = {}
    by_id: dict[str, CandidateCard] = {}

    for card in cards:
        url_key = _url_key(card)
        existing = None
        if url_key is not None and url_key in by_url:
            existing = by_url[url_key]
        elif card.id and card.id in by_id:
            existing = by_id[card.id]

        if existing is not None:
            _merge_into(existing, card)
            # Keep the merged card indexed under both keys.
            if url_key is not None:
                by_url[url_key] = existing
            continue

        merged.append(card)
        if url_key is not None:
            by_url[url_key] = card
        if card.id:
            by_id.setdefault(card.id, card)

    return merged
