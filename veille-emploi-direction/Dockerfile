FROM python:3.12-slim

WORKDIR /app

COPY worker.py pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir "mistralai-workflows>=3.10"

CMD ["python", "worker.py"]
