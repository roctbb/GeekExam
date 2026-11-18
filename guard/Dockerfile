FROM node:24-alpine AS web
WORKDIR /web
COPY web/package*.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 guard
COPY guard_service/ ./guard_service/
COPY --from=web /web/dist ./web/dist/
RUN mkdir -p instance && chown guard:guard instance
USER guard
EXPOSE 8088
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8088/healthz', timeout=3)"
ARG VCS_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/roctbb/GeekExam" org.opencontainers.image.revision=$VCS_REF
CMD ["gunicorn", "--bind", "0.0.0.0:8088", "--workers", "2", "--threads", "4", "--timeout", "30", "guard_service:create_app()"]
