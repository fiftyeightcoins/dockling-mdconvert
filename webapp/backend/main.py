"""
Backend for the GraphRAG web UI.

Responsibilities:
  1. Accept uploaded documents (PDF, DOCX, PPTX, HTML, images, etc.), convert
     them to clean Markdown using Docling, save the .md, then ingest.py that
     markdown into the Neo4j document graph.
  2. Accept a query + mode ("documents" or "oil_dataset") and run the
     corresponding existing CLI script as a subprocess:
        python rag.py     --query "..." --provider gemini   (documents)
        python rag_csv.py --query "..." --provider gemini   (oil dataset)
     then parse and return the answer.

Nothing about rag.py / rag_csv.py is modified — this just orchestrates them.
"""

import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# --- paths ---
BACKEND_DIR = Path(__file__).resolve().parent
WEBAPP_DIR = BACKEND_DIR.parent
PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", WEBAPP_DIR.parent)).resolve()
FRONTEND_DIR = WEBAPP_DIR / "frontend"
UPLOADS_DIR = WEBAPP_DIR / "data" / "uploads"
MARKDOWN_DIR = WEBAPP_DIR / "data" / "markdown"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)

PYTHON_BIN = os.environ.get("PYTHON_BIN", sys.executable)
DEFAULT_PROVIDER = os.environ.get("DEFAULT_PROVIDER", "gemini")

app = FastAPI(title="GraphRAG Oil Intelligence API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Track ingested docs for the sidebar (simple JSON-on-disk registry, no DB needed)
import json
REGISTRY_PATH = WEBAPP_DIR / "data" / "documents.json"


def _load_registry():
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text())
    return []


def _save_registry(docs):
    REGISTRY_PATH.write_text(json.dumps(docs, indent=2))


# ---------- Docling conversion ----------

def convert_to_markdown(src_path: Path) -> str:
    """Convert any supported document to Markdown text using Docling."""
    from docling.document_converter import DocumentConverter
    converter = DocumentConverter()
    result = converter.convert(str(src_path))
    return result.document.export_to_markdown()


def run_ingest(md_path: Path, doc_id: str, title: str, provider: str) -> str:
    """Call the existing ingest.py CLI script to load markdown into Neo4j."""
    cmd = [
        PYTHON_BIN, str(PROJECT_ROOT / "ingest.py"),
        "--file", str(md_path),
        "--doc-id", doc_id,
        "--title", title,
        "--provider", provider,
    ]
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        raise RuntimeError(f"ingest.py failed:\n{proc.stdout}\n{proc.stderr}")
    return proc.stdout


# ---------- RAG query orchestration ----------

ANSWER_BLOCK_RE = re.compile(r"={10,}\n(.*?)\n={10,}", re.DOTALL)


def run_rag_script(script: str, query: str, provider: str, extra_args=None) -> str:
    cmd = [PYTHON_BIN, str(PROJECT_ROOT / script), "--query", query, "--provider", provider]
    if extra_args:
        cmd.extend(extra_args)
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"{script} failed:\n{proc.stdout}\n{proc.stderr}")

    match = ANSWER_BLOCK_RE.search(proc.stdout)
    return match.group(1).strip() if match else proc.stdout.strip()


# ---------- API routes ----------

@app.get("/api/documents")
def list_documents():
    return _load_registry()


@app.post("/api/upload")
async def upload_documents(files: list[UploadFile] = File(...), provider: str = Form(DEFAULT_PROVIDER)):
    results = []
    registry = _load_registry()

    for f in files:
        try:
            doc_id = f"doc_{uuid.uuid4().hex[:10]}"
            src_path = UPLOADS_DIR / f"{doc_id}_{f.filename}"
            with open(src_path, "wb") as out:
                out.write(await f.read())

            md_text = convert_to_markdown(src_path)
            md_path = MARKDOWN_DIR / f"{doc_id}.md"
            md_path.write_text(md_text, encoding="utf-8")

            run_ingest(md_path, doc_id, title=f.filename, provider=provider)

            entry = {
                "doc_id": doc_id,
                "filename": f.filename,
                "markdown_path": str(md_path),
                "status": "ingested",
                "chars": len(md_text),
            }
            registry.append(entry)
            results.append(entry)
        except Exception as e:
            results.append({"filename": f.filename, "status": "error", "error": str(e)})

    _save_registry(registry)
    return {"results": results}


@app.post("/api/query")
async def query(payload: dict):
    q = payload.get("query", "").strip()
    mode = payload.get("mode", "documents")  # "documents" | "oil_dataset"
    provider = payload.get("provider", DEFAULT_PROVIDER)

    if not q:
        raise HTTPException(status_code=400, detail="query is required")

    try:
        if mode == "oil_dataset":
            answer = run_rag_script("rag_csv.py", q, provider)
        else:
            answer = run_rag_script("rag.py", q, provider, extra_args=["--graph-hops", "2", "--neighbor-window", "1"])
        return {"answer": answer, "mode": mode, "provider": provider}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- static frontend ----------

@app.get("/")
def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
