# One image, one process, one world. See docs/DEPLOY.md.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# The game's own packages are installed from paths, never from an index:
# there are unrelated packages on PyPI called `market` and `api`. See
# sim/pyproject.toml. Editable installs, because sim reads orbital's anchor
# data from the source tree.
COPY orbital/ orbital/
COPY market/ market/
COPY sim/ sim/
COPY voice/ voice/
COPY api/ api/
RUN pip install -e './orbital[offline]' -e ./market -e ./sim -e ./voice -e ./api

COPY web/ web/

# Everything that must survive a rebuild lives in /data: the world.
ENV SOLAR_DB=/data/world.db \
    SOLAR_HOST=0.0.0.0 \
    SOLAR_PORT=8000 \
    SOLAR_WEB=/app/web
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

# Never more than one worker. Two processes would be two diverging worlds.
CMD ["python", "-m", "api"]
