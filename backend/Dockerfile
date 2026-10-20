FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements-ml.txt backend/requirements.txt /app/backend/
RUN pip install --no-cache-dir -r backend/requirements-ml.txt
COPY demo /app/demo
COPY backend /app/backend
RUN useradd --create-home groundwork && mkdir -p /app/instance /app/data && chown -R groundwork:groundwork /app/instance /app/data
USER groundwork
WORKDIR /app/backend
EXPOSE 8000
CMD ["uvicorn", "groundwork_backend.api:app", "--host", "0.0.0.0", "--port", "8000"]
