import os
import time
import re
from fastapi import FastAPI
from pydantic import BaseModel
import yt_dlp
import whisper
import google.generativeai as genai
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from fastapi.responses import FileResponse

app = FastAPI()

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- [1단계] 설정 구간 ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel('models/gemini-1.5-flash')

# Whisper 모델 로드 (서버 시작 시 1회만 로드)
print("Whisper 모델 로딩 중...")
whisper_model = whisper.load_model("small")
print("Whisper 모델 로딩 완료!")

class VideoURL(BaseModel):
    url: str

# 메인 페이지: index.html 반환
@app.get("/")
def home():
    return FileResponse("index.html")

@app.post("/cook")
async def create_recipe(item: VideoURL):
    audio_file = "temp_audio.m4a"

    try:
        print(f"--- 1. 작업 시작: {item.url} ---")

        if os.path.exists(audio_file):
            os.remove(audio_file)

        # A. 오디오 다운로드
        ydl_opts = {
            'format': 'm4a/bestaudio/best',
            'outtmpl': 'temp_audio.%(ext)s',
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': ['ko', 'en'],
            'quiet': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(item.url, download=True)
            video_title = info.get('title', '제목 없음')
            video_description = info.get('description', '')[:500]

        print(f"--- 2. 다운로드 완료: {video_title} ---")

        # B. Whisper 음성 전사
        print("--- 3. Whisper 음성 인식 중 ---")
        result = whisper_model.transcribe(
            audio_file,
            language=None,
            task="transcribe",
            verbose=False,
            fp16=False,
            condition_on_previous_text=True,
            temperature=0.0,
        )

        transcript = result["text"].strip()
        detected_language = result.get("language", "unknown")
        print(f"--- 감지 언어: {detected_language}, 전사 길이: {len(transcript)}자 ---")

        if not transcript:
            return {"status": "error", "message": "음성 인식 결과가 없습니다."}

        # C. 자막 보조 데이터 수집
        subtitle_text = ""
        for ext in ["ko.vtt", "en.vtt", "ko.srt", "en.srt"]:
            sub_path = f"temp_audio.{ext}"
            if os.path.exists(sub_path):
                with open(sub_path, "r", encoding="utf-8") as f:
                    raw = f.read()
                    clean = re.sub(r'\d{2}:\d{2}[\d:,.]+\s*-->\s*\d{2}:\d{2}[\d:,.]+', '', raw)
                    clean = re.sub(r'<[^>]+>', '', clean)
                    clean = re.sub(r'WEBVTT.*?\n', '', clean)
                    subtitle_text = ' '.join(clean.split())[:2000]
                print(f"--- 자막 발견: {sub_path} ---")
                break

        # D. Gemini 요약
        print("--- 4. Gemini 레시피 요약 중 ---")

        context_parts = [f"[영상 제목]: {video_title}"]
        if video_description:
            context_parts.append(f"[영상 설명]: {video_description}")
        if subtitle_text:
            context_parts.append(f"[자막 보조 데이터]: {subtitle_text[:1000]}")
        context_parts.append(f"[음성 전사 원문]:\n{transcript[:8000]}")

        full_context = "\n\n".join(context_parts)

        prompt = f"""
너는 최고의 요리 전문 에디터야. 아래 내용을 바탕으로 깔끔한 레시피 요약본만 작성해줘.

{full_context}

[출력 형식]:
1. 요리 이름:
2. 핵심 재료:
3. 요리 순서:
4. 꿀팁:

- 마크다운 특수 기호(**)는 사용하지 마.
- 한국어로 작성해줘.
"""

        response = gemini_model.generate_content(prompt)

        # E. 임시 파일 정리
        for f in os.listdir("."):
            if f.startswith("temp_audio"):
                os.remove(f)

        print("--- 5. 완료! ---")
        return {
            "status": "success",
            "recipe": response.text.strip(),
            "debug": {
                "video_title": video_title,
                "detected_language": detected_language,
                "transcript_length": len(transcript),
            }
        }

    except Exception as e:
        for f in os.listdir("."):
            if f.startswith("temp_audio"):
                try: os.remove(f)
                except: pass
        print(f"!!! 에러 발생: {str(e)} !!!")
        return {"status": "error", "message": f"오류 발생: {str(e)}"}

if __name__ == "__main__":
    # Hugging Face Spaces 기본 포트 7860 유지
    uvicorn.run(app, host="0.0.0.0", port=7860)