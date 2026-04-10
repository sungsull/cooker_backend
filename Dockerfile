FROM python:3.10-slim

USER root
WORKDIR /app

# 1. 시스템 패키지 + Node.js 20 바이너리 직접 설치 (NodeSource curl 방식 제거)
RUN apt-get update && apt-get install -y \
    ffmpeg git curl xz-utils ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL --retry 3 \
       https://nodejs.org/dist/v20.11.1/node-v20.11.1-linux-x64.tar.xz \
       -o /tmp/node.tar.xz \
    && tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 \
    && rm /tmp/node.tar.xz \
    && node -v && npm -v

# 2. Python 라이브러리 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir bgutil-ytdlp-pot-provider

# 3. bgutil Node.js 서버 빌드
RUN git clone --depth=1 \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /app/bgutil \
    && cd /app/bgutil/server \
    && npm ci \
    && npx tsc

# 4. 소스 복사
COPY . .

RUN chmod -R 777 /app

CMD ["sh", "-c", "node /app/bgutil/server/build/main.js & sleep 5 && python main.py"]
