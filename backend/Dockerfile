FROM python:3.12-slim
ARG VCS_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/roctbb/GeekExam" org.opencontainers.image.revision=$VCS_REF
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chmod +x entrypoint.sh
CMD ["./entrypoint.sh"]
