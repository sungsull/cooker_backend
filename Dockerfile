FROM python:3.10-slim

USER root
WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod -R 777 /app

CMD ["python", "main.py"]