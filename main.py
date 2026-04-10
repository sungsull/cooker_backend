import os
import tempfile
import requests
import uvicorn
import google.generativeai as genai
from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import yt_dlp

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel('models/gemini-1.5-flash')

import whisper
print("Whisper 모델 로딩 중...")
whisper_model = whisper.load_model("base")
print("Whisper 모델 로딩 완료!")

@app.get("/")
def home():
    return FileResponse("index.html")

@app.get("/script.js")
def serve_script():
    return FileResponse("script.js")

@app.post("/get_audio_url")
async def get_audio_url(url: str = Form(...)):
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['web'],
                },
                'youtubepot-bgutilhttp': {
                    'base_url': ['http://127.0.0.1:4416']
                }
            },
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                "status": "success",
                "audio_url": info['url'],
                "title": info.get('title', '요리 영상')
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/transcribe")
async def transcribe_audio(audio_url: str = Form(...)):
    tmp_path = None
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(audio_url, headers=headers, stream=True, timeout=60)
        response.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            downloaded = 0
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                if downloaded > 50 * 1024 * 1024:
                    break
            tmp_path = f.name

        result = whisper_model.transcribe(tmp_path, language="ko")
        return {"status": "success", "text": result["text"]}

    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

@app.post("/summarize")
async def summarize_recipe(transcript: str = Form(...), video_title: str = Form(...)):
    try:
        prompt = (
            f"요리 전문가로서 다음 내용을 아래 형식으로 요약해줘. 마크다운(**) 금지.\n\n"
            f"[요리 이름]\n[재료]\n[조리 순서]\n[꿀팁]\n\n"
            f"제목: {video_title}\n내용: {transcript[:8000]}"
        )
        response = gemini_model.generate_content(prompt)
        return {"status": "success", "recipe": response.text.strip()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)
