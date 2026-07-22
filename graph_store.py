"""
Neo4j graph store helper for GraphRAG.

Schema used:
  (:Document {id, title, source})
  (:Chunk {id, text, embedding, doc_id})-[:PART_OF]->(:Document)
  (:Chunk)-[:NEXT]->(:Chunk)                 -- sequential order
  (:Entity {name, type})
  (:Chunk)-[:MENTIONS]->(:Entity)
  (:Entity)-[:RELATES_TO {type, description}]->(:Entity)

A native vector index is created on Chunk.embedding, dimension matching
whichever embedder you choose (both backends are configured to output
768-dim vectors so you can swap providers without recreating the index).
"""

import os
from typing import List, Dict, Any
from neo4j import GraphDatabase


class Neo4jGraphStore:
    def __init__(self, uri=None, user=None, password=None, database=None):
        self.driver = GraphDatabase.driver(
            uri or os.environ["NEO4J_URI"],
            auth=(user or os.environ["NEO4J_USERNAME"], password or os.environ["NEO4J_PASSWORD"]),
        )
        self.database = database or os.environ.get("NEO4J_DATABASE", "neo4j")

    def close(self):
        self.driver.close()

    def run(self, query: str, **params):
        with self.driver.session(database=self.database) as session:
            return list(session.run(query, **params))

    # ---------- setup ----------

    def create_vector_index(self, dimension: int, index_name: str = "chunk_embedding_index",
                             similarity: str = "cosine"):
        self.run(f"""
        CREATE VECTOR INDEX {index_name} IF NOT EXISTS
        FOR (c:Chunk) ON (c.embedding)
        OPTIONS {{ indexConfig: {{
            `vector.dimensions`: $dim,
            `vector.similarity_function`: $sim
        }}}}
        """, dim=dimension, sim=similarity)

    def create_constraints(self):
        self.run("CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE")
        self.run("CREATE CONSTRAINT doc_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE")
        self.run("CREATE CONSTRAINT entity_name IF NOT EXISTS FOR (e:Entity) REQUIRE e.name IS UNIQUE")

    # ---------- ingestion ----------

    def upsert_document(self, doc_id: str, title: str, source: str = ""):
        self.run("""
        MERGE (d:Document {id: $doc_id})
        SET d.title = $title, d.source = $source
        """, doc_id=doc_id, title=title, source=source)

    def upsert_chunk(self, chunk_id: str, text: str, embedding: List[float], doc_id: str, prev_chunk_id: str = None):
        self.run("""
        MERGE (c:Chunk {id: $chunk_id})
        SET c.text = $text, c.embedding = $embedding, c.doc_id = $doc_id
        WITH c
        MATCH (d:Document {id: $doc_id})
        MERGE (c)-[:PART_OF]->(d)
        """, chunk_id=chunk_id, text=text, embedding=embedding, doc_id=doc_id)
        if prev_chunk_id:
            self.run("""
            MATCH (p:Chunk {id: $prev}), (c:Chunk {id: $curr})
            MERGE (p)-[:NEXT]->(c)
            """, prev=prev_chunk_id, curr=chunk_id)

    def upsert_entity(self, name: str, entity_type: str = "Entity"):
        self.run("""
        MERGE (e:Entity {name: $name})
        SET e.type = $type
        """, name=name, type=entity_type)

    def link_chunk_mentions_entity(self, chunk_id: str, entity_name: str):
        self.run("""
        MATCH (c:Chunk {id: $chunk_id}), (e:Entity {name: $name})
        MERGE (c)-[:MENTIONS]->(e)
        """, chunk_id=chunk_id, name=entity_name)

    def link_entities(self, source: str, target: str, rel_type: str = "RELATES_TO", description: str = ""):
        self.run("""
        MATCH (a:Entity {name: $source}), (b:Entity {name: $target})
        MERGE (a)-[r:RELATES_TO]->(b)
        SET r.type = $rel_type, r.description = $description
        """, source=source, target=target, rel_type=rel_type, description=description)

    # ---------- retrieval ----------

    def vector_search(self, query_embedding: List[float], top_k: int = 5,
                       index_name: str = "chunk_embedding_index") -> List[Dict[str, Any]]:
        result = self.run(f"""
        CALL db.index.vector.queryNodes($index_name, $top_k, $embedding)
        YIELD node, score
        RETURN node.id AS id, node.text AS text, node.doc_id AS doc_id, score
        ORDER BY score DESC
        """, index_name=index_name, top_k=top_k, embedding=query_embedding)
        return [dict(r) for r in result]

    def expand_graph_context(self, chunk_ids: List[str], hops: int = 1, limit: int = 25) -> List[Dict[str, Any]]:
        """
        Given seed chunks from vector search, walk out through MENTIONS ->
        Entity -> RELATES_TO -> Entity <- MENTIONS <- Chunk to pull in
        graph-connected context that pure vector similarity would miss.
        """
        result = self.run(f"""
        MATCH (c:Chunk) WHERE c.id IN $chunk_ids
        MATCH (c)-[:MENTIONS]->(e:Entity)
        OPTIONAL MATCH (e)-[r:RELATES_TO*1..{hops}]-(e2:Entity)
        OPTIONAL MATCH (other:Chunk)-[:MENTIONS]->(e2)
        WITH DISTINCT e, e2, other
        LIMIT $limit
        RETURN e.name AS entity, e2.name AS related_entity,
               other.id AS related_chunk_id, other.text AS related_chunk_text
        """, chunk_ids=chunk_ids, limit=limit)
        return [dict(r) for r in result]

    def get_neighboring_chunks(self, chunk_id: str, window: int = 1) -> List[Dict[str, Any]]:
        """Pull chunks immediately before/after a seed chunk via :NEXT for extra context."""
        result = self.run(f"""
        MATCH (c:Chunk {{id: $chunk_id}})
        OPTIONAL MATCH (c)<-[:NEXT*1..{window}]-(before:Chunk)
        OPTIONAL MATCH (c)-[:NEXT*1..{window}]->(after:Chunk)
        RETURN collect(DISTINCT before.text) + collect(DISTINCT after.text) AS neighbors
        """, chunk_id=chunk_id)
        rows = [dict(r) for r in result]
        return rows[0]["neighbors"] if rows else []
