# Built with context = project root (see docker-compose.yml), so it can pip
# install both the root project's requirements.txt (neo4j, google-genai, etc.)
# and the webapp backend's own requirements.txt (fastapi, docling) and has
# access to ingest.py / rag.py / rag_csv.py / embeddings.py / graph_store.py
# to invoke as subprocesses.
FROM python:3.11-slim

WORKDIR /app/project

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
COPY webapp/backend/requirements.txt ./webapp/backend/requirements.txt

RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r webapp/backend/requirements.txt

COPY . .

EXPOSE 8080
CMD ["uvicorn", "webapp.backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
