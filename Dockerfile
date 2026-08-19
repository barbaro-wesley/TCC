# Imagem única do Atlas S10: serve a API (long-running) e roda o pipeline (one-shot).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# bash para os scripts de pipeline; libgomp1 para o LightGBM (OpenMP).
RUN apt-get update \
 && apt-get install -y --no-install-recommends bash libgomp1 \
 && rm -rf /var/lib/apt/lists/*

# Dependências primeiro (camada de cache). python-dotenv é usado pelo sync_eia.
COPY requirements.txt ./
RUN pip install --upgrade pip \
 && pip install -r requirements.txt python-dotenv

# Código da aplicação (dados/artefatos vêm por bind-mount no compose — ver .dockerignore).
COPY . .

# Usuário não-root.
RUN useradd --system --uid 1001 --create-home atlas \
 && chown -R atlas:atlas /app
USER atlas

EXPOSE 8000

# Liveness: a API respondendo em /health (200) — o endpoint já existe.
HEALTHCHECK --interval=30s --timeout=10s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).status==200 else 1)"

# Padrão: sobe a API. O serviço 'pipeline' no compose sobrescreve o command.
CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
