FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --uid 10001 --create-home agent
COPY runtime /opt/runtime
WORKDIR /workspace
USER 10001:10001
ENTRYPOINT ["python", "-m", "runtime.main"]
ENV PYTHONPATH=/opt

FROM node:22-alpine AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build

FROM python:3.12-slim AS platform
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/services:/app
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY services ./services
COPY runtime ./runtime
COPY --from=web /web/dist /app/web
RUN useradd --uid 10001 --create-home platform
USER 10001:10001
CMD ["uvicorn", "agentberth.api:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
