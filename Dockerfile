# syntax=docker/dockerfile:1

# ---- cli: headless command-line image (small) --------------------------------------------------
FROM python:3.12-slim AS cli
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    SKRAPKIN_HOME=/tmp/skrapkin-home
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY skrapkin ./skrapkin
RUN useradd --create-home --uid 1000 skrapkin && mkdir /data && chown skrapkin /data
USER skrapkin
WORKDIR /data
ENV PYTHONPATH=/app
ENTRYPOINT ["python", "-m", "skrapkin.cli"]

# ---- gui: desktop window shown through X11 (Linux). The full python image ships Tk. ----------
FROM python:3.12 AS gui
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    SKRAPKIN_HOME=/tmp/skrapkin-home
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY skrapkin ./skrapkin
COPY run_gui.py .
RUN useradd --create-home --uid 1000 skrapkin && mkdir /data && chown skrapkin /data
USER skrapkin
ENV HOME=/data
CMD ["python", "run_gui.py"]
