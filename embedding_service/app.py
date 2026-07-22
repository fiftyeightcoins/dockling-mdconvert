"""
Small FastAPI service that wraps BAAI/bge-base-en-v1.5 locally.
Runs entirely offline once the model is downloaded (baked into the image
at build time, so no internet needed at runtime either).

Endpoints:
  GET  /health                          -> {"status": "ok", "dimension": 768}
  POST /embed  {"texts": [...], "mode": "query"|"document"}
       -> {"embeddings": [[...], ...], "dimension": 768}

BGE models want an instruction prefix on the query side only:
  "Represent this sentence for searching relevant passages: "
Documents are embedded as-is. This is handled here so callers just send
mode="query" or mode="document" and don't need to know the model's quirks.
"""

import os
from typing import List, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

MODEL_NAME = os.environ.get("MODEL_NAME", "BAAI/bge-base-en-v1.5")
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

app = FastAPI(title="Local BGE Embedding Service")

print(f"Loading model {MODEL_NAME} ...")
model = SentenceTransformer(MODEL_NAME, device=os.environ.get("DEVICE", "cpu"))
DIMENSION = model.get_sentence_embedding_dimension()
print(f"Model loaded. Embedding dimension: {DIMENSION}")


class EmbedRequest(BaseModel):
    texts: List[str]
    mode: Literal["query", "document"] = "document"


class EmbedResponse(BaseModel):
    embeddings: List[List[float]]
    dimension: int


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME, "dimension": DIMENSION}


@app.post("/embed", response_model=EmbedResponse)
def embed(req: EmbedRequest):
    if not req.texts:
        raise HTTPException(status_code=400, detail="texts must be a non-empty list")

    texts = req.texts
    if req.mode == "query":
        texts = [QUERY_PREFIX + t for t in texts]

    vectors = model.encode(texts, normalize_embeddings=True, batch_size=32)
    return EmbedResponse(embeddings=[v.tolist() for v in vectors], dimension=DIMENSION)
