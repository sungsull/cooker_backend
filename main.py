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

# 2. Whisper 모델 로드 (자막 없을 때만 사용됨)
print("Whisper 모델 로딩 중...")
whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
print("Whisper 모델 로딩 완료!")

# 쿠키 설정 (기존 로직 유지)
COOKIE_FILE_PATH = None
youtube_cookies = os.environ.get("YOUTUBE_COOKIES")
if youtube_cookies:
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write(youtube_cookies.strip())
            COOKIE_FILE_PATH = f.name
    except: pass

def get_ydl_opts(download_audio=False):
    opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': not download_audio,  # 자막만 딸 때는 True
        'writesubtitles': True,               # 공식 자막
        'writeautomaticsub': True,            # 자동 생성 자막
        'subtitleslangs': ['ko'],             # 한국어 우선
        'extractor_args': {'youtube': {'player_client': ['ios', 'web']}},
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1',
        }
    }
    if COOKIE_FILE_PATH:
        opts['cookiefile'] = COOKIE_FILE_PATH
    if download_audio:
        opts['format'] = 'ba/b'
    return opts

@app.get("/")
def home():
    return FileResponse("index.html")

@app.post("/process")
async def process_video(url: str = Form(...)):
    tmp_audio = None
    transcript = ""
    
    try:
        # [1단계] 자막 추출 시도 (다운로드 없이)
        print("--- [Step 1] 자막 추출 시도 ---")
        ydl_opts_sub = get_ydl_opts(download_audio=False)
        
        # 임시 폴더에서 자막 추출 작업
        with tempfile.TemporaryDirectory() as tmp_dir:
            ydl_opts_sub['outtmpl'] = os.path.join(tmp_dir, 'sub')
            with yt_dlp.YoutubeDL(ydl_opts_sub) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', '요리 영상')
                
                # 생성된 자막 파일 검색 (.vtt, .srt 등)
                for f_name in os.listdir(tmp_dir):
                    if f_name.endswith(('.vtt', '.srt')):
                        with open(os.path.join(tmp_dir, f_name), 'r', encoding='utf-8') as f:
                            raw_sub = f.read()
                            # 자막 타임라인 및 태그 제거 클리닝
                            clean_sub = re.sub(r'\d{2}:\d{2}.*?\n', '', raw_sub)
                            clean_sub = re.sub(r'<[^>]+>', '', clean_sub)
                            clean_sub = re.sub(r'WEBVTT|Kind:.*|Language:.*', '', clean_sub)
                            transcript = " ".join(clean_sub.split())
                        print("✅ 자막 획득 성공!")
                        break

        # [2단계] 자막 실패 시 오디오 다운로드 및 Whisper 가동
        if not transcript.strip():
            print("--- [Step 2] 자막 없음. 오디오 분석 시작 ---")
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                tmp_audio = f.name
            
            ydl_opts_audio = get_ydl_opts(download_audio=True)
            ydl_opts_audio['outtmpl'] = tmp_audio
            
            with yt_dlp.YoutubeDL(ydl_opts_audio) as ydl:
                ydl.download([url])
            
            segments, _ = whisper_model.transcribe(tmp_audio, language="ko", beam_size=1)
            transcript = " ".join([seg.text for seg in segments])

        if not transcript.strip():
            return {"status": "error", "message": "데이터를 가져오지 못했습니다. 차단되었거나 음성이 없습니다."}

        # [3단계] Gemini 요약
        prompt = (
            f"요리 전문가로서 다음 내용을 아래 형식으로 요약해줘. 마크다운(**) 금지.\n\n"
            f"[요리 이름]\n[재료]\n[조리 순서]\n[꿀팁]\n\n"
            f"제목: {title}\n내용: {transcript[:8000]}"
        )
        gemini_resp = gemini_model.generate_content(prompt)

        return {
            "status": "success",
            "title": title,
            "recipe": gemini_resp.text.strip(),
            "method": "Subtitle" if not tmp_audio else "Whisper"
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}
    
    finally:
        if tmp_audio and os.path.exists(tmp_audio):
            try: os.remove(tmp_audio)
            except: pass

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)