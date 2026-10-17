FROM python:3.13-slim AS builder

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# No compiler needed: every dependency ships a manylinux wheel for cp313.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.13-slim AS runner

WORKDIR /app

RUN addgroup --system appuser \
    && adduser --system --group appuser \
    && chown appuser:appuser /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

# Migrations run before the server starts: a new deploy, or a new store, gets its tables with no manual step.
# One worker on purpose: per-customer locks and the circuit breakers live in process memory.
# exec hands SIGTERM to uvicorn, so replies in flight get their shutdown grace period.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
