FROM python:3.10-slim

USER root
WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# torch CPU 버전 먼저 설치 (CUDA 버전 2GB → CPU 버전 200MB)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod -R 777 /app

CMD ["python", "main.py"]
