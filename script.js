const btn = document.getElementById('btn');
const status = document.getElementById('status');
const urlInput = document.getElementById('urlInput');
const result = document.getElementById('result');

async function startProcess() {
    const url = urlInput.value.trim();
    if (!url) return alert("유튜브 링크를 입력해 주세요!");

    btn.disabled = true;
    result.innerText = "";
    status.innerText = "⏳ AI가 영상을 분석 중입니다... (1~2분 소요)";

    try {
        const fd = new FormData();
        fd.append("url", url);

        const res = await fetch('/process', { method: 'POST', body: fd });
        const data = await res.json();

        if (data.status !== "success") throw new Error(data.message);

        result.innerText = data.recipe;
        status.innerText = "✨ 요약이 완료되었습니다!";

    } catch (e) {
        status.innerText = "❌ 에러 발생: " + e.message;
        result.innerText = "";
    } finally {
        btn.disabled = false;
        btn.innerText = "다시 요약하기";
    }
}

btn.addEventListener('click', startProcess);
