FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN mkdir -p /data
ENV MDBRIDGE_DATA_DIR=/data \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
EXPOSE 7335
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7335/health', timeout=3)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7335"]
