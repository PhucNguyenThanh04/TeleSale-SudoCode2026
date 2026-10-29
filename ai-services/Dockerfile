FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /service
COPY requirements.txt requirements-rag.txt ./
RUN pip install --no-cache-dir -r requirements.txt
ARG INSTALL_RAG=false
RUN if [ "$INSTALL_RAG" = "true" ]; then \
      pip install --no-cache-dir 'torch==2.7.1+cpu' --index-url https://download.pytorch.org/whl/cpu \
      && pip install --no-cache-dir -r requirements-rag.txt; \
    fi
COPY app ./app

CMD ["python", "-m", "app.mcp_servers.mcp_catalog.server"]
