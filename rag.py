"""
GraphRAG query pipeline:
  1. Embed the user query (same provider used at ingestion time).
  2. Vector search over :Chunk.embedding in Neo4j -> seed chunks.
  3. Graph expansion: walk MENTIONS -> Entity -> RELATES_TO -> Entity <- MENTIONS
     to pull in connected chunks that plain vector similarity would miss.
  4. Optionally pull sequential neighbor chunks (:NEXT) for local continuity.
  5. Assemble a context block and ask Gemini to answer, grounded only in
     the retrieved context.

Run:
    python rag.py --query "How are X and Y related?"
"""

import os
import argparse
from dotenv import load_dotenv

from embeddings import get_embedder
from graph_store import Neo4jGraphStore

load_dotenv()


def build_context(seed_chunks, graph_rows, neighbor_texts_by_chunk):
    lines = ["### Retrieved chunks (vector similarity):"]
    for c in seed_chunks:
        lines.append(f"- [{c['id']}] {c['text']}")

    if neighbor_texts_by_chunk:
        lines.append("\n### Neighboring context (sequential):")
        for cid, neighbors in neighbor_texts_by_chunk.items():
            for n in neighbors:
                if n:
                    lines.append(f"- (near {cid}) {n}")

    if graph_rows:
        lines.append("\n### Graph-connected context (entities & relations):")
        seen = set()
        for row in graph_rows:
            key = (row.get("entity"), row.get("related_entity"), row.get("related_chunk_id"))
            if key in seen or not row.get("related_entity"):
                continue
            seen.add(key)
            snippet = f"- {row['entity']} --related_to--> {row['related_entity']}"
            if row.get("related_chunk_text"):
                snippet += f" | supporting text: {row['related_chunk_text'][:300]}"
            lines.append(snippet)

    return "\n".join(lines)


def answer_query(query: str, top_k: int = 5, graph_hops: int = 1, provider: str = None,
                  neighbor_window: int = 0, llm_model: str = None) -> str:
    embedder = get_embedder(provider)
    store = Neo4jGraphStore()

    query_vec = embedder.embed_query(query)
    seed_chunks = store.vector_search(query_vec, top_k=top_k)

    chunk_ids = [c["id"] for c in seed_chunks]
    graph_rows = store.expand_graph_context(chunk_ids, hops=graph_hops) if chunk_ids else []

    neighbor_texts_by_chunk = {}
    if neighbor_window > 0:
        for cid in chunk_ids:
            neighbor_texts_by_chunk[cid] = store.get_neighboring_chunks(cid, window=neighbor_window)

    store.close()

    context = build_context(seed_chunks, graph_rows, neighbor_texts_by_chunk)

    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = f"""You are a helpful assistant answering questions using ONLY the context below,
which was retrieved from a knowledge graph (vector similarity + graph traversal over entities/relations).
If the context is insufficient, say so honestly instead of guessing.

{context}

Question: {query}

Answer clearly and cite which retrieved chunk id(s) support each claim, e.g. [chunk_id]."""

    resp = client.models.generate_content(
        model=llm_model or os.environ.get("GEMINI_LLM_MODEL", "gemini-2.5-flash"),
        contents=prompt,
    )
    return resp.text


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--graph-hops", type=int, default=1)
    parser.add_argument("--neighbor-window", type=int, default=0)
    parser.add_argument("--provider", choices=["gemini", "local", "local_docker"], default=None)
    args = parser.parse_args()

    answer = answer_query(
        args.query,
        top_k=args.top_k,
        graph_hops=args.graph_hops,
        provider=args.provider,
        neighbor_window=args.neighbor_window,
    )
    print("\n" + "=" * 80)
    print(answer)
    print("=" * 80)
