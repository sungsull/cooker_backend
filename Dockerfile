FROM python:3.10-slim

WORKDIR /app

# 1. 시스템 의존성 설치
# git, nodejs, npm은 외부 라이브러리 빌드에 필수입니다.
RUN apt-get update && apt-get install -y \
    ffmpeg git nodejs npm curl \
    && rm -rf /var/lib/apt/lists/*

# 2. Python 라이브러리 설치
# 먼저 requirements.txt에 있는 기본 패키지들을 설치합니다.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# [핵심] 외부 GitHub 레포지토리는 여기서 단독으로 설치 (에러 방지)
RUN pip install --no-cache-dir "git+https://github.com/coletdjnz/yt-dlp-get-pot.git"

# 3. Node.js POT provider 설치 (우회 방식)
# npm install -g 방식의 경로 에러를 피하기 위해 직접 클론하여 빌드합니다.
RUN git clone https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil && \
    cd /opt/bgutil && \
    npm install && \
    npm run build

# 4. 소스 코드 복사 및 권한 설정
COPY . .
RUN chmod -R 777 /app

# Hugging Face 기본 포트
EXPOSE 7860

# 5. 실행 명령
# POT 서버를 먼저 배경에서 띄우고, 5초 대기 후 파이썬 메인 앱을 실행합니다.
CMD ["sh", "-c", "node /opt/bgutil/build/server.js & sleep 5 && python main.py"]