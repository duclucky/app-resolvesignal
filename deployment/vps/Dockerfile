ARG PYTHON_BASE=python:3.13-slim@sha256:cf50a4f6ac4f026458b08d5222023d700ac806410dff5e9ca8728fa44f2b850f
FROM ${PYTHON_BASE} AS dependencies
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.linux.lock /app/requirements.linux.lock
RUN python -m venv /venv && /venv/bin/pip install --no-cache-dir --require-hashes -r /app/requirements.linux.lock

FROM dependencies AS verification
COPY src /app/src
COPY tests /app/tests
COPY data/fixtures /app/data/fixtures
RUN /venv/bin/python -m pytest -q --tb=short --basetemp=/tmp/pricealert-tests --junitxml=/tmp/linux-tests.xml

FROM ${PYTHON_BASE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_DATA_DIR=/state APP_ENV_FILE=/run/pricealert-managed.env
WORKDIR /app
COPY --from=dependencies /venv /venv
COPY --from=verification /app/src /app/src
COPY --from=verification /app/data/fixtures /app/data/fixtures
COPY THIRD_PARTY_NOTICES.md LICENSE /app/
USER 65532:65532
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --start-period=20s --retries=3 CMD ["/venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=3)"]
CMD ["/venv/bin/python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers", "--no-access-log"]
