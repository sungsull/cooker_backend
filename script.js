const btn = document.getElementById('btn');
const status = document.getElementById('status');
const urlInput = document.getElementById('urlInput');
const result = document.getElementById('result');

async function startProcess() {
    const url = urlInput.value.trim();
    if (!url) return alert("유튜브 링크를 입력해 주세요!");

    btn.disabled = true;
    result.innerText = "";

    try {
        // 1단계: 오디오 URL 추출
        status.innerText = "🔍 1단계: 영상 정보 확인 중...";
        const fd1 = new FormData();
        fd1.append("url", url);

        const res1 = await fetch('/get_audio_url', { method: 'POST', body: fd1 });
        const data1 = await res1.json();
        if (data1.status !== "success") throw new Error(data1.message);

        // 2단계: 서버에서 Whisper 음성 인식
        status.innerText = "🧠 2단계: AI 음성 분석 중... (1~2분 소요될 수 있습니다)";
        const fd2 = new FormData();
        fd2.append("audio_url", data1.audio_url);

        const res2 = await fetch('/transcribe', { method: 'POST', body: fd2 });
        const data2 = await res2.json();
        if (data2.status !== "success") throw new Error(data2.message);

        // 3단계: Gemini로 레시피 요약
        status.innerText = "✍️ 3단계: 요리 전문가 Gemini가 요약 중...";
        const fd3 = new FormData();
        fd3.append("transcript", data2.text);
        fd3.append("video_title", data1.title);

        const res3 = await fetch('/summarize', { method: 'POST', body: fd3 });
        const data3 = await res3.json();
        if (data3.status !== "success") throw new Error(data3.message);

        result.innerText = data3.recipe;
        status.innerText = "✨ 요약이 완료되었습니다!";

    } catch (e) {
        console.error("실행 에러:", e);
        const msg = e.message.includes("fetch") ? "네트워크 확인 요망" : e.message;
        status.innerText = "❌ 에러 발생: " + msg;
        result.innerText = "";
    } finally {
        btn.disabled = false;
        btn.innerText = "다시 요약하기";
    }
}

btn.addEventListener('click', startProcess);