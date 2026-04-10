import os
import re
import tempfile
import uvicorn
import google.generativeai as genai
from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import yt_dlp
from faster_whisper import WhisperModel

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. Gemini 설정
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel('models/gemini-1.5-flash')

# 2. Whisper 모델 로드 (가벼운 tiny 버전)
print("Whisper 모델 로딩 중...")
whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
print("Whisper 모델 로딩 완료!")

# 3. [보완 1] 쿠키 파일 생성 (UTF-8 인코딩 명시)
COOKIE_FILE_PATH = None
youtube_cookies = os.environ.get("YOUTUBE_COOKIES")

if youtube_cookies:
    try:
        # 재욱님이 주신 고순도 쿠키 텍스트를 임시 파일로 변환
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write(youtube_cookies.strip())
            COOKIE_FILE_PATH = f.name
        print(f"✅ 쿠키 파일 생성 완료: {COOKIE_FILE_PATH}")
    except Exception as e:
        print(f"❌ 쿠키 생성 에러: {e}")

# 4. [보완 4] yt-dlp 보안 돌파 옵션 최적화
def get_ydl_opts():
    opts = {
        'format': 'ba/b', # 오디오 우선
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        # iOS 클라이언트와 사파리 헤더 조합이 현재 가장 차단율이 낮습니다.
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'web', 'mweb'],
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1',
        }
    }
    if COOKIE_FILE_PATH:
        opts['cookiefile'] = COOKIE_FILE_PATH
    return opts

def extract_video_id(url: str):
    patterns = [
        r'(?:v=)([a-zA-Z0-9_-]{11})',
        r'(?:youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'(?:shorts/)([a-zA-Z0-9_-]{11})',
        r'(?:embed/)([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

@app.get("/")
def home():
    return FileResponse("index.html")

@app.get("/script.js")
def serve_script():
    return FileResponse("script.js")

@app.post("/process")
async def process_video(url: str = Form(...)):
    tmp_path = None
    try:
        video_id = extract_video_id(url)
        if not video_id:
            return {"status": "error", "message": "유효한 YouTube URL이 아닙니다."}

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp_path = f.name

        ydl_opts = get_ydl_opts()
        ydl_opts['outtmpl'] = tmp_path

        # 다운로드 실행
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                raise Exception("유튜브 차단을 뚫지 못했습니다. 쿠키를 다시 확인해주세요.")
            title = info.get('title', '요리 영상')

        # [보완 2] Whisper 변환 및 빈 텍스트 체크
        segments, _ = whisper_model.transcribe(tmp_path, language="ko", beam_size=1)
        transcript = " ".join([seg.text for seg in segments])

        if not transcript.strip():
            return {"status": "error", "message": "음성 인식 결과가 비어있습니다. 소리가 없는 영상일 수 있습니다."}

        # Gemini 요약 (전문가 페르소나 적용)
        prompt = (
            f"요리 전문가로서 다음 내용을 아래 형식으로 요약해줘. 마크다운(**) 금지.\n\n"
            f"[요리 이름]\n[재료]\n[조리 순서]\n[꿀팁]\n\n"
            f"제목: {title}\n내용: {transcript[:8000]}"
        )
        gemini_resp = gemini_model.generate_content(prompt)

        return {
            "status": "success",
            "title": title,
            "recipe": gemini_resp.text.strip()
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}
    
    # [보완 3] 안전한 임시 파일 삭제
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except:
                pass

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)