# Zero-Budget OCI Plan

Target OCI shape: Ampere A1 Always Free where available.

Recommended stack:

- Docker Compose
- Caddy or Nginx
- Next.js command center
- Python EAOS runtime
- PostgreSQL
- n8n or Activepieces
- Uptime Kuma
- optional Qdrant/Chroma
- optional Ollama
- optional FFmpeg/Whisper.cpp

Do not create paid shapes, paid storage, paid load balancers beyond Always Free limits, or paid API calls.

Run the cost guard before enabling any connector.
