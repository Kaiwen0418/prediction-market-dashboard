FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY backend/requirements.txt /tmp/backend-requirements.txt
COPY surveillance/requirements.txt /tmp/surveillance-requirements.txt
RUN pip install -r /tmp/backend-requirements.txt -r /tmp/surveillance-requirements.txt
COPY backend/app /app/backend/app
COPY public/data /app/public/data
COPY surveillance /app/surveillance
ENV PYTHONPATH=/app/backend:/app
