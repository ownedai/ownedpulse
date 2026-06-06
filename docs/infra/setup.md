# Infrastructure Setup

## Docker — api/Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]
```

## Docker — ui/Dockerfile

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
```

## vite.config.js essentials

- Proxy: `/api` → `http://regpulse-api:8001` (container name on ai-stack)
- `allowedHosts: ['rp.ownedai.dev']` for Cloudflare tunnel access
- `VITE_API_URL=""` in docker-compose forces same-origin via Vite proxy

Both containers join existing `ai-stack` Docker network.

Compose files: `/opt/docker-compose/regpulse-api/docker-compose.yml` and `/opt/docker-compose/regpulse-ui/docker-compose.yml`.

## Infrastructure Connections

### Qdrant
- Host: `qdrant` — Port: 6333
- Collection: `knowledge_base`
- ALWAYS use `client.query_points()` — never `client.search()`

### PostgreSQL
- Host: `postgres` — Port: 5432
- Database: `knowledge_base` — User: `postgres`
- Password: from env `POSTGRES_PASSWORD`

### Ollama
- Host: `ollama` — Port: 11434
- Generation model: `phi4:14b-q8_0`
- Embedding model: `mxbai-embed-large`

### Langfuse
- Host: `langfuse` — Port: 3000
- Credentials from env: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`
- Used for nested trace per query (sub-queries → retrievals → dedup → LLM call)
- Backend exposes `GET /api/trace/{trace_id}` to proxy Langfuse for UI drawer
