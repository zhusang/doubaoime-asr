#!/bin/bash
# 豆包语音识别服务 — 一键启动脚本
# 包含依赖安装 + 服务启动，容器重启后执行此脚本即可恢复

set -e

PROJECT_DIR="/home/node/.openclaw/workspace/doubaoime-asr"
LOG_PREFIX="[doubaoime-asr-bootstrap]"

echo "$LOG_PREFIX 开始初始化..."

# 1. 检查服务是否已经在运行
if command -v pm2 &>/dev/null && pm2 pid doubaoime-asr &>/dev/null; then
    PID=$(pm2 pid doubaoime-asr 2>/dev/null)
    if [ -n "$PID" ] && [ "$PID" != "0" ] && kill -0 "$PID" 2>/dev/null; then
        # 验证 HTTP 是否真的可用
        if curl -sf http://localhost:8081/health &>/dev/null; then
            echo "$LOG_PREFIX 服务已在运行 (PID: $PID)，跳过"
            exit 0
        fi
    fi
fi

echo "$LOG_PREFIX 安装系统依赖..."
apt-get update -qq 2>/dev/null
apt-get install -y -qq python3-pip libopus0 ffmpeg 2>/dev/null

echo "$LOG_PREFIX 安装 PM2..."
npm install -g pm2 2>/dev/null | tail -1

echo "$LOG_PREFIX 安装 Python 依赖..."
pip3 install -e "$PROJECT_DIR" aiohttp cryptography --break-system-packages -q 2>/dev/null

echo "$LOG_PREFIX 启动服务..."
cd "$PROJECT_DIR"

# 如果 pm2 里有残留进程先删除
pm2 delete doubaoime-asr 2>/dev/null || true

pm2 start server.py --name doubaoime-asr --interpreter python3
pm2 save

# 等待并验证
sleep 3
if curl -sf http://localhost:8081/health &>/dev/null; then
    echo "$LOG_PREFIX ✅ 服务启动成功 http://localhost:8081"
else
    echo "$LOG_PREFIX ❌ 服务启动失败，查看日志: pm2 logs doubaoime-asr"
    exit 1
fi
