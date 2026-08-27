"""Build index entries for candidates by reading their CVs through MCP.

MCP stays the only path to BoondManager data (see the Agent API
architecture boundaries): the indexer calls the same
``getCandidateTechnicalDocument`` / ``getCandidateCV`` tools the
enrichment node uses, then embeds the assembled document.

Two callers, one code path:

- the bulk indexing script, which walks every candidate;
- the on-the-fly catch-up during a search, which indexes the handful of
  candidates that were enriched but are not in the index yet.

Cost note: a full pass over ~26k candidates is ~52k MCP calls, each of
which makes BoondManager download and re-extract a PDF. Concurrency is
bounded and configurable for exactly that reason — this is a background
job, not something to run inside a request.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Final, Protocol

from app.rag.document import build_candidate_document
from app.rag.embeddings import EmbeddingClient, EmbeddingError
from app.rag.models import IndexedCandidate, content_hash

logger = logging.getLogger(__name__)

TECHNICAL_DOCUMENT_TOOL: Final[str] = "getCandidateTechnicalDocument"
RESUME_TOOL: Final[str] = "getCandidateCV"

# Keep only the fields a candidate card / pre-ranking actually reads, so
# the stored summary stays small (Table Storage entity budget) and never
# becomes a second, drifting copy of the candidate record.
_SUMMARY_FIELDS: Final[tuple[str, ...]] = (
    "id",
    "firstName",
    "lastName",
    "title",
    "skills",
    "city",
    "country",
    "experience",
    "experienceMinYears",
    "experienceOpenEnded",
    "experienceSpecified",
    "experienceLabelRaw",
    "expertiseAreas",
    "activityAreas",
    "tools",
    "diplomas",
    "languages",
    "state",
)


class SupportsCallTool(Protocol):
    async def call_tool(
        self, tool: str, inputs: dict[str, object]
    ) -> list[dict[str, object]]: ...


@dataclass(frozen=True)
class CandidatePayload:
    """Already-fetched material for one candidate.

    Lets the search path index a candidate from the payloads enrichment
    just downloaded, instead of asking MCP for the same CV a second time.
    """

    summary: dict[str, object]
    technical_document: dict[str, object] | None = None
    cv: dict[str, object] | None = None

    @property
    def candidate_id(self) -> str:
        return str(self.summary.get("id") or "").strip()


@dataclass
class IndexReport:
    """Outcome of one indexing pass."""

    seen: int = 0
    indexed: int = 0
    skipped_unchanged: int = 0
    skipped_empty: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)

    def merge(self, other: IndexReport) -> None:
        self.seen += other.seen
        self.indexed += other.indexed
        self.skipped_unchanged += other.skipped_unchanged
        self.skipped_empty += other.skipped_empty
        self.failed += other.failed
        self.failures.extend(other.failures)

    def as_dict(self) -> dict[str, object]:
        return {
            "seen": self.seen,
            "indexed": self.indexed,
            "skipped_unchanged": self.skipped_unchanged,
            "skipped_empty": self.skipped_empty,
            "failed": self.failed,
        }


def compact_summary(record: dict[str, object]) -> dict[str, object]:
    """Trim a search record down to the fields worth storing."""
    return {key: record[key] for key in _SUMMARY_FIELDS if key in record}


class CandidateIndexer:
    """Fetches CV material through MCP, embeds it, and writes the index."""

    def __init__(
        self,
        *,
        mcp_client: SupportsCallTool,
        embeddings: EmbeddingClient,
        store,
        concurrency: int = 6,
    ) -> None:
        self._mcp = mcp_client
        self._embeddings = embeddings
        self._store = store
        self._semaphore = asyncio.Semaphore(max(1, concurrency))

    async def build_entries(
        self,
        summaries: list[dict[str, object]],
        *,
        known_hashes: dict[str, str] | None = None,
    ) -> tuple[list[IndexedCandidate], IndexReport]:
        """Fetch CV material through MCP, then embed. For the bulk script.

        ``known_hashes`` (candidate id -> stored document hash) lets an
        incremental pass skip candidates whose CV material is unchanged,
        avoiding both the embedding call and the write.
        """
        report = IndexReport(seen=len(summaries))
        fetched = await asyncio.gather(
            *(self._fetch_payload(summary) for summary in summaries),
            return_exceptions=True,
        )

        payloads: list[CandidatePayload] = []
        for summary, outcome in zip(summaries, fetched):
            if isinstance(outcome, BaseException):
                report.failed += 1
                report.failures.append(
                    f"{summary.get('id')}: {outcome}"
                )
                continue
            payloads.append(outcome)

        entries, embed_report = await self.build_entries_from_payloads(
            payloads, known_hashes=known_hashes
        )
        # `seen` is already counted above; take the rest from the embed pass.
        embed_report.seen = 0
        report.merge(embed_report)
        return entries, report

    async def build_entries_from_payloads(
        self,
        payloads: list[CandidatePayload],
        *,
        known_hashes: dict[str, str] | None = None,
    ) -> tuple[list[IndexedCandidate], IndexReport]:
        """Embed already-fetched candidate material — no MCP calls.

        Used by the in-search catch-up, where enrichment has just
        downloaded the CV and technical document: re-fetching them would
        double the cost of every search for no new information.
        """
        report = IndexReport(seen=len(payloads))
        known = known_hashes or {}

        pending: list[tuple[CandidatePayload, str, str]] = []
        for payload in payloads:
            if not payload.candidate_id:
                report.skipped_empty += 1
                continue
            document = build_candidate_document(
                summary=payload.summary,
                technical_document=payload.technical_document,
                cv=payload.cv,
            )
            if not document:
                report.skipped_empty += 1
                continue
            digest = content_hash(document)
            if known.get(payload.candidate_id) == digest:
                report.skipped_unchanged += 1
                continue
            pending.append((payload, document, digest))

        if not pending:
            return [], report

        try:
            vectors = await self._embeddings.embed([doc for _, doc, _ in pending])
        except EmbeddingError as exc:
            report.failed += len(pending)
            report.failures.append(f"embedding batch failed: {exc}")
            return [], report

        entries = [
            IndexedCandidate(
                candidate_id=payload.candidate_id,
                vector=vector,
                summary=compact_summary(payload.summary),
                doc_hash=digest,
                model=self._embeddings.model,
                dims=len(vector),
            ).with_defaults()
            for (payload, _, digest), vector in zip(pending, vectors)
        ]
        report.indexed = len(entries)
        return entries, report

    async def index(
        self,
        summaries: list[dict[str, object]],
        *,
        known_hashes: dict[str, str] | None = None,
    ) -> tuple[list[IndexedCandidate], IndexReport]:
        """``build_entries`` + persist. Returns the entries actually written."""
        entries, report = await self.build_entries(
            summaries, known_hashes=known_hashes
        )
        if entries:
            await self._store.upsert_many(entries)
        return entries, report

    async def index_payloads(
        self,
        payloads: list[CandidatePayload],
        *,
        known_hashes: dict[str, str] | None = None,
    ) -> tuple[list[IndexedCandidate], IndexReport]:
        """``build_entries_from_payloads`` + persist."""
        entries, report = await self.build_entries_from_payloads(
            payloads, known_hashes=known_hashes
        )
        if entries:
            await self._store.upsert_many(entries)
        return entries, report

    async def _fetch_payload(self, summary: dict[str, object]) -> CandidatePayload:
        candidate_id = str(summary.get("id") or "").strip()
        if not candidate_id:
            return CandidatePayload(summary=summary)
        async with self._semaphore:
            tech_doc, cv = await asyncio.gather(
                self._call_one(TECHNICAL_DOCUMENT_TOOL, candidate_id),
                self._call_one(RESUME_TOOL, candidate_id),
            )
        return CandidatePayload(
            summary=summary, technical_document=tech_doc, cv=cv
        )

    async def _call_one(
        self, tool: str, candidate_id: str
    ) -> dict[str, object] | None:
        """One MCP call, degrading to None so a missing CV is not fatal.

        A candidate with no technical document (or no CV) is still worth
        indexing on the fields we do have; only a candidate with nothing
        at all is skipped, by ``build_candidate_document`` returning "".
        """
        try:
            records = await self._mcp.call_tool(tool, {"candidateId": candidate_id})
        except Exception as exc:  # noqa: BLE001 — one tool, one candidate
            logger.debug(
                "rag.indexer.tool_failed",
                extra={"tool": tool, "candidate_id": candidate_id, "error": str(exc)},
            )
            return None
        if records and isinstance(records[0], dict):
            return records[0]
        return None
