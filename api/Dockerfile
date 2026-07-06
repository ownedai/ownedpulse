FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --retries 10 --timeout 300 -r requirements.txt
# Pre-cache nomic tokenizer to avoid HuggingFace network dependency at runtime
RUN python -c "from transformers import AutoTokenizer; AutoTokenizer.from_pretrained('nomic-ai/nomic-embed-text-v1')"
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]
