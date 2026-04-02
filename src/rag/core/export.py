"""Export and import Qdrant collection data for backup or sharing."""

from __future__ import annotations

import json
from pathlib import Path

import structlog

from rag.core.vectorstore import QdrantVectorStore, ChunkDocument

logger = structlog.get_logger()


async def export_collection(
    vectorstore: QdrantVectorStore, collection: str, output_path: str
) -> int:
    """Export collection to JSONL file. Returns point count.

    Includes payload but NOT vectors (too large).
    """
    client = await vectorstore._get_client()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    offset = None

    with open(out, "w", encoding="utf-8") as f:
        while True:
            results, next_offset = await client.scroll(
                collection_name=collection,
                offset=offset,
                limit=100,
                with_payload=True,
                with_vectors=False,
            )

            if not results:
                break

            for point in results:
                record = {
                    "id": str(point.id),
                    "payload": point.payload or {},
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1

            if next_offset is None:
                break
            offset = next_offset

    logger.info(
        "collection_exported",
        collection=collection,
        output_path=output_path,
        points=count,
    )
    return count


async def import_collection(
    vectorstore: QdrantVectorStore, collection: str, input_path: str
) -> int:
    """Import collection from JSONL file. Returns point count.

    Re-embeds content from payload and upserts to collection.
    """
    inp = Path(input_path)
    if not inp.exists():
        raise FileNotFoundError(f"Import file not found: {input_path}")

    documents: list[ChunkDocument] = []

    with open(inp, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            payload = record.get("payload", {})
            content = payload.pop("content", "")
            if not content:
                logger.warning("skipping_point_no_content", point_id=record.get("id"))
                continue
            documents.append(
                ChunkDocument(
                    content=content,
                    metadata=payload,
                    chunk_id=record.get("id"),
                )
            )

    if not documents:
        logger.warning("import_empty", input_path=input_path)
        return 0

    count = await vectorstore.upsert(collection, documents)

    logger.info(
        "collection_imported",
        collection=collection,
        input_path=input_path,
        points=count,
    )
    return count
