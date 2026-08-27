"""Bulk-index candidate CVs into the vector store (ADR-014).

Walks ``searchCandidates`` page by page, reads each candidate's CV and
technical document through MCP, embeds the assembled document, and
writes it to the configured vector store.

This is a **background job, not a request**: a full pass over ~26k
candidates issues ~52k MCP calls, each of which makes BoondManager
download and re-extract a PDF. Budget hours, run it off-peak, and keep
``--concurrency`` modest.

The run is **resumable and incremental**: candidates whose document
hash already matches the stored one are skipped without an embedding
call, so re-running after an interruption only does what is left.

Usage
-----
    # everything, resumable
    uv run python scripts/index_candidates.py

    # a first slice, to sanity-check quality before the full run
    uv run python scripts/index_candidates.py --limit 200

    # force re-embedding (e.g. after changing RAG_EMBEDDING_DIMS)
    uv run python scripts/index_candidates.py --force

Requires the same environment as the API: MCP_SERVER_URL / USE_MOCK_MCP
and RAG_* settings (see .env.example).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

# Allow `python scripts/index_candidates.py` from the app root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.settings import get_settings  # noqa: E402
from app.mcp.factory import create_mcp_client  # noqa: E402
from app.rag.factory import (  # noqa: E402
    create_embedding_client,
    create_vector_store,
)
from app.rag.indexer import CandidateIndexer, IndexReport  # noqa: E402

logger = logging.getLogger("index_candidates")

SEARCH_TOOL = "searchCandidates"
PAGE_SIZE = 100


async def _fetch_page(mcp_client, page: int, size: int) -> list[dict[str, object]]:
    records = await mcp_client.call_tool(
        SEARCH_TOOL, {"page": page, "maxResults": size}
    )
    return [record for record in records if isinstance(record, dict)]


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()

    mcp_client = create_mcp_client(settings)
    connect = getattr(mcp_client, "connect", None)
    if callable(connect):
        await connect()

    store = create_vector_store(settings)
    await store.initialize()
    embeddings = create_embedding_client(settings)
    indexer = CandidateIndexer(
        mcp_client=mcp_client,
        embeddings=embeddings,
        store=store,
        concurrency=args.concurrency,
    )

    known = {} if args.force else await store.get_hashes()
    print(
        f"store={settings.rag_store} model={settings.rag_embedding_model} "
        f"dims={settings.rag_embedding_dims} "
        f"deja_indexes={len(known)} concurrency={args.concurrency}"
    )

    total = IndexReport()
    started = time.monotonic()
    page = args.start_page
    processed = 0

    try:
        while True:
            if args.limit and processed >= args.limit:
                break
            summaries = await _fetch_page(mcp_client, page, PAGE_SIZE)
            if not summaries:
                print(f"page {page}: vide -> fin de la base")
                break
            if args.limit:
                summaries = summaries[: args.limit - processed]

            _, report = await indexer.index(summaries, known_hashes=known)
            total.merge(report)
            processed += len(summaries)

            elapsed = time.monotonic() - started
            rate = processed / elapsed if elapsed else 0.0
            print(
                f"page {page:4d} | vus {processed:6d} | indexes {total.indexed:6d} "
                f"| inchanges {total.skipped_unchanged:5d} "
                f"| sans contenu {total.skipped_empty:5d} "
                f"| echecs {total.failed:4d} | {rate:.1f} cand/s"
            )
            page += 1
    except KeyboardInterrupt:
        print("\ninterrompu — relancer la commande reprendra ou cela s'est arrete")
    finally:
        close = getattr(mcp_client, "aclose", None) or getattr(
            mcp_client, "close", None
        )
        if callable(close):
            result = close()
            if hasattr(result, "__await__"):
                await result
        await store.close()

    elapsed = time.monotonic() - started
    print()
    print(f"termine en {elapsed / 60:.1f} min : {total.as_dict()}")
    if total.failures:
        print(f"{len(total.failures)} echecs, 5 premiers :")
        for failure in total.failures[:5]:
            print(f"  - {failure}")
    return 1 if total.indexed == 0 and total.failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Candidats traites en parallele (defaut: RAG_INDEX_CONCURRENCY).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="S'arreter apres N candidats (0 = toute la base).",
    )
    parser.add_argument(
        "--start-page", type=int, default=1, help="Page de depart (1-based)."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-embarquer meme les candidats inchanges.",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if args.concurrency is None:
        args.concurrency = get_settings().rag_index_concurrency

    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
