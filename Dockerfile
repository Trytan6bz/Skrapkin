# syntax=docker/dockerfile:1

# ---- cli: headless command-line image ------------------------------------------------------
FROM python:3.12-slim AS cli
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    SKRAPKIN_HOME=/config PYTHONPATH=/app
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY skrapkin ./skrapkin
RUN useradd --create-home --uid 1000 skrapkin && mkdir /data /config && chown skrapkin /data /config
USER skrapkin
WORKDIR /data
ENTRYPOINT ["python", "-m", "skrapkin.cli"]

# ---- web: the browser interface (default for docker compose up) ----------------------------
FROM cli AS web
ENV SKRAPKIN_WEB_HOST=0.0.0.0 SKRAPKIN_WEB_PORT=8080 SKRAPKIN_OUTPUT_DIR=/data/output
EXPOSE 8080
ENTRYPOINT ["python", "-m", "skrapkin.web"]
