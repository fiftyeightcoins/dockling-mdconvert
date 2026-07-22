# Local BGE embedding service — fully isolated, no dependency conflicts with your main app.
FROM python:3.11-slim

WORKDIR /app

# System deps for torch (CPU only, keeps image smaller)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# CPU-only torch wheel keeps the image ~1.5GB instead of ~5GB with CUDA
RUN pip install --no-cache-dir torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Bake the model into the image at build time so container startup needs
# no internet access and no re-download.
ARG MODEL_NAME=BAAI/bge-base-en-v1.5
ENV MODEL_NAME=${MODEL_NAME}
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${MODEL_NAME}')"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
