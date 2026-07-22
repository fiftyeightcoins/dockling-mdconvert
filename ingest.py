"""
Ingestion pipeline:
  1. Split raw text into chunks.
  2. Embed chunks (Gemini or local BGE, chosen via EMBEDDING_PROVIDER).
  3. Write Document/Chunk nodes + embeddings + :NEXT ordering to Neo4j.
  4. Extract simple entities per chunk with the Gemini LLM (cheap, free-tier
     model) and write Entity nodes + MENTIONS + RELATES_TO edges.

Run:
    python ingest.py --file mydoc.txt --doc-id doc1 --title "My Document"
"""

import os
import argparse
import json
import uuid
from dotenv import load_dotenv

from embeddings import get_embedder
from graph_store import Neo4jGraphStore

load_dotenv()


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 100):
    words = text.split()
    chunks = []
    step = chunk_size - overlap
    for i in range(0, len(words), step):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk.strip():
            chunks.append(chunk)
        if i + chunk_size >= len(words):
            break
    return chunks


def extract_entities_and_relations(text: str, model_name: str = None) -> dict:
    """
    Uses Gemini (free-tier) to pull a small entity/relation graph out of a chunk.
    Returns {"entities": [{"name","type"}], "relations": [{"source","target","type","description"}]}
    Falls back to an empty structure if the API/parsing fails, so ingestion
    never hard-fails on the entity step.
    """
    try:
        from google import genai
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        prompt = f"""Extract key entities and relationships from the text below.
Return ONLY valid JSON, no markdown fences, in this exact shape:
{{"entities": [{{"name": "...", "type": "Person|Org|Concept|Place|Other"}}],
  "relations": [{{"source": "...", "target": "...", "type": "...", "description": "..."}}]}}

Text:
\"\"\"{text}\"\"\"
"""
        resp = client.models.generate_content(
            model=model_name or os.environ.get("GEMINI_LLM_MODEL", "gemini-2.5-flash"),
            contents=prompt,
        )
        raw = resp.text.strip().strip("```").replace("json\n", "", 1) if resp.text else "{}"
        return json.loads(raw)
    except Exception as e:
        print(f"[entity extraction] skipped due to error: {e}")
        return {"entities": [], "relations": []}


def ingest_file(path: str, doc_id: str, title: str, provider: str = None, extract_entities: bool = True):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    embedder = get_embedder(provider)
    store = Neo4jGraphStore()
    store.create_constraints()
    store.create_vector_index(dimension=embedder.dimension)

    store.upsert_document(doc_id, title, source=path)

    chunks = chunk_text(text)
    print(f"Split into {len(chunks)} chunks. Embedding with provider={provider or os.environ.get('EMBEDDING_PROVIDER')}...")
    vectors = embedder.embed_documents(chunks)

    prev_id = None
    for chunk, vec in zip(chunks, vectors):
        chunk_id = f"{doc_id}::{uuid.uuid4().hex[:8]}"
        store.upsert_chunk(chunk_id, chunk, vec, doc_id, prev_chunk_id=prev_id)

        if extract_entities:
            graph = extract_entities_and_relations(chunk)
            for ent in graph.get("entities", []):
                store.upsert_entity(ent["name"], ent.get("type", "Entity"))
                store.link_chunk_mentions_entity(chunk_id, ent["name"])
            for rel in graph.get("relations", []):
                # ensure both endpoints exist as entities even if extraction missed one
                store.upsert_entity(rel["source"])
                store.upsert_entity(rel["target"])
                store.link_entities(rel["source"], rel["target"], rel.get("type", "RELATES_TO"), rel.get("description", ""))

        prev_id = chunk_id

    store.close()
    print(f"Ingestion complete for document '{doc_id}'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="Path to a .txt file to ingest")
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--provider", choices=["gemini", "local", "local_docker"], default=None,
                         help="Overrides EMBEDDING_PROVIDER env var")
    parser.add_argument("--no-entities", action="store_true", help="Skip LLM entity extraction (faster/cheaper)")
    args = parser.parse_args()

    ingest_file(args.file, args.doc_id, args.title or args.doc_id,
                provider=args.provider, extract_entities=not args.no_entities)
