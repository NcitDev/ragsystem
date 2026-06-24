import asyncio
from qdrant_client import AsyncQdrantClient
from rag.config import get_settings
from rag.core.vectorstore import PAYLOAD_INDEXES

async def main():
    s = get_settings()
    path = str(s.qdrant.resolved_path)
    print("qdrant path:", path)
    client = AsyncQdrantClient(path=path)
    cols = [c.name for c in (await client.get_collections()).collections]
    print("collections:", cols)
    for coll in cols:
        n = 0
        for field, schema in PAYLOAD_INDEXES:
            try:
                await client.create_payload_index(collection_name=coll, field_name=field, field_schema=schema)
                n += 1
            except Exception as e:
                pass
        print(f"  {coll}: created/ensured {n} payload indexes")
    await client.close()

asyncio.run(main())
