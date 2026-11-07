ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /service

RUN rm -rf /service/app /frontend
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY frontend /frontend

CMD ["python", "-m", "uvicorn", "app.voice_main:app", "--host", "0.0.0.0", "--port", "8000"]
