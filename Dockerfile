FROM python:3.11-slim

USER root
WORKDIR /app

# 필수 시스템 라이브러리 설치
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libgomp1 \
    git \
    && rm -rf /var/lib/apt/lists/*

# 파이썬 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY . .

# 실행 권한 부여
RUN chmod +x main.py

EXPOSE 7860

CMD ["python", "main.py"]