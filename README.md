# doubaoime-asr

豆包输入法语音识别 Python 客户端 + HTTP/WebSocket 服务。

## 免责声明

本项目通过对安卓豆包输入法客户端通信协议分析并参考客户端代码实现，**非官方提供的 API**。

- 本项目仅供学习和研究目的
- 不保证未来的可用性和稳定性
- 服务端协议可能随时变更导致功能失效

---

## 🚀 一键部署（Docker）

最简单的部署方式，无需手动安装任何依赖：

```bash
git clone https://github.com/starccy/doubaoime-asr.git
cd doubaoime-asr
docker compose up -d
```

服务启动后：
- **API**: `http://localhost:8081`
- **Web UI**: `http://localhost:8081/`
- **健康检查**: `http://localhost:8081/health`
- **WebSocket 实时识别**: `ws://localhost:8081/ws/realtime`

首次启动会自动注册虚拟设备，凭据缓存在 `./data/credentials.json`，无需配置 API Key。

### 自定义端口

```bash
# 方式1: 环境变量
ASR_PORT=9090 docker compose up -d

# 方式2: .env 文件
cp .env.example .env
# 编辑 .env 中的 ASR_PORT
docker compose up -d
```

### 查看日志

```bash
docker compose logs -f
```

### Nginx 反向代理（可选）

如需公网访问或 HTTPS，参考以下 Nginx 配置：

```nginx
server {
    listen 443 ssl;
    server_name asr.example.com;

    ssl_certificate     /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:8081;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 3600s;
    }
}
```

---

## 📡 HTTP 服务 API

服务提供三种识别方式（详见 [API.md](API.md)）：

| 端点 | 方式 | 适用场景 |
|------|------|---------|
| `POST /transcribe` | HTTP | 上传文件，返回完整结果 |
| `POST /transcribe/stream` | HTTP | 上传文件，NDJSON 流式返回 |
| `WS /ws/realtime` | WebSocket | **实时麦克风，边说边出字** |

```bash
# 快速测试
curl -X POST http://localhost:8081/transcribe -F "file=@test.wav"
```

---

## 安装（作为 Python 库使用）

```bash
# 从本地安装
git clone https://github.com/starccy/doubaoime-asr.git
cd doubaoime-asr
pip install -e .

# 或从 Git 仓库安装
pip install git+https://github.com/starccy/doubaoime-asr.git
```

### 系统依赖

本项目依赖 Opus 音频编解码库，需要先安装系统库：

```bash
# Debian/Ubuntu
sudo apt install libopus0

# Arch Linux
sudo pacman -S opus

# macOS
brew install opus
```

## 快速开始

### 基本用法

```python
import asyncio
from doubaoime_asr import transcribe, ASRConfig

async def main():
    # 配置（首次运行会自动注册设备，并将凭据保存到指定文件）
    config = ASRConfig(credential_path="./credentials.json")

    # 识别音频文件
    result = await transcribe("audio.wav", config=config)
    print(f"识别结果: {result}")

asyncio.run(main())
```

### 流式识别

如果需要获取中间结果或更详细的状态信息，可以使用 `transcribe_stream`：

```python
import asyncio
from doubaoime_asr import transcribe_stream, ASRConfig, ResponseType

async def main():
    config = ASRConfig(credential_path="./credentials.json")

    async for response in transcribe_stream("audio.wav", config=config):
        match response.type:
            case ResponseType.INTERIM_RESULT:
                print(f"[中间结果] {response.text}")
            case ResponseType.FINAL_RESULT:
                print(f"[最终结果] {response.text}")
            case ResponseType.ERROR:
                print(f"[错误] {response.error_msg}")

asyncio.run(main())
```

### 实时麦克风识别

实时语音识别需要配合音频采集库使用，请参考 [examples/mic_realtime.py](examples/mic_realtime.py)。

运行示例需要安装额外依赖：

```bash
pip install sounddevice numpy
# 或
pip install doubaoime-asr[examples]
```

## API 参考

### transcribe

非流式语音识别，直接返回最终结果。

```python
async def transcribe(
    audio: str | Path | bytes,
    *,
    config: ASRConfig | None = None,
    on_interim: Callable[[str], None] | None = None,
    realtime: bool = False,
) -> str
```

参数：
- `audio`: 音频文件路径或 PCM 字节数据
- `config`: ASR 配置
- `on_interim`: 中间结果回调
- `realtime`: 是否模拟实时发送（每个音频数据帧之间加入固定的发送延迟）
    - `True`: 模拟实时发送，加入固定的延迟，表现得更像正常的客户端，但会增加整体识别时间
    - `False`: 尽可能快地发送所有数据帧，整体识别时间更短（貌似也不会被风控）

### transcribe_stream

流式语音识别，返回 `ASRResponse` 异步迭代器。

```python
async def transcribe_stream(
    audio: str | Path | bytes,
    *,
    config: ASRConfig | None = None,
    realtime: bool = False,
) -> AsyncIterator[ASRResponse]
```

### transcribe_realtime

实时流式语音识别，接收 PCM 音频数据的异步迭代器。

```python
async def transcribe_realtime(
    audio_source: AsyncIterator[bytes],
    *,
    config: ASRConfig | None = None,
) -> AsyncIterator[ASRResponse]
```

### ASRConfig

配置类，支持以下主要参数：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `credential_path` | str | None | 凭据缓存文件路径 |
| `device_id` | str | None | 设备 ID（空则自动注册） |
| `token` | str | None | 认证 Token（空则自动获取） |
| `sample_rate` | int | 16000 | 采样率 |
| `channels` | int | 1 | 声道数 |
| `enable_punctuation` | bool | True | 是否启用标点 |

### ResponseType

响应类型枚举：

| 类型 | 说明 |
|------|------|
| `TASK_STARTED` | 任务已启动 |
| `SESSION_STARTED` | 会话已启动 |
| `VAD_START` | 检测到语音开始 |
| `INTERIM_RESULT` | 中间识别结果 |
| `FINAL_RESULT` | 最终识别结果 |
| `SESSION_FINISHED` | 会话结束 |
| `ERROR` | 错误 |

## 凭据管理

首次使用时会自动向服务器注册虚拟设备（设备参数定义在 `constants.py` 的 `DEFAULT_DEVICE_CONFIG` 中）并获取认证 Token。

推荐指定 `credential_path` 参数，凭据会自动缓存到文件，避免重复注册：

```python
config = ASRConfig(credential_path="~/.config/doubaoime-asr/credentials.json")
```
