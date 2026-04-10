FROM python:3.10-slim

WORKDIR /app

# ffmpeg + Node.js 설치
RUN apt-get update && apt-get install -y \
    ffmpeg git nodejs npm \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# yt-dlp-get-pot 플러그인 설치
RUN pip install --no-cache-dir \
    "yt-dlp-get-pot @ https://github.com/coletdjnz/yt-dlp-get-pot/archive/refs/heads/master.zip"

# bgutil Node.js 서버 설치
RUN npm install -g bgutil-ytdlp-pot-provider

COPY . .

EXPOSE 7860

# bgutil 서버 + FastAPI 동시 실행
CMD ["sh", "-c", "node /usr/local/lib/node_modules/bgutil-ytdlp-pot-provider/build/server.js & python main.py"]