import os
import re
import tempfile
import uvicorn
import google.generativeai as genai
from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import yt_dlp
from faster_whisper import WhisperModel

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY 환경변수가 없습니다.")
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("models/gemini-1.5-flash")

print("Whisper 모델 로딩 중...")
whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
print("Whisper 모델 로딩 완료!")

COOKIE_FILE_PATH = None
youtube_cookies = os.environ.get("YOUTUBE_COOKIES")
if youtube_cookies:
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(youtube_cookies.strip())
            COOKIE_FILE_PATH = f.name
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
            ),
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
    text = re.sub(r"WEBVTT|Kind:.*|Language:.*", "", raw_sub)
    text = re.sub(r"\d+\n", "", text)
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
    return " ".join(text.split())

@app.get("/")
def home():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return JSONResponse({"status": "ok", "message": "server is running"})

@app.post("/process")
async def process_video(url: str = Form(...)):
    transcript = ""
    title = "요리 영상"

    try:
        # 1) 자막 추출 시도
        print("--- [Step 1] 자막 추출 시도 ---")
        with tempfile.TemporaryDirectory() as tmp_dir:
            sub_template = os.path.join(tmp_dir, "sub.%(ext)s")
            ydl_opts_sub = get_ydl_opts(download_audio=False, outtmpl=sub_template)

            with yt_dlp.YoutubeDL(ydl_opts_sub) as ydl:
                info = ydl.extract_info(url, download=True)
                if info:
                    title = info.get("title", "요리 영상")

            for f_name in os.listdir(tmp_dir):
                if f_name.endswith((".vtt", ".srt")):
                    sub_path = os.path.join(tmp_dir, f_name)
                    with open(sub_path, "r", encoding="utf-8") as f:
                        raw_sub = f.read()
                    transcript = clean_subtitle_text(raw_sub)
                    if transcript.strip():
                        print("✅ 자막 획득 성공:", f_name)
                        break

        # 2) 자막 없으면 오디오 다운로드 후 Whisper
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

                if not os.path.exists(downloaded_path):
                    candidates = [
                        os.path.join(audio_dir, x)
                        for x in os.listdir(audio_dir)
                        if os.path.isfile(os.path.join(audio_dir, x))
                    ]
                    if not candidates:
                        return {"status": "error", "message": "오디오 파일 다운로드 실패"}
                    downloaded_path = candidates[0]

                print("다운로드된 오디오:", downloaded_path)

                segments, _ = whisper_model.transcribe(
                    downloaded_path,
                    language="ko",
                    beam_size=1
                )
                transcript = " ".join(seg.text for seg in segments)

        if not transcript.strip():
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
            return {"status": "error", "message": "Gemini 응답이 비어 있습니다."}

        return {
            "status": "success",
            "title": title,
            "recipe": recipe_text,
            "method": "Subtitle" if transcript else "Whisper"
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)