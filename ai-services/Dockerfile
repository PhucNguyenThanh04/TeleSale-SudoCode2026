ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /service
<<<<<<< HEAD
RUN rm -rf /service/app
COPY requirements.txt requirements-rag.txt ./
=======
COPY requirements.txt ./
>>>>>>> d7c5b79 (refactor(ai-services): remove unused code and simplify shared logic)
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

CMD ["python", "-m", "app.mcp_servers.mcp_catalog.server"]
