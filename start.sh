#!/usr/bin/env bash
echo "=== Vision AI Scanner 起動 ==="

# ポート5000を使用中のプロセスを確認・停止
PID=$(lsof -ti :5000 2>/dev/null)
if [ -n "$PID" ]; then
    echo "[!] ポート5000を使用中のプロセス(PID:${PID})を停止します..."
    kill -9 $PID 2>/dev/null
    sleep 1
fi

echo "[OK] Flask起動中..."
python app.py
