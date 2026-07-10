"""Terminal helper: fetch a candidate's data (detail + tech doc + CV) via MCP.

Connects directly to the running MCP BoondManager server (NOT through the
FastAPI agent) and dumps the raw tool results, so you can verify what data —
including the extracted CV text — BoondManager actually returns for a candidate.

Usage (from apps/agent-api, with the MCP server running):

    # default MCP URL is http://localhost:8080/mcp
    python scripts/fetch_candidate.py <candidate_id>

    # find the id by name first, then fetch everything for the single match
    python scripts/fetch_candidate.py --name "Ziaad Benamar"

    # just list candidates matching a name (no fetch)
    python scripts/fetch_candidate.py --search "Houssame"

    # custom MCP URL
    python scripts/fetch_candidate.py <candidate_id> --url http://localhost:8001/mcp

    # only the CV
    python scripts/fetch_candidate.py <candidate_id> --only cv

The MCP server must be running and configured with a valid
BOONDMANAGER_JWT_CLIENT token, otherwise the calls will fail / return no CV.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from app.agents.agent1.normalizer import (
    NORM_CONFLICTS,
    NORM_EXPERIENCE_SOURCE,
    NORM_EXPERIENCE_YEARS,
    _all_qualified_years,
    _estimate_years_from_graduation,
    _sum_experience_durations,
    normalize_candidate,
)
from app.mcp.remote_client import RemoteMcpClient
from app.models.results import SearchResult

# Tool names exposed by the MCP BoondManager server.
TOOLS = {
    "detail": "getCandidateDetail",
    "techdoc": "getCandidateTechnicalDocument",
    "cv": "getCandidateCV",
}

DEFAULT_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8080/mcp")


def _id_inputs(candidate_id: str) -> dict[str, object]:
    """Most MCP candidate tools accept `candidateId` (int when possible)."""
    try:
        value: int | str = int(candidate_id)
    except (TypeError, ValueError):
        value = candidate_id
    return {"candidateId": value}


def _print_section(title: str, payload: object) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _extract_id(record: object) -> str | None:
    """Best-effort id extraction from a search result record."""
    if not isinstance(record, dict):
        return None
    for key in ("id", "candidateId", "_id"):
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    data = record.get("data")
    if isinstance(data, dict):
        return _extract_id(data)
    return None


def _summarise(record: object) -> str:
    if not isinstance(record, dict):
        return str(record)
    cid = _extract_id(record)
    name = (
        record.get("fullName")
        or " ".join(
            str(record.get(k, "")).strip()
            for k in ("firstName", "lastName")
        ).strip()
        or record.get("title")
        or "?"
    )
    title = record.get("title") or record.get("jobTitle") or ""
    return f"id={cid}  {name}  — {title}".strip()


async def _search(client: RemoteMcpClient, name: str) -> list[dict[str, object]]:
    """Search candidates by name; try several keyword fields until one hits.

    A single token (e.g. "Ziaad") may be a first or last name, so we probe
    fullName → lastName → firstName and return the first non-empty result set.
    """
    seen: dict[str, dict[str, object]] = {}
    for kw_type in ("fullName", "lastName", "firstName"):
        results = await client.call_tool(
            "searchCandidates",
            {"keywords": name, "keywordsType": kw_type, "maxResults": 25},
        )
        records = [r for r in results if isinstance(r, dict)]
        if records:
            print(f"  (matched via keywordsType={kw_type})")
            for rec in records:
                cid = _extract_id(rec) or str(id(rec))
                seen.setdefault(cid, rec)
            break
    return list(seen.values())


async def _fetch_all(client: RemoteMcpClient, candidate_id: str, only: str | None) -> int:
    inputs = _id_inputs(candidate_id)
    selected = [only] if only else ["detail", "techdoc", "cv"]
    exit_code = 0
    for key in selected:
        tool = TOOLS[key]
        try:
            result = await client.call_tool(tool, inputs)
            _print_section(f"{tool}  (candidateId={inputs['candidateId']})", result)
        except Exception as exc:  # noqa: BLE001 — terminal diagnostic tool
            exit_code = 1
            _print_section(f"{tool}  -> ERROR", f"{type(exc).__name__}: {exc}")
    return exit_code


_EXP_SOURCE_LABELS = {
    "cv": "Année clairement écrite dans le CV",
    "cv_durations": "Somme des durées de postes du CV (durées explicites ou plages de dates)",
    "boondmanager": "Champ structuré BoondManager (experienceMinYears)",
    "experience_level": "Niveau d'expérience BoondManager (label du dictionnaire)",
    "technical_document": "Mention dans le dossier technique",
    "profile_text": "Mention dans le titre / résumé du profil",
    "graduation": "Estimé depuis l'année de diplôme (année actuelle − fin d'études)",
    "llm": "Arbitrage IA (réconciliation des sources)",
}


async def _explain_experience(client: RemoteMcpClient, candidate_id: str) -> int:
    """Fetch a candidate and explain how Agent1 computed its years of experience."""
    inputs = _id_inputs(candidate_id)

    async def _one(tool_key: str) -> dict | None:
        try:
            records = await client.call_tool(TOOLS[tool_key], inputs)
            return records[0] if records and isinstance(records[0], dict) else None
        except Exception as exc:  # noqa: BLE001
            print(f"  ({TOOLS[tool_key]} a échoué : {type(exc).__name__}: {exc})")
            return None

    detail = await _one("detail")
    techdoc = await _one("techdoc")
    cv = await _one("cv")

    data: dict[str, object] = dict(detail) if detail else {}
    if techdoc:
        data["_enrichment_technical_document"] = techdoc
    if cv and cv.get("hasContent"):
        data["_enrichment_resume"] = cv

    title = str(data.get("title") or "")
    result = SearchResult(
        id=str(candidate_id), type="candidate", title=title, score=1.0,
        source_tool="searchCandidates", data=data,
    )
    out = normalize_candidate(result)
    d = out.data

    years = d.get(NORM_EXPERIENCE_YEARS)
    source = d.get(NORM_EXPERIENCE_SOURCE)
    conflicts = d.get(NORM_CONFLICTS) or []

    # Inputs that fed the decision.
    min_years = None
    if isinstance(techdoc, dict):
        min_years = techdoc.get("experienceMinYears")
    cv_text = (cv or {}).get("extractedText") or "" if isinstance(cv, dict) else ""
    td_text = " ".join(
        str(techdoc.get(f)) for f in ("title", "summary", "description", "text", "skills")
        if isinstance(techdoc, dict) and isinstance(techdoc.get(f), str)
    )
    cv_figures = sorted(_all_qualified_years(cv_text)) if cv_text else []
    td_figures = sorted(_all_qualified_years(td_text)) if td_text else []
    grad_estimate = _estimate_years_from_graduation(data)
    duration_sum = _sum_experience_durations(data)

    print("\n" + "=" * 70)
    print(f"EXPLICATION — expérience de {title or candidate_id} (id={candidate_id})")
    print("=" * 70)
    print(f"\n➡  RÉSULTAT : {years if years is not None else 'Non renseigné'} an(s)")
    print(f"   Source retenue : {source or 'aucune'} — "
          f"{_EXP_SOURCE_LABELS.get(source, 'n/a')}")
    if d.get("_experienceLabel"):
        print(f"   Niveau structuré (fourchette) : {d.get('_experienceLabel')}")
    print(f"\n   Conflits détectés : {conflicts or 'aucun'}")
    print("\n   Sources examinées :")
    print(f"   • experienceMinYears (BoondManager) : {min_years!r}")
    print(f"   • Années 'd'expérience' trouvées dans le CV       : {cv_figures or '—'}")
    print(f"   • Années 'd'expérience' dans le dossier technique : {td_figures or '—'}")
    print(f"   • Estimation par année de diplôme                 : "
          f"{grad_estimate if grad_estimate is not None else '—'}")
    print(f"   • Somme des durées d'expériences (CV)             : "
          f"{duration_sum if duration_sum is not None else '—'}")
    if source == "graduation":
        print("\n   → Aucune année explicite exploitable : calcul basé sur le diplôme.")
    print()
    return 0


async def _run(
    candidate_id: str | None,
    url: str,
    only: str | None,
    name: str | None,
    search_only: str | None,
    explain: bool = False,
) -> int:
    client = RemoteMcpClient(url=url, timeout_seconds=30.0)

    query = name or search_only
    if query:
        try:
            matches = await _search(client, query)
        except Exception as exc:  # noqa: BLE001
            _print_section("searchCandidates -> ERROR", f"{type(exc).__name__}: {exc}")
            return 1

        print(f"\n{len(matches)} match(es) for {query!r}:")
        for rec in matches:
            print("  - " + _summarise(rec))

        if search_only:
            return 0
        if not matches:
            print("\nNo candidate found — refine the name.")
            return 1
        if len(matches) > 1:
            print(
                "\nMultiple matches. Re-run with the exact id:\n"
                "  python scripts/fetch_candidate.py <id>"
            )
            return 0
        candidate_id = _extract_id(matches[0])
        if not candidate_id:
            print("\nCould not extract an id from the single match.")
            return 1
        print(f"\nSingle match → fetching candidate id={candidate_id} ...")

    if not candidate_id:
        print("No candidate id provided.")
        return 2
    if explain:
        return await _explain_experience(client, candidate_id)
    return await _fetch_all(client, candidate_id, only)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch candidate data via MCP.")
    parser.add_argument(
        "candidate_id", nargs="?", default=None, help="BoondManager candidate id"
    )
    parser.add_argument(
        "--name", default=None,
        help="Find candidate by full name, then fetch all data for the single match",
    )
    parser.add_argument(
        "--search", default=None,
        help="Only list candidates matching this name (no detail/CV fetch)",
    )
    parser.add_argument(
        "--url", default=DEFAULT_URL, help=f"MCP server URL (default: {DEFAULT_URL})"
    )
    parser.add_argument(
        "--only",
        choices=sorted(TOOLS.keys()),
        default=None,
        help="Fetch only one of: detail, techdoc, cv",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Explain how Agent1 computed the candidate's years of experience",
    )
    args = parser.parse_args()
    if not (args.candidate_id or args.name or args.search):
        parser.error("provide a candidate_id, or --name, or --search")
    # Windows consoles default to cp1252 and choke on Unicode (→, •, …).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    print(f"MCP URL: {args.url}")
    return asyncio.run(
        _run(args.candidate_id, args.url, args.only, args.name, args.search, args.explain)
    )


if __name__ == "__main__":
    sys.exit(main())
