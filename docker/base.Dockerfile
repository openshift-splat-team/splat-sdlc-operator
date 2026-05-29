FROM python:3.11-slim

RUN pip install uv==0.4.18 --no-cache-dir

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY agents/common ./agents/common
COPY agents/__init__.py ./agents/__init__.py
