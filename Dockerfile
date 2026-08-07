# ── build a slim, non-root image ───────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TEPHRA_DEFAULT_VAULT=/vault

WORKDIR /srv

# deps first so code edits don't bust the layer cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Run as a non-root user. UID/GID are build args so you can match the
# ownership of your host vault directory and avoid permission surprises:
#   docker compose build --build-arg UID=$(id -u) --build-arg GID=$(id -g)
ARG UID=1000
ARG GID=1000
RUN groupadd -g $GID tephra 2>/dev/null || true && \
    useradd -u $UID -g $GID -m -s /usr/sbin/nologin tephra 2>/dev/null || true && \
    mkdir -p /vault && chown -R $UID:$GID /vault /srv
USER $UID:$GID

VOLUME ["/vault"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=4s --start-period=8s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
