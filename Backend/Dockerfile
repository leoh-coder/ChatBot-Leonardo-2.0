FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY Backend/requirements.txt ./Backend/requirements.txt

RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install -r Backend/requirements.txt \
    && (pip uninstall -y google-generativeai || true)

COPY Backend/ ./Backend/

WORKDIR /app/Backend

EXPOSE 8010

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8010"]
