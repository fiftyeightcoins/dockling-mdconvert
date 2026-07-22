# GraphRAG on Neo4j (local BGE embeddings)

A minimal but complete GraphRAG stack over your Neo4j web instance:

- **Vector search** over chunk embeddings using Neo4j's native vector index
- **Graph expansion** through entity/relation edges extracted from your text
  (catches connected context that pure vector similarity misses)
- **Swappable embeddings**: free-tier **Gemini embedding API** (`gemini-embedding-001`)
  or fully local **`BAAI/bge-base-en-v1.5`** (no API key, no network)
- **Answer generation** with Gemini (`gemini-2.5-flash` by default, also free-tier)

## 0. Local embedding model, dockerized (recommended if you hit dependency conflicts)

If installing `torch`/`sentence-transformers` locally causes version
conflicts, run the BGE model in its own isolated container instead — your
main environment then only needs `requests` to talk to it over HTTP.

```bash
docker compose up -d --build bge-embedding-service
# check it's ready:
curl http://localhost:8000/health
# {"status":"ok","model":"BAAI/bge-base-en-v1.5","dimension":768}
```

Then set in `.env`:
```
EMBEDDING_PROVIDER=local_docker
LOCAL_EMBED_SERVICE_URL=http://localhost:8000
```

Or pass `--provider local_docker` on any script's CLI. The model is baked
into the image at build time, so once built, the container runs fully
offline (no internet needed at runtime, no re-downloads).

The service exposes:
- `GET /health` → `{"status", "model", "dimension"}`
- `POST /embed` with `{"texts": [...], "mode": "query"|"document"}` →
  `{"embeddings": [[...]], "dimension": 768}` (handles the BGE query-prefix
  convention internally, so callers don't need to think about it)

To stop it: `docker compose down`. Logs: `docker compose logs -f bge-embedding-service`.

## 1. Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env: Neo4j creds + Gemini API key (get one free at https://aistudio.google.com/apikey)
```

Set `EMBEDDING_PROVIDER=gemini` or `EMBEDDING_PROVIDER=local` in `.env`.
Both backends are configured to output **768-dim** vectors so the Neo4j
vector index stays compatible no matter which you pick (Gemini's
`output_dimensionality` is set to 768 to match BGE-base's native size).

> Note: if you ingest with one provider, query with the *same* provider —
> embeddings from different models aren't comparable. Re-ingest if you switch.

## 2. Ingest a document

```bash
python ingest.py --file mydoc.txt --doc-id doc1 --title "My Document" --provider gemini
# or, fully offline:
python ingest.py --file mydoc.txt --doc-id doc1 --title "My Document" --provider local
```

This will:
1. Chunk the text (~800 words, 100-word overlap)
2. Embed each chunk
3. Write `(:Document)`, `(:Chunk {embedding})`, `:PART_OF`, `:NEXT` (sequential order)
4. Use Gemini to pull entities/relations per chunk → `(:Entity)`, `:MENTIONS`, `:RELATES_TO`
   (skip this with `--no-entities` for faster/cheaper ingestion if you only want vector RAG)

## 3. Query

```bash
python rag.py --query "How does X relate to Y?" --provider gemini --graph-hops 2
```

Pipeline: embed query → vector search top-k chunks → expand via graph
(entities → related entities → their chunks) → optionally pull `:NEXT`
neighbor chunks for local continuity → assemble context → ask Gemini,
grounded strictly in retrieved context, with chunk-id citations.

## Neo4j schema

```
(:Document {id, title, source})
(:Chunk {id, text, embedding, doc_id}) -[:PART_OF]-> (:Document)
(:Chunk) -[:NEXT]-> (:Chunk)
(:Entity {name, type})
(:Chunk) -[:MENTIONS]-> (:Entity)
(:Entity) -[:RELATES_TO {type, description}]-> (:Entity)
```

Vector index: `chunk_embedding_index` on `Chunk.embedding`, cosine similarity.

## Notes on the two embedding backends

| | Gemini (`gemini-embedding-001`) | Local (`BAAI/bge-base-en-v1.5`) |
|---|---|---|
| Cost | Free tier (rate-limited) | Free, no limits |
| Network | Requires internet + API key | Fully offline |
| Speed | API latency, batched in 10s | Depends on your CPU/GPU |
| Quality | Strong, general-purpose | Strong for English retrieval, MTEB-competitive |
| Setup | Just an API key | Downloads ~440MB model on first run |

Switch anytime via `EMBEDDING_PROVIDER` in `.env` or `--provider` on the CLI —
just remember to re-ingest if you change providers, since vector spaces differ.

## CSV / structured-data ingestion (e.g. oil-geopolitics dataset)

For structured tabular data (events, sanctions, exports, risk indices, daily
prices), don't chunk rows as raw text — use `ingest_csv.py` / `rag_csv.py`
instead of `ingest.py` / `rag.py`. These build a domain graph:

```
(:Record {id, type, date, narrative, embedding, ...})
(:Record) -[:IN_MONTH]-> (:Month {key:"YYYY-MM"})
(:Record) -[:INVOLVES_COUNTRY]-> (:Country {name})
```

Each row becomes a `Record` with a generated natural-language `narrative`
(what gets embedded and shown to the LLM) plus `type` = `event | sanction |
export | risk | price_event | price_month`. Daily prices aren't embedded row
by row (too granular) — only geopolitical-event days, plus one aggregated
`price_month` record per month.

At query time, `rag_csv.py` vector-searches for the closest Records, then
hops through shared `Month`/`Country` nodes to pull in records that
co-occurred in time or involved the same country — this is the "graph" part
of GraphRAG: it surfaces connections plain similarity search would miss
(e.g. a sanction and a price shock that happened the same month).

```bash
python ingest_csv.py --dir "path/to/csv_folder" --provider gemini
python rag_csv.py --query "What happened to oil prices during the 2012 Iran sanctions?" --provider gemini
```

## Web UI (elegant frontend for oil traders)

A single-page web app lives in `webapp/`:

- **Backend** (`webapp/backend/main.py`, FastAPI): accepts document uploads,
  converts them to Markdown with **Docling**, ingests them via the existing
  `ingest.py`, and answers questions by shelling out to your existing CLI
  scripts exactly as-is:
  ```
  python rag.py     --query "..." --provider gemini    (Document KB mode)
  python rag_csv.py --query "..." --provider gemini    (Oil Dataset mode)
  ```
  Nothing about `rag.py`/`rag_csv.py` was changed — the backend just runs
  them as subprocesses and parses the printed answer block.
- **Frontend** (`webapp/frontend/`): a white-themed chat interface with a
  mode switch (Oil Dataset vs. Document Knowledge Base), a drag-and-drop
  upload panel, and trader-oriented answer formatting — dollar amounts,
  percentages (colored by sign), dates, and record-id citations are
  highlighted inline so key figures jump out at a glance.

### Run it

Locally (same venv as the rest of the project, plus the two extra deps):
```bash
pip install fastapi uvicorn python-multipart docling
uvicorn webapp.backend.main:app --reload --port 8080
```
Then open http://localhost:8080

Or via Docker (bundled into `docker-compose.yml`, alongside the embedding service):
```bash
docker compose up -d --build webapp bge-embedding-service
```
Then open http://localhost:8080. Make sure `.env` is filled in — it's mounted
into the container via `env_file`.

### Notes
- Uploaded files are converted to Markdown under `webapp/data/markdown/` and
  registered in `webapp/data/documents.json` (a lightweight JSON registry
  used purely for the sidebar list — Neo4j remains the source of truth for
  retrieval).
- The "Oil Dataset" mode's document list is a static display of the 5 CSVs
  already ingested via `ingest_csv.py` — upload isn't wired to that mode
  since it isn't a generic-document graph.
- Answer formatting (highlighting $, %, dates, citations) happens purely in
  the frontend; the underlying prompts in `rag.py`/`rag_csv.py` were not
  changed, so the trader framing there still comes from `rag_csv.py`'s
  existing analyst-style system prompt.

## Extending this

- Swap `chunk_text` for a semantic/recursive splitter (e.g. LangChain's
  `RecursiveCharacterTextSplitter`) for better chunk boundaries.
- Replace the simple Gemini-prompt entity extractor in `ingest.py` with a
  proper NER/RE model if you need higher precision at scale.
- Add a reranker (e.g. cross-encoder) between vector search and graph
  expansion if precision at low top-k matters more than recall.
- Add community/graph-clustering (Leiden via GDS) for a "global" GraphRAG
  mode (summarizing whole clusters) alongside this "local" mode.
