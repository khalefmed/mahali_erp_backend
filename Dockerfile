FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.10.1 /uv /usr/local/bin/uv
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN DJANGO_SECRET_KEY=build DATABASE_URL=postgres://x/x uv run --no-sync python manage.py collectstatic --noinput \
    && useradd --system --uid 1000 --home /app app \
    && mkdir -p /data/media && chown -R app /data /app/staticfiles
USER app
ENV PATH="/app/.venv/bin:$PATH" MEDIA_ROOT=/data/media
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", \
     "--timeout", "30", "--access-logfile", "-", "--forwarded-allow-ips", "*"]
