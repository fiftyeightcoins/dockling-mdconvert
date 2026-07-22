"""
GraphRAG query pipeline for the oil-geopolitics Record graph (see ingest_csv.py).

Retrieval strategy:
  1. Embed the question, vector-search top-k :Record nodes.
  2. Graph expansion: for each seed Record, hop to its :Month and :Country
     nodes and pull in OTHER Records sharing that month or country — this
     surfaces e.g. sanctions/events/price moves that co-occurred in time or
     involved the same country, which plain vector similarity often misses.
  3. Assemble context (seed narratives + graph-connected narratives) and ask
     Gemini to answer, grounded only in that context, citing record ids.

Usage:
    python rag_csv.py --query "What happened to oil prices during the 2012 Iran sanctions?"
"""

import os
import argparse
from dotenv import load_dotenv

from embeddings import get_embedder
from graph_store import Neo4jGraphStore

load_dotenv()


def vector_search_records(store, query_vec, top_k):
    result = store.run("""
    CALL db.index.vector.queryNodes('record_embedding_index', $top_k, $embedding)
    YIELD node, score
    RETURN node.id AS id, node.type AS type, node.date AS date, node.narrative AS narrative, score
    ORDER BY score DESC
    """, top_k=top_k, embedding=query_vec)
    return [dict(r) for r in result]


def expand_via_month_and_country(store, record_ids, limit=20):
    result = store.run("""
    MATCH (r:Record) WHERE r.id IN $ids
    OPTIONAL MATCH (r)-[:IN_MONTH]->(m:Month)<-[:IN_MONTH]-(same_month:Record)
    WHERE same_month.id <> r.id
    OPTIONAL MATCH (r)-[:INVOLVES_COUNTRY]->(c:Country)<-[:INVOLVES_COUNTRY]-(same_country:Record)
    WHERE same_country.id <> r.id
    WITH r,
         collect(DISTINCT {id: same_month.id, type: same_month.type, date: same_month.date, narrative: same_month.narrative}) AS month_matches,
         collect(DISTINCT {id: same_country.id, type: same_country.type, date: same_country.date, narrative: same_country.narrative}) AS country_matches
    RETURN r.id AS seed_id, month_matches, country_matches
    """, ids=record_ids)
    return [dict(r) for r in result][:limit] if result else []


def build_context(seed_records, expansions):
    lines = ["### Directly relevant records (vector similarity):"]
    for r in seed_records:
        lines.append(f"- [{r['id']}] ({r['type']}, {r['date']}) {r['narrative']}")

    lines.append("\n### Graph-connected records (same month / same country as above):")
    seen = set()
    for exp in expansions:
        for group in ("month_matches", "country_matches"):
            for m in exp.get(group, []):
                if not m or not m.get("id") or m["id"] in seen:
                    continue
                seen.add(m["id"])
                lines.append(f"- [{m['id']}] ({m['type']}, {m['date']}) {m['narrative']}")

    return "\n".join(lines)


def answer_query(query: str, top_k: int = 6, provider: str = None, llm_model: str = None) -> str:
    embedder = get_embedder(provider)
    store = Neo4jGraphStore()

    query_vec = embedder.embed_query(query)
    seed_records = vector_search_records(store, query_vec, top_k)
    record_ids = [r["id"] for r in seed_records]
    expansions = expand_via_month_and_country(store, record_ids) if record_ids else []

    store.close()

    context = build_context(seed_records, expansions)

    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = f"""You are an analyst answering questions about oil markets and Iran-related
geopolitics using ONLY the context below, retrieved from a knowledge graph
(vector similarity over events/sanctions/exports/risk/price records, expanded
through shared month and country connections). If the context is insufficient,
say so honestly.

{context}

Question: {query}

Give a clear, well-organized answer. Cite record ids like [event_12] for each claim."""

    resp = client.models.generate_content(
        model=llm_model or os.environ.get("GEMINI_LLM_MODEL", "gemini-2.5-flash"),
        contents=prompt,
    )
    return resp.text


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--provider", choices=["gemini", "local", "local_docker"], default=None)
    args = parser.parse_args()

    print("\n" + "=" * 80)
    print(answer_query(args.query, top_k=args.top_k, provider=args.provider))
    print("=" * 80)
