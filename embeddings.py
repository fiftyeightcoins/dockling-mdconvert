"""
Embedding provider abstraction.

Two interchangeable backends:
  - "gemini": Google's free-tier Gemini Embedding API (gemini-embedding-001)
  - "local" : BAAI/bge-base-en-v1.5 running locally via sentence-transformers

Both expose the same interface: embed_query(text) -> list[float]
                                 embed_documents(list[str]) -> list[list[float]]

BGE models expect an instruction prefix on the *query* side only
("Represent this sentence for searching relevant passages: "),
documents are embedded as-is. This is handled automatically below.
"""

import os
import time
from typing import List

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class BaseEmbedder:
    dimension: int

    def embed_query(self, text: str) -> List[float]:
        raise NotImplementedError

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError


class GeminiEmbedder(BaseEmbedder):
    """
    Free-tier Gemini embeddings via google-genai SDK.
    Model: gemini-embedding-001 (default output dim 3072, can be truncated
    via output_dimensionality -> we default to 768 to match BGE-base and
    keep Neo4j vector index dimensions consistent regardless of backend).
    """

    def __init__(self, api_key: str = None, model: str = "gemini-embedding-001",
                 output_dim: int = 768, max_retries: int = 5):
        from google import genai
        self.client = genai.Client(api_key=api_key or os.environ["GEMINI_API_KEY"])
        self.model = model
        self.dimension = output_dim
        self.max_retries = max_retries

    def _embed(self, texts: List[str], task_type: str) -> List[List[float]]:
        from google.genai import types
        out = []
        # Gemini embed_content supports batching a list of contents in one call
        for attempt in range(self.max_retries):
            try:
                resp = self.client.models.embed_content(
                    model=self.model,
                    contents=texts,
                    config=types.EmbedContentConfig(
                        task_type=task_type,
                        output_dimensionality=self.dimension,
                    ),
                )
                out = [e.values for e in resp.embeddings]
                return out
            except Exception as e:
                wait = 2 ** attempt
                print(f"[GeminiEmbedder] retry {attempt+1}/{self.max_retries} after error: {e} (sleep {wait}s)")
                time.sleep(wait)
        raise RuntimeError("GeminiEmbedder: exhausted retries")

    def embed_query(self, text: str) -> List[float]:
        return self._embed([text], task_type="RETRIEVAL_QUERY")[0]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        # Gemini free tier rate-limits; chunk into small batches
        results = []
        batch_size = 10
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            results.extend(self._embed(batch, task_type="RETRIEVAL_DOCUMENT"))
            time.sleep(0.5)  # be polite to the free-tier rate limit
        return results


class LocalBGEEmbedder(BaseEmbedder):
    """
    Local, offline embedder using BAAI/bge-base-en-v1.5 (768-dim), loaded
    in-process via sentence-transformers. No API key, no network calls.
    Requires torch + sentence-transformers installed in THIS environment —
    use LocalBGEDockerEmbedder instead if you want to avoid that dependency
    footprint / version conflicts.
    """

    def __init__(self, model_name: str = "BAAI/bge-base-en-v1.5", device: str = None):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name, device=device)
        self.dimension = self.model.get_sentence_embedding_dimension()  # 768

    def embed_query(self, text: str) -> List[float]:
        vec = self.model.encode(BGE_QUERY_PREFIX + text, normalize_embeddings=True)
        return vec.tolist()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        vecs = self.model.encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=True)
        return [v.tolist() for v in vecs]


class LocalBGEDockerEmbedder(BaseEmbedder):
    """
    Calls the dockerized BGE embedding service (see embedding_service/) over
    HTTP instead of loading the model in-process. This means your main app
    never needs torch/sentence-transformers installed at all — no version
    conflicts, no CUDA/CPU wheel headaches. Just run:

        docker compose up -d bge-embedding-service

    and point this at it (default http://localhost:8000).
    """

    def __init__(self, base_url: str = None, timeout: int = 60, batch_size: int = 64):
        import requests  # local import so `requests` is only required for this backend
        self._requests = requests
        self.base_url = (base_url or os.environ.get("LOCAL_EMBED_SERVICE_URL", "http://localhost:8000")).rstrip("/")
        self.timeout = timeout
        self.batch_size = batch_size

        resp = self._requests.get(f"{self.base_url}/health", timeout=self.timeout)
        resp.raise_for_status()
        self.dimension = resp.json()["dimension"]

    def _call(self, texts: List[str], mode: str) -> List[List[float]]:
        resp = self._requests.post(
            f"{self.base_url}/embed",
            json={"texts": texts, "mode": mode},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["embeddings"]

    def embed_query(self, text: str) -> List[float]:
        return self._call([text], mode="query")[0]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        results = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            results.extend(self._call(batch, mode="document"))
        return results


def get_embedder(provider: str = None, **kwargs) -> BaseEmbedder:
    """
    Factory. provider = "gemini" | "local" | "local_docker". Falls back to
    env var EMBEDDING_PROVIDER, defaulting to "gemini".

      "gemini"       -> Gemini embedding API (needs GEMINI_API_KEY)
      "local"        -> BGE loaded in-process (needs torch + sentence-transformers)
      "local_docker" -> BGE running in the embedding_service Docker container,
                        called over HTTP. No torch/sentence-transformers
                        needed in this environment — avoids version conflicts.
    """
    provider = (provider or os.environ.get("EMBEDDING_PROVIDER", "gemini")).lower()
    if provider == "gemini":
        return GeminiEmbedder(
            model=os.environ.get("GEMINI_EMBED_MODEL", "gemini-embedding-001"),
            **kwargs,
        )
    elif provider == "local":
        return LocalBGEEmbedder(
            model_name=os.environ.get("LOCAL_EMBED_MODEL", "BAAI/bge-base-en-v1.5"),
            **kwargs,
        )
    elif provider in ("local_docker", "docker"):
        return LocalBGEDockerEmbedder(
            base_url=os.environ.get("LOCAL_EMBED_SERVICE_URL", "http://localhost:8000"),
            **kwargs,
        )
    else:
        raise ValueError(f"Unknown EMBEDDING_PROVIDER: {provider}")
