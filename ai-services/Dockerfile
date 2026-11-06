# syntax=docker/dockerfile:1
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=5 PIP_RESUME_RETRIES=5 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /service
COPY requirements.txt ./
RUN --mount=type=cache,id=ai-services-pip-py312-cpu,target=/root/.cache/pip,sharing=locked \
    python -m pip install --upgrade pip==25.2 \
    && python -m pip install -r requirements.txt
COPY app ./app
COPY scripts/container_start.py ./container_start.py
ENTRYPOINT ["python", "/service/container_start.py"]

CMD ["python", "-m", "app.mcp_servers.mcp_catalog.server"]
