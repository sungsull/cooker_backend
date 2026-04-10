FROM python:3.10-slim

USER root
WORKDIR /app

# Node.js 20 설치 (bgutil 요구사항: Node >= 20)
RUN apt-get update && apt-get install -y \
    ffmpeg git curl ca-certificates gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
       | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" \
       | tee /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Python 라이브러리 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# bgutil POT provider 플러그인 (PyPI 직접 설치, deprecated된 get-pot 불필요)
RUN pip install --no-cache-dir bgutil-ytdlp-pot-provider

# bgutil Node.js 서버 빌드 (server/ 디렉토리에서 빌드해야 함)
RUN git clone --single-branch --branch master \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /app/bgutil && \
    cd /app/bgutil/server && \
    npm ci && \
    npx tsc

COPY . .

RUN chmod -R 777 /app

# 올바른 빌드 결과물 경로: server/build/main.js
CMD ["sh", "-c", "node /app/bgutil/server/build/main.js & sleep 5 && python main.py"]
