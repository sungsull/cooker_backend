FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg git nodejs npm \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN pip install --no-cache-dir \
    "yt-dlp-get-pot @ https://github.com/coletdjnz/yt-dlp-get-pot/archive/refs/heads/master.zip"

# ✅ 패키지명 수정
RUN npm install -g @brainicism/bgutil-ytdlp-pot-provider

COPY . .

EXPOSE 7860

# ✅ 경로도 패키지명에 맞게 수정
CMD ["sh", "-c", "node /usr/local/lib/node_modules/@brainicism/bgutil-ytdlp-pot-provider/build/server.js & python main.py"]