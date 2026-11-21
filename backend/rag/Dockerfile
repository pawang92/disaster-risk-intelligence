FROM python:3.12-slim
WORKDIR /service
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/data/hf_cache CHROMA_PATH=/data/chroma
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils tesseract-ocr tesseract-ocr-mar && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd --system --uid 10002 --create-home raguser \
    && mkdir -p /data/chroma /data/hf_cache \
    && chown -R raguser:raguser /service /data
USER raguser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
