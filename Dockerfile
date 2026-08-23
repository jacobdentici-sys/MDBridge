FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN mkdir -p /data
ENV MDBRIDGE_DATA_DIR=/data
EXPOSE 7335
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7335"]
