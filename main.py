import os
import re
import ssl
import tempfile
import traceback
import uvicorn
import google.generativeai as genai
import yt_dlp

from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from faster_whisper import WhisperModel

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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


def get_ydl_opts(download_audio=False, outtmpl=None, insecure_ssl=False):
    opts = {
        "quiet": False,
        "verbose": True,
        "no_warnings": True,
        "skip_download": not download_audio,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["ko", "ko-KR", "en"],
        "retries": 3,
        "fragment_retries": 3,
        "extractor_retries": 3,

        # IPv4 강제
        "source_address": "0.0.0.0",

        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        },
        "extractor_args": {
            "youtube": {
                "player_client": ["web", "ios"]
            }
        }
    }

    if insecure_ssl:
        opts["nocheckcertificate"] = True

    if outtmpl:
        opts["outtmpl"] = outtmpl

    if COOKIE_FILE_PATH:
        opts["cookiefile"] = COOKIE_FILE_PATH

    if download_audio:
        opts["format"] = "bestaudio/best"

    return opts


def clean_subtitle_text(raw_sub: str) -> str:
    text = raw_sub
    text = re.sub(r"WEBVTT", "", text)
    text = re.sub(r"Kind:.*", "", text)
    text = re.sub(r"Language:.*", "", text)
    text = re.sub(r"^\d+\s*$", "", text, flags=re.MULTILINE)
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
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.split()).strip()


def extract_info_with_ssl_retry(url, download, ydl_opts_normal, ydl_opts_insecure):
    """
    먼저 일반 SSL 검증 상태로 시도하고,
    SSL 관련 오류일 때만 마지막으로 nocheckcertificate=True로 한 번 더 시도
    """
    try:
        with yt_dlp.YoutubeDL(ydl_opts_normal) as ydl:
            info = ydl.extract_info(url, download=download)
            return info
    except Exception as e:
        msg = str(e)
        ssl_like = (
            "UNEXPECTED_EOF_WHILE_READING" in msg
            or "EOF occurred in violation of protocol" in msg
            or "SSL" in msg
            or isinstance(e, ssl.SSLError)
        )

        if not ssl_like:
            raise

        print("SSL 관련 오류 감지. nocheckcertificate=True로 1회 재시도합니다.")
        with yt_dlp.YoutubeDL(ydl_opts_insecure) as ydl:
            info = ydl.extract_info(url, download=download)
            return info


@app.get("/")
def home():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return JSONResponse({
        "status": "error",
        "message": "index.html 파일이 없습니다."
    })


@app.get("/script.js")
def get_script():
    if os.path.exists("script.js"):
        return FileResponse("script.js", media_type="application/javascript")
    return JSONResponse({
        "status": "error",
        "message": "script.js 파일이 없습니다."
    }, status_code=404)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "gemini": bool(GEMINI_API_KEY),
        "index_exists": os.path.exists("index.html"),
        "script_exists": os.path.exists("script.js")
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

            ydl_opts_sub_normal = get_ydl_opts(
                download_audio=False,
                outtmpl=sub_template,
                insecure_ssl=False
            )
            ydl_opts_sub_insecure = get_ydl_opts(
                download_audio=False,
                outtmpl=sub_template,
                insecure_ssl=True
            )

            info = extract_info_with_ssl_retry(
                url=url,
                download=True,
                ydl_opts_normal=ydl_opts_sub_normal,
                ydl_opts_insecure=ydl_opts_sub_insecure
            )

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
        if not transcript:
            print("--- [Step 2] 자막 없음. 오디오 분석 시작 ---")
            with tempfile.TemporaryDirectory() as audio_dir:
                audio_template = os.path.join(audio_dir, "audio.%(ext)s")

                ydl_opts_audio_normal = get_ydl_opts(
                    download_audio=True,
                    outtmpl=audio_template,
                    insecure_ssl=False
                )
                ydl_opts_audio_insecure = get_ydl_opts(
                    download_audio=True,
                    outtmpl=audio_template,
                    insecure_ssl=True
                )

                info = extract_info_with_ssl_retry(
                    url=url,
                    download=True,
                    ydl_opts_normal=ydl_opts_audio_normal,
                    ydl_opts_insecure=ydl_opts_audio_insecure
                )

                if info:
                    title = info.get("title", title)

                downloaded_path = None
                if info:
                    try:
                        with yt_dlp.YoutubeDL(ydl_opts_audio_normal) as ydl:
                            downloaded_path = ydl.prepare_filename(info)
                    except Exception:
                        pass

                if not downloaded_path or not os.path.exists(downloaded_path):
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