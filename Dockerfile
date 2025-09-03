# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install Python dependencies first (better cache)
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Copy app code
COPY crawler.py ./
COPY schema.sql ./
COPY .env.example ./

# Default entrypoint; command/args can be overridden by docker-compose
ENTRYPOINT ["python", "crawler.py"]

