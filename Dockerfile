FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /workspace

FROM base AS ai
COPY config/requirements/ai.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements.txt
COPY ai-services/app ./ai-services/app
COPY ai-services/migrations ./ai-services/migrations
COPY ai-services/eval_harness ./ai-services/eval_harness
COPY ai-services/requirements.txt ./ai-services/requirements.txt
COPY ai-services/scripts/container_start.py ./container_start.py
COPY backend/migrations/0007_demo_users.sql ./backend/migrations/0007_demo_users.sql
COPY config ./config
COPY dataloader_offline ./dataloader_offline
COPY eval ./eval
COPY speech ./speech
COPY scripts/btc_container.py scripts/prepare_knowledge_tokenizer.py ./scripts/
RUN chmod -R a+rX /workspace
ENV PYTHONPATH=/workspace/ai-services:/workspace
ENTRYPOINT ["python", "/workspace/container_start.py"]

FROM base AS speech
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 libgomp1 libstdc++6 libasound2t64 && rm -rf /var/lib/apt/lists/*
COPY speech/serving/requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements.txt vieneu==3.8.3
COPY speech ./speech
ENV PYTHONPATH=/workspace
RUN python -c "from speech.serving import app, vieneu_sidecar"

FROM speech AS speech-gpu
COPY speech/serving/requirements-cuda13.txt /tmp/requirements-cuda13.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements-cuda13.txt && python -m pip uninstall -y onnxruntime && python -m pip install --no-cache-dir --force-reinstall --no-deps onnxruntime-gpu==1.28.0
RUN python -c "from pathlib import Path; print('\n'.join(str(p) for p in Path('/usr/local/lib/python3.12/site-packages/nvidia').glob('*/lib')))" > /etc/ld.so.conf.d/speech-cuda.conf && ldconfig
RUN python -c "from importlib.metadata import version; import sherpa_onnx, onnxruntime, torch; assert '+cuda' in version('sherpa-onnx'); assert 'CUDAExecutionProvider' in onnxruntime.get_available_providers(); assert torch.version.cuda.startswith('13.')"

FROM base AS backend
COPY config/requirements/backend.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements.txt
COPY backend/app ./backend/app
COPY backend/migrations/0007_demo_users.sql ./backend/migrations/0007_demo_users.sql
COPY frontend ./frontend
COPY scripts/btc_container.py ./scripts/btc_container.py
ENV PYTHONPATH=/workspace/backend:/workspace
