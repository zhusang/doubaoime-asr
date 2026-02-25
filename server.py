"""
豆包语音识别 HTTP + WebSocket 服务

API:
  POST /transcribe         — 非流式识别 (multipart file)
  POST /transcribe/stream  — 流式识别 (multipart file → NDJSON)
  WS   /ws/realtime        — 实时流式识别 (浏览器边录边传)
  GET  /health             — 健康检查
  GET  /                   — H5 页面
"""

import asyncio
import json
import os
import subprocess
import tempfile
from pathlib import Path

import aiohttp
from aiohttp import web
from doubaoime_asr import transcribe, transcribe_stream, ASRConfig, ResponseType
from doubaoime_asr.asr import DoubaoASR

# 配置
HOST = os.environ.get("ASR_HOST", "0.0.0.0")
PORT = int(os.environ.get("ASR_PORT", "8081"))
CREDENTIAL_PATH = os.environ.get(
    "ASR_CREDENTIAL_PATH",
    str(Path(__file__).parent / "credentials.json"),
)

config = ASRConfig(credential_path=CREDENTIAL_PATH)


# ============================================================
# 工具函数
# ============================================================

def _guess_suffix(part) -> str:
    filename = getattr(part, 'filename', None) or ''
    if '.' in filename:
        return '.' + filename.rsplit('.', 1)[-1].lower()
    ct = part.headers.get('Content-Type', '') if hasattr(part, 'headers') else ''
    mime_map = {
        'audio/wav': '.wav', 'audio/x-wav': '.wav', 'audio/wave': '.wav',
        'audio/mp3': '.mp3', 'audio/mpeg': '.mp3',
        'audio/mp4': '.m4a', 'audio/x-m4a': '.m4a', 'audio/aac': '.m4a',
        'audio/ogg': '.ogg', 'audio/opus': '.ogg',
        'audio/webm': '.webm',
        'audio/flac': '.flac', 'audio/x-flac': '.flac',
    }
    for mime, ext in mime_map.items():
        if mime in ct:
            return ext
    return '.wav'

_NEEDS_CONVERT = {'.webm', '.ogg', '.m4a', '.aac', '.opus'}

def _convert_to_wav(src_path: str) -> str:
    dst = src_path + '.wav'
    subprocess.run(
        ['ffmpeg', '-y', '-i', src_path, '-ar', '16000', '-ac', '1', '-f', 'wav', dst],
        capture_output=True, check=True, timeout=30,
    )
    return dst


# ============================================================
# HTTP 路由
# ============================================================

async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "doubaoime-asr"})


async def handle_transcribe(request: web.Request) -> web.Response:
    try:
        reader = await request.multipart()
        audio_data = None
        suffix = '.wav'
        async for part in reader:
            if part.name == "file":
                suffix = _guess_suffix(part)
                audio_data = await part.read()
                break
        if not audio_data:
            return web.json_response({"ok": False, "error": "缺少 file 字段"}, status=400)

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio_data)
            tmp_path = f.name

        wav_path = None
        try:
            if suffix in _NEEDS_CONVERT:
                wav_path = _convert_to_wav(tmp_path)
                actual_path = wav_path
            else:
                actual_path = tmp_path
            result = await transcribe(actual_path, config=config)
            return web.json_response({"ok": True, "text": result})
        finally:
            os.unlink(tmp_path)
            if wav_path and os.path.exists(wav_path):
                os.unlink(wav_path)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def handle_transcribe_stream(request: web.Request) -> web.StreamResponse:
    response = web.StreamResponse(
        status=200,
        headers={"Content-Type": "application/x-ndjson; charset=utf-8"},
    )
    await response.prepare(request)
    try:
        reader = await request.multipart()
        audio_data = None
        suffix = '.wav'
        async for part in reader:
            if part.name == "file":
                suffix = _guess_suffix(part)
                audio_data = await part.read()
                break
        if not audio_data:
            await response.write(
                (json.dumps({"type": "error", "error": "缺少 file 字段"}) + "\n").encode()
            )
            return response

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio_data)
            tmp_path = f.name

        wav_path = None
        try:
            if suffix in _NEEDS_CONVERT:
                wav_path = _convert_to_wav(tmp_path)
                actual_path = wav_path
            else:
                actual_path = tmp_path
            async for resp in transcribe_stream(actual_path, config=config):
                line = {"type": resp.type.name, "text": resp.text, "is_final": resp.is_final}
                if resp.type == ResponseType.ERROR:
                    line["error"] = resp.error_msg
                await response.write((json.dumps(line, ensure_ascii=False) + "\n").encode())
        finally:
            os.unlink(tmp_path)
            if wav_path and os.path.exists(wav_path):
                os.unlink(wav_path)
    except Exception as e:
        await response.write((json.dumps({"type": "error", "error": str(e)}) + "\n").encode())
    return response


# ============================================================
# WebSocket 实时流式识别
# ============================================================

async def handle_ws_realtime(request: web.Request) -> web.WebSocketResponse:
    """
    WebSocket 实时流式语音识别

    协议:
      客户端 → 服务端:
        - 二进制帧: 16-bit PCM, 16kHz, mono 音频数据
        - 文本 "EOS": 结束信号
      服务端 → 客户端:
        - JSON 文本帧: {"type": "INTERIM_RESULT"|"FINAL_RESULT"|..., "text": "..."}
    """
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def audio_source():
        """异步迭代器，从队列中读取 PCM 数据"""
        while True:
            chunk = await audio_queue.get()
            if chunk is None:
                break
            yield chunk

    async def run_asr():
        """运行 ASR 引擎并将结果发回 WebSocket"""
        try:
            async with DoubaoASR(config) as asr:
                async for resp in asr.transcribe_realtime(audio_source()):
                    if ws.closed:
                        break
                    msg = {
                        "type": resp.type.name,
                        "text": resp.text,
                        "is_final": resp.is_final,
                    }
                    if resp.type == ResponseType.ERROR:
                        msg["error"] = resp.error_msg
                    await ws.send_json(msg)
        except Exception as e:
            if not ws.closed:
                await ws.send_json({"type": "ERROR", "text": "", "error": str(e)})

    # 启动 ASR 任务
    asr_task = asyncio.create_task(run_asr())

    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.BINARY:
                await audio_queue.put(msg.data)
            elif msg.type == aiohttp.WSMsgType.TEXT:
                if msg.data.strip().upper() == "EOS":
                    await audio_queue.put(None)
            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                break
    finally:
        await audio_queue.put(None)
        await asr_task

    return ws


# ============================================================
# 页面 & 应用
# ============================================================

async def handle_index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(Path(__file__).parent / "index.html")


def create_app() -> web.Application:
    app = web.Application(client_max_size=50 * 1024 * 1024)

    @web.middleware
    async def cors_middleware(request, handler):
        if request.method == "OPTIONS":
            resp = web.Response()
        else:
            resp = await handler(request)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "*"
        return resp

    app.middlewares.append(cors_middleware)

    app.router.add_get("/", handle_index)
    app.router.add_get("/health", handle_health)
    app.router.add_post("/transcribe", handle_transcribe)
    app.router.add_post("/transcribe/stream", handle_transcribe_stream)
    app.router.add_get("/ws/realtime", handle_ws_realtime)
    return app


if __name__ == "__main__":
    print(f"🎙️  豆包语音识别服务启动: http://{HOST}:{PORT}")
    print(f"📁 凭据路径: {CREDENTIAL_PATH}")
    print(f"🔌 WebSocket 实时识别: ws://{HOST}:{PORT}/ws/realtime")
    web.run_app(create_app(), host=HOST, port=PORT)
