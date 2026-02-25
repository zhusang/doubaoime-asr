# 豆包语音识别服务 — API 开发文档

## 目录

- [概述](#概述)
- [服务配置](#服务配置)
- [API 总览](#api-总览)
- [1. 健康检查](#1-健康检查)
- [2. 文件识别（非流式）](#2-文件识别非流式)
- [3. 文件识别（流式）](#3-文件识别流式)
- [4. 实时流式语音识别（WebSocket）](#4-实时流式语音识别websocket)
  - [连接](#41-连接)
  - [音频格式要求](#42-音频格式要求)
  - [通信协议](#43-通信协议)
  - [消息类型详解](#44-消息类型详解)
  - [完整会话流程](#45-完整会话流程)
  - [错误处理](#46-错误处理)
- [客户端示例代码](#客户端示例代码)
  - [Python](#python-示例)
  - [JavaScript / 浏览器](#javascript--浏览器示例)
  - [Node.js](#nodejs-示例)
  - [Go](#go-示例)
- [注意事项](#注意事项)

---

## 概述

基于[豆包输入法语音识别](https://github.com/starccy/doubaoime-asr)封装的 HTTP + WebSocket 服务，提供三种识别方式：

| 方式 | 适用场景 | 延迟 |
|------|---------|------|
| `POST /transcribe` | 录好的音频文件，只需要最终结果 | 高（等全部识别完） |
| `POST /transcribe/stream` | 录好的音频文件，需要中间过程 | 中（NDJSON 流式返回） |
| `WS /ws/realtime` | **实时麦克风 / 流式音频源** | **低（边说边出字）** |

---

## 服务配置

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `ASR_HOST` | `0.0.0.0` | 监听地址 |
| `ASR_PORT` | `8081` | 监听端口 |
| `ASR_CREDENTIAL_PATH` | `./credentials.json` | 豆包设备凭据缓存路径 |

首次启动会自动注册虚拟设备并缓存凭据，无需手动配置 API Key。

---

## API 总览

```
GET  /health             健康检查
POST /transcribe         文件识别（非流式，返回完整结果）
POST /transcribe/stream  文件识别（流式，返回 NDJSON）
WS   /ws/realtime        实时流式语音识别（WebSocket）
GET  /                   Web UI 页面
```

---

## 1. 健康检查

```
GET /health
```

**响应：**

```json
{"ok": true, "service": "doubaoime-asr"}
```

---

## 2. 文件识别（非流式）

```
POST /transcribe
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | file | ✅ | 音频文件（WAV/MP3/M4A/OGG/FLAC/WebM） |

**成功响应：**

```json
{"ok": true, "text": "识别出来的文字"}
```

**失败响应：**

```json
{"ok": false, "error": "错误信息"}
```

**cURL 示例：**

```bash
curl -X POST http://localhost:8081/transcribe \
  -F "file=@recording.wav"
```

---

## 3. 文件识别（流式）

```
POST /transcribe/stream
Content-Type: multipart/form-data
```

参数同上。响应为 NDJSON（每行一个 JSON 对象）：

```jsonl
{"type": "TASK_STARTED", "text": "", "is_final": false}
{"type": "SESSION_STARTED", "text": "", "is_final": false}
{"type": "INTERIM_RESULT", "text": "你好", "is_final": false}
{"type": "INTERIM_RESULT", "text": "你好世界", "is_final": false}
{"type": "FINAL_RESULT", "text": "你好世界。", "is_final": true}
{"type": "SESSION_FINISHED", "text": "", "is_final": false}
```

---

## 4. 实时流式语音识别（WebSocket）

> **这是本服务的核心能力。** 客户端建立 WebSocket 连接后，持续发送 PCM 音频帧，服务端实时返回识别结果。

### 4.1 连接

```
ws://<host>:8081/ws/realtime
```

- 无需认证（服务端内部管理豆包凭据）
- 每个 WebSocket 连接对应一个独立的 ASR 会话
- 连接断开时会话自动结束

### 4.2 音频格式要求

| 参数 | 值 | 说明 |
|------|---|------|
| 编码 | **PCM (Linear PCM)** | 原始未压缩音频 |
| 位深 | **16-bit** | signed int16, 小端序 (Little-Endian) |
| 采样率 | **16000 Hz** | 16kHz |
| 声道 | **单声道 (Mono)** | 1 channel |

> ⚠️ 必须严格遵守此格式。发送其他格式（MP3、Opus、Float32 等）将导致识别失败或乱码。

**每帧数据大小计算：**

```
每帧字节数 = 采样率 × 位深/8 × 声道数 × 帧时长(秒)
           = 16000 × 2 × 1 × 0.02
           = 640 bytes (20ms 一帧)
```

建议每 **20ms** 发送一帧（640 bytes），也可以攒到更大的 chunk 一起发（如 100ms = 3200 bytes），但不要超过 **500ms**。

### 4.3 通信协议

```
┌─────────┐                          ┌─────────┐
│  Client  │                          │  Server  │
└────┬─────┘                          └────┬─────┘
     │                                     │
     │  ── WebSocket Connect ──────────►   │
     │                                     │
     │  ── Binary: PCM audio chunk ────►   │
     │  ── Binary: PCM audio chunk ────►   │
     │  ── Binary: PCM audio chunk ────►   │
     │                                     │
     │  ◄── Text: {"type":"INTERIM_RESULT",│
     │       "text":"你好","is_final":false}│
     │                                     │
     │  ── Binary: PCM audio chunk ────►   │
     │  ── Binary: PCM audio chunk ────►   │
     │                                     │
     │  ◄── Text: {"type":"FINAL_RESULT",  │
     │       "text":"你好世界。",            │
     │       "is_final":true}              │
     │                                     │
     │  ── Text: "EOS" ───────────────►    │  (结束信号)
     │                                     │
     │  ◄── Text: {"type":"SESSION_FINISHED"│
     │       ...}                          │
     │                                     │
     │  ── WebSocket Close ────────────►   │
     │                                     │
```

#### 客户端 → 服务端

| 帧类型 | 内容 | 说明 |
|--------|------|------|
| **Binary** | PCM 音频数据 | 16-bit, 16kHz, mono, Little-Endian |
| **Text** | `"EOS"` | 结束信号，告知服务端音频发送完毕 |

#### 服务端 → 客户端

所有响应均为 **Text 帧**，内容为 JSON：

```typescript
{
  "type": string,      // 消息类型（见下表）
  "text": string,      // 识别文本（中间结果或最终结果）
  "is_final": boolean, // 是否为最终结果
  "error"?: string     // 仅 ERROR 类型包含
}
```

### 4.4 消息类型详解

| type | is_final | 说明 |
|------|----------|------|
| `TASK_STARTED` | `false` | ASR 任务已创建 |
| `SESSION_STARTED` | `false` | 会话已初始化，可以开始发送音频 |
| `VAD_START` | `false` | 检测到语音活动开始（用户开始说话） |
| `INTERIM_RESULT` | `false` | **中间识别结果**（会被后续结果覆盖） |
| `FINAL_RESULT` | `true` | **最终识别结果**（一段话说完后确认的文字） |
| `SESSION_FINISHED` | `false` | 会话已结束 |
| `ERROR` | `false` | 错误，包含 `error` 字段 |

**重要说明：**

- `INTERIM_RESULT` 是不稳定的，同一段语音的中间结果会被不断更新覆盖，仅用于 UI 实时展示
- `FINAL_RESULT` 是稳定的最终文字，当用户说完一段话（VAD 检测到静音）后返回
- 一次连接中可能产生**多个** `FINAL_RESULT`（用户说了多段话），应将所有 `FINAL_RESULT` 的 `text` **拼接**起来

### 4.5 完整会话流程

```
1. 客户端连接 WebSocket
2. 服务端自动初始化 ASR 会话
3. 服务端返回 TASK_STARTED → SESSION_STARTED
4. 客户端开始持续发送 Binary PCM 帧
5. 服务端返回 VAD_START（检测到说话）
6. 服务端持续返回 INTERIM_RESULT（中间结果实时更新）
7. 用户停顿后，服务端返回 FINAL_RESULT（这一段话的最终结果）
8. 如果用户继续说话，重复 5-7
9. 客户端发送 Text "EOS" 结束音频流
10. 服务端返回最后的 FINAL_RESULT（如有）和 SESSION_FINISHED
11. 客户端关闭 WebSocket
```

### 4.6 错误处理

| 场景 | 处理方式 |
|------|---------|
| WebSocket 连接失败 | 检查服务地址和端口，确认服务正在运行 |
| 收到 `ERROR` 消息 | 读取 `error` 字段，记录日志，考虑重连 |
| 连接意外断开 | 实现自动重连机制（建议指数退避） |
| 长时间无响应 | 客户端设置心跳/超时检测 |

---

## 客户端示例代码

### Python 示例

```python
import asyncio
import json
import wave
import websockets

ASR_WS_URL = "ws://localhost:8081/ws/realtime"

async def realtime_asr_from_file(audio_path: str):
    """
    从 WAV 文件读取 PCM 数据，通过 WebSocket 实时发送并获取识别结果
    """
    # 读取 WAV 文件
    with wave.open(audio_path, 'rb') as wf:
        assert wf.getsampwidth() == 2, "需要 16-bit 音频"
        assert wf.getframerate() == 16000, "需要 16kHz 采样率"
        assert wf.getnchannels() == 1, "需要单声道"
        pcm_data = wf.readframes(wf.getnframes())

    async with websockets.connect(ASR_WS_URL) as ws:
        # 启动接收协程
        results = []

        async def receiver():
            async for message in ws:
                data = json.loads(message)
                msg_type = data["type"]
                text = data.get("text", "")

                if msg_type == "INTERIM_RESULT":
                    print(f"  [中间] {text}")
                elif msg_type == "FINAL_RESULT":
                    print(f"  [最终] {text}")
                    results.append(text)
                elif msg_type == "ERROR":
                    print(f"  [错误] {data.get('error')}")
                    break
                elif msg_type == "SESSION_FINISHED":
                    break

        recv_task = asyncio.create_task(receiver())

        # 模拟实时发送：每 20ms 发 640 bytes
        chunk_size = 640  # 20ms @ 16kHz 16-bit mono
        for i in range(0, len(pcm_data), chunk_size):
            chunk = pcm_data[i:i + chunk_size]
            await ws.send(chunk)
            await asyncio.sleep(0.02)  # 模拟实时

        # 发送结束信号
        await ws.send("EOS")

        # 等待接收完成
        await recv_task

        full_text = "".join(results)
        print(f"\n完整识别结果: {full_text}")
        return full_text


async def realtime_asr_from_microphone():
    """
    从麦克风实时采集并识别（需要 sounddevice 库）
    """
    import sounddevice as sd
    import numpy as np

    SAMPLE_RATE = 16000
    CHANNELS = 1
    CHUNK_DURATION = 0.02  # 20ms
    CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_DURATION)

    async with websockets.connect(ASR_WS_URL) as ws:
        # 接收协程
        async def receiver():
            async for message in ws:
                data = json.loads(message)
                if data["type"] == "INTERIM_RESULT":
                    print(f"\r  💬 {data['text']}", end="", flush=True)
                elif data["type"] == "FINAL_RESULT":
                    print(f"\r  ✅ {data['text']}")
                elif data["type"] == "SESSION_FINISHED":
                    break

        recv_task = asyncio.create_task(receiver())

        # 麦克风采集
        print("🎤 开始录音... (Ctrl+C 停止)")
        loop = asyncio.get_event_loop()

        def audio_callback(indata, frames, time_info, status):
            # Float32 → Int16
            int16_data = (indata[:, 0] * 32767).astype(np.int16)
            pcm_bytes = int16_data.tobytes()
            asyncio.run_coroutine_threadsafe(ws.send(pcm_bytes), loop)

        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype='float32',
            blocksize=CHUNK_SAMPLES,
            callback=audio_callback,
        )

        try:
            with stream:
                await asyncio.sleep(3600)  # 最长录 1 小时
        except KeyboardInterrupt:
            pass
        finally:
            await ws.send("EOS")
            await recv_task


# 运行
if __name__ == "__main__":
    # 文件识别
    # asyncio.run(realtime_asr_from_file("test.wav"))

    # 麦克风实时识别
    asyncio.run(realtime_asr_from_microphone())
```

**依赖安装：**

```bash
pip install websockets
# 麦克风采集需要额外安装：
pip install sounddevice numpy
```

---

### JavaScript / 浏览器示例

```javascript
class RealtimeASR {
  constructor(serverUrl = 'ws://localhost:8081/ws/realtime') {
    this.serverUrl = serverUrl;
    this.ws = null;
    this.audioContext = null;
    this.workletNode = null;
    this.mediaStream = null;
    this.onInterim = null;   // callback(text)
    this.onFinal = null;     // callback(text)
    this.onError = null;     // callback(error)
    this.finalTexts = [];
  }

  async start() {
    // 1. 获取麦克风
    this.mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true }
    });

    // 2. 创建 AudioContext (16kHz)
    this.audioContext = new AudioContext({ sampleRate: 16000 });
    const source = this.audioContext.createMediaStreamSource(this.mediaStream);

    // 3. 注册 AudioWorklet 处理器 (Float32 → Int16 PCM)
    const processorCode = `
      class PCMProcessor extends AudioWorkletProcessor {
        process(inputs) {
          const input = inputs[0];
          if (input && input[0]) {
            const float32 = input[0];
            const int16 = new Int16Array(float32.length);
            for (let i = 0; i < float32.length; i++) {
              const s = Math.max(-1, Math.min(1, float32[i]));
              int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
            }
            this.port.postMessage(int16.buffer, [int16.buffer]);
          }
          return true;
        }
      }
      registerProcessor('pcm-processor', PCMProcessor);
    `;
    const blob = new Blob([processorCode], { type: 'application/javascript' });
    const url = URL.createObjectURL(blob);
    await this.audioContext.audioWorklet.addModule(url);
    URL.revokeObjectURL(url);

    this.workletNode = new AudioWorkletNode(this.audioContext, 'pcm-processor');
    source.connect(this.workletNode);
    this.workletNode.connect(this.audioContext.destination);

    // 4. 连接 WebSocket
    this.ws = new WebSocket(this.serverUrl);
    this.ws.binaryType = 'arraybuffer';
    this.finalTexts = [];

    this.ws.onopen = () => {
      // 开始发送 PCM 数据
      this.workletNode.port.onmessage = (e) => {
        if (this.ws?.readyState === WebSocket.OPEN) {
          this.ws.send(e.data);
        }
      };
    };

    this.ws.onmessage = (e) => {
      const data = JSON.parse(e.data);
      switch (data.type) {
        case 'INTERIM_RESULT':
          this.onInterim?.(this.finalTexts.join('') + data.text);
          break;
        case 'FINAL_RESULT':
          this.finalTexts.push(data.text);
          this.onFinal?.(this.finalTexts.join(''));
          break;
        case 'ERROR':
          this.onError?.(data.error);
          break;
      }
    };

    this.ws.onerror = () => this.onError?.('WebSocket 连接失败');
  }

  stop() {
    // 发送结束信号
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send('EOS');
      setTimeout(() => this.ws?.close(), 2000);
    }

    // 清理资源
    if (this.workletNode) {
      this.workletNode.port.onmessage = null;
      this.workletNode.disconnect();
    }
    this.mediaStream?.getTracks().forEach(t => t.stop());
    this.audioContext?.close();
  }

  getFullText() {
    return this.finalTexts.join('');
  }
}

// 使用示例
const asr = new RealtimeASR('ws://localhost:8081/ws/realtime');

asr.onInterim = (text) => {
  document.getElementById('result').textContent = text;  // 实时更新
};
asr.onFinal = (text) => {
  document.getElementById('result').textContent = text;  // 确认结果
};
asr.onError = (err) => console.error('ASR Error:', err);

// 开始
document.getElementById('startBtn').onclick = () => asr.start();

// 停止
document.getElementById('stopBtn').onclick = () => asr.stop();
```

---

### Node.js 示例

```javascript
const WebSocket = require('ws');
const fs = require('fs');

const ASR_WS_URL = 'ws://localhost:8081/ws/realtime';

/**
 * 从 PCM 文件进行实时流式识别
 * @param {string} pcmFilePath - 16kHz 16-bit mono PCM 文件
 */
async function realtimeASR(pcmFilePath) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(ASR_WS_URL);
    const results = [];

    ws.on('open', () => {
      console.log('WebSocket 已连接');

      // 读取 PCM 文件并分块发送
      const pcmData = fs.readFileSync(pcmFilePath);
      const chunkSize = 640; // 20ms
      let offset = 0;

      const sendInterval = setInterval(() => {
        if (offset >= pcmData.length) {
          clearInterval(sendInterval);
          ws.send('EOS');
          return;
        }
        const chunk = pcmData.slice(offset, offset + chunkSize);
        ws.send(chunk);
        offset += chunkSize;
      }, 20);
    });

    ws.on('message', (data) => {
      const msg = JSON.parse(data.toString());
      switch (msg.type) {
        case 'INTERIM_RESULT':
          process.stdout.write(`\r  💬 ${msg.text}`);
          break;
        case 'FINAL_RESULT':
          console.log(`\n  ✅ ${msg.text}`);
          results.push(msg.text);
          break;
        case 'SESSION_FINISHED':
          ws.close();
          resolve(results.join(''));
          break;
        case 'ERROR':
          console.error('  ❌', msg.error);
          ws.close();
          reject(new Error(msg.error));
          break;
      }
    });

    ws.on('error', reject);
  });
}

// 运行
realtimeASR('test.pcm').then(text => {
  console.log('\n完整结果:', text);
});
```

**依赖安装：**

```bash
npm install ws
```

---

### Go 示例

```go
package main

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/gorilla/websocket"
)

type ASRResponse struct {
	Type    string `json:"type"`
	Text    string `json:"text"`
	IsFinal bool   `json:"is_final"`
	Error   string `json:"error,omitempty"`
}

func main() {
	wsURL := "ws://localhost:8081/ws/realtime"

	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		log.Fatal("连接失败:", err)
	}
	defer conn.Close()

	// 接收协程
	done := make(chan struct{})
	var results []string

	go func() {
		defer close(done)
		for {
			_, message, err := conn.ReadMessage()
			if err != nil {
				return
			}
			var resp ASRResponse
			json.Unmarshal(message, &resp)

			switch resp.Type {
			case "INTERIM_RESULT":
				fmt.Printf("\r  💬 %s", resp.Text)
			case "FINAL_RESULT":
				fmt.Printf("\n  ✅ %s\n", resp.Text)
				results = append(results, resp.Text)
			case "SESSION_FINISHED":
				return
			case "ERROR":
				fmt.Printf("\n  ❌ %s\n", resp.Error)
				return
			}
		}
	}()

	// 读取 PCM 文件并发送
	pcmData, err := os.ReadFile("test.pcm")
	if err != nil {
		log.Fatal(err)
	}

	chunkSize := 640 // 20ms
	for i := 0; i < len(pcmData); i += chunkSize {
		end := i + chunkSize
		if end > len(pcmData) {
			end = len(pcmData)
		}
		conn.WriteMessage(websocket.BinaryMessage, pcmData[i:end])
		time.Sleep(20 * time.Millisecond)
	}

	// 发送结束信号
	conn.WriteMessage(websocket.TextMessage, []byte("EOS"))

	<-done
	fmt.Println("\n完整结果:", join(results))
}

func join(s []string) string {
	r := ""
	for _, v := range s {
		r += v
	}
	return r
}
```

---

## 注意事项

### 音频格式

- WebSocket 端点**仅接受原始 PCM 数据**，不接受 WAV 头、MP3、Opus 等编码格式
- 如果音频源不是 16kHz/16-bit/Mono，需要客户端先进行重采样和格式转换
- 浏览器 `AudioContext({ sampleRate: 16000 })` 会自动重采样

### 性能建议

- 每 **20ms** 发送一个 640 bytes 的音频帧是最佳实践
- 也可以攒多帧一起发（如 100ms = 3200 bytes），但间隔不要超过 500ms
- 不要一次性发送大量数据（会失去"实时"效果）

### 并发

- 每个 WebSocket 连接是独立的 ASR 会话
- 服务支持多个并发连接，但过多并发可能触发豆包服务端限流
- 建议单实例并发不超过 **5** 个

### 网络

- WebSocket 连接对网络延迟敏感，建议客户端与服务部署在同一局域网或低延迟网络
- 如需公网访问，建议使用 Nginx 反向代理并启用 WebSocket 支持：

```nginx
location /ws/ {
    proxy_pass http://127.0.0.1:8081;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s;
}
```

### 凭据

- 服务首次启动会自动注册虚拟设备，凭据缓存在 `credentials.json`
- 此文件包含设备 ID 和 Token，**请勿泄露**
- Token 过期后会自动刷新，无需手动干预

### 已知限制

- 本服务基于豆包输入法的非官方协议，**不保证长期可用**
- 识别质量主要针对中文普通话优化
- 单次会话建议不超过 **5 分钟**（更长的录音建议分段）
