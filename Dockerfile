FROM node:24-bookworm-slim AS frontend
WORKDIR /web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.13-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PLAYWRIGHT_BROWSERS_PATH=/opt/browsers
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project && \
    .venv/bin/python -m playwright install --with-deps chromium && \
    chmod -R a+rX /opt/browsers
RUN groupadd --gid 10001 adwatch && useradd --uid 10001 --gid adwatch --create-home adwatch
COPY adwatch/ ./adwatch/
COPY facebook_ads_mcp_complete.py ./
COPY --from=frontend /web/dist ./web/dist
ENV PATH="/app/.venv/bin:$PATH"
USER adwatch
EXPOSE 8000
CMD ["uvicorn", "adwatch.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
