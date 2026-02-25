FROM python:3.11-slim

# 系统依赖: libopus (Opus编解码), ffmpeg (音频格式转换)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libopus0 ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先复制依赖文件，利用 Docker 缓存
COPY pyproject.toml ./
COPY doubaoime_asr/ ./doubaoime_asr/

# 安装 Python 依赖
RUN pip install --no-cache-dir . aiohttp

# 复制服务代码和前端页面
COPY server.py ./
COPY index.html ./

# 凭据目录 (运行时挂载或首次自动生成)
RUN mkdir -p /app/data
ENV ASR_CREDENTIAL_PATH=/app/data/credentials.json
ENV ASR_HOST=0.0.0.0
ENV ASR_PORT=8081

EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8081/health')" || exit 1

CMD ["python", "server.py"]
