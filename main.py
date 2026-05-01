import os
import re
import tempfile
import traceback
import uvicorn
import google.generativeai as genai
import yt_dlp

from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from faster_whisper import WhisperModel

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일(js, css) 제공
# 폴더 구조:
# project/
# ├─ main.py
# ├─ index.html
# └─ static/
#    └─ script.js
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Gemini 설정
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY 환경변수가 없습니다.")

genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("models/gemini-1.5-flash")

# Whisper 모델 로드
print("Whisper 모델 로딩 중...")
whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
print("Whisper 모델 로딩 완료!")

# YouTube 쿠키 파일 준비
COOKIE_FILE_PATH = None
youtube_cookies = os.environ.get("YOUTUBE_COOKIES")

if youtube_cookies:
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            delete=False,
            encoding="utf-8"
        ) as f:
            f.write(youtube_cookies.strip())
            COOKIE_FILE_PATH = f.name
        print("쿠키 파일 생성 완료:", COOKIE_FILE_PATH)
    except Exception as e:
        print("쿠키 파일 생성 실패:", e)


def get_ydl_opts(download_audio=False, outtmpl=None):
    opts = {
        "quiet": False,
        "no_warnings": True,
        "skip_download": not download_audio,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["ko", "ko-KR", "en"],
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 "
                "Mobile/15E148 Safari/604.1"
            )
        },
    }

    if outtmpl:
        opts["outtmpl"] = outtmpl

    if COOKIE_FILE_PATH:
        opts["cookiefile"] = COOKIE_FILE_PATH

    if download_audio:
        opts["format"] = "bestaudio/best"

    return opts


def clean_subtitle_text(raw_sub: str) -> str:
    text = raw_sub

    # 기본 메타 제거
    text = re.sub(r"WEBVTT", "", text)
    text = re.sub(r"Kind:.*", "", text)
    text = re.sub(r"Language:.*", "", text)

    # SRT 번호 줄 제거
    text = re.sub(r"^\d+\s*$", "", text, flags=re.MULTILINE)

    # VTT/SRT 타임스탬프 제거
    text = re.sub(
        r"\d{2}:\d{2}:\d{2}\.\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}",
        "",
        text
    )
    text = re.sub(
        r"\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}",
        "",
        text
    )

    # 태그 제거
    text = re.sub(r"<[^>]+>", "", text)

    # 공백 정리
    text = " ".join(text.split())
    return text.strip()


@app.get("/")
def home():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return JSONResponse({
        "status": "error",
        "message": "index.html 파일이 없습니다."
    })


@app.get("/health")
def health():
    return {
        "status": "ok",
        "gemini": bool(GEMINI_API_KEY),
        "static_exists": os.path.isdir("static"),
        "index_exists": os.path.exists("index.html")
    }


@app.post("/process")
async def process_video(url: str = Form(...)):
    transcript = ""
    title = "요리 영상"
    method = ""

    try:
        print("=" * 60)
        print("요청 들어옴:", url)

        # 1단계: 자막 추출 시도
        print("--- [Step 1] 자막 추출 시도 ---")
        with tempfile.TemporaryDirectory() as tmp_dir:
            sub_template = os.path.join(tmp_dir, "sub.%(ext)s")
            ydl_opts_sub = get_ydl_opts(download_audio=False, outtmpl=sub_template)

            with yt_dlp.YoutubeDL(ydl_opts_sub) as ydl:
                info = ydl.extract_info(url, download=True)
                if info:
                    title = info.get("title", "요리 영상")

            subtitle_files = [
                os.path.join(tmp_dir, f_name)
                for f_name in os.listdir(tmp_dir)
                if f_name.endswith((".vtt", ".srt"))
            ]

            for sub_path in subtitle_files:
                try:
                    with open(sub_path, "r", encoding="utf-8") as f:
                        raw_sub = f.read()

                    cleaned = clean_subtitle_text(raw_sub)
                    if cleaned:
                        transcript = cleaned
                        method = "Subtitle"
                        print("✅ 자막 획득 성공:", os.path.basename(sub_path))
                        break
                except Exception as e:
                    print("자막 파일 읽기 실패:", sub_path, e)

        # 2단계: 자막 없으면 오디오 다운로드 후 Whisper
        if not transcript.strip():
            print("--- [Step 2] 자막 없음. 오디오 분석 시작 ---")
            with tempfile.TemporaryDirectory() as audio_dir:
                audio_template = os.path.join(audio_dir, "audio.%(ext)s")
                ydl_opts_audio = get_ydl_opts(download_audio=True, outtmpl=audio_template)

                with yt_dlp.YoutubeDL(ydl_opts_audio) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if info:
                        title = info.get("title", title)

                    downloaded_path = ydl.prepare_filename(info)

                # 실제 파일이 prepare_filename 경로와 다를 경우 대비
                if not os.path.exists(downloaded_path):
                    candidates = [
                        os.path.join(audio_dir, x)
                        for x in os.listdir(audio_dir)
                        if os.path.isfile(os.path.join(audio_dir, x))
                    ]
                    if not candidates:
                        return {
                            "status": "error",
                            "message": "오디오 파일 다운로드 실패"
                        }
                    downloaded_path = candidates[0]

                print("다운로드된 오디오:", downloaded_path)

                segments, _ = whisper_model.transcribe(
                    downloaded_path,
                    language="ko",
                    beam_size=1
                )

                transcript = " ".join(seg.text for seg in segments).strip()
                method = "Whisper"

        if not transcript:
            return {
                "status": "error",
                "message": "데이터를 가져오지 못했습니다. 자막/음성이 없거나 다운로드가 차단되었습니다."
            }

        print("전사 길이:", len(transcript))

        # 3단계: Gemini 요약
        prompt = (
            "요리 전문가로서 다음 내용을 아래 형식으로 요약해줘. "
            "마크다운(**) 금지.\n\n"
            "[요리 이름]\n[재료]\n[조리 순서]\n[꿀팁]\n\n"
            f"제목: {title}\n"
            f"내용: {transcript[:8000]}"
        )

        gemini_resp = gemini_model.generate_content(prompt)
        recipe_text = getattr(gemini_resp, "text", "").strip()

        if not recipe_text:
            return {
                "status": "error",
                "message": "Gemini 응답이 비어 있습니다."
            }

        return {
            "status": "success",
            "title": title,
            "recipe": recipe_text,
            "method": method
        }

    except Exception as e:
        traceback.print_exc()
        return {
            "status": "error",
            "message": str(e)
        }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)