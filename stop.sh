#!/usr/bin/env bash
# シェアファイル 停止スクリプト。Tailscale全体や他のアプリは停止しません。
set -u
cd "$(dirname "$(readlink -f "$0")")" || exit 1
if [ ! -t 0 ] && [ -z "${SHAREFILE_IN_TERM:-}" ] && command -v gnome-terminal >/dev/null; then
  exec gnome-terminal --title="シェアファイル 停止" -- env SHAREFILE_IN_TERM=1 "$PWD/$(basename "$0")"
fi
ROOT="$PWD"
PID_FILE="$ROOT/.run/sharefile.pid"
PORT="$(".venv/bin/python" -c 'from app.config import load_settings; print(load_settings().port)' 2>/dev/null || echo 8765)"
TS_PORT="$(grep -E '^SHAREFILE_TAILSCALE_HTTPS_PORT=' config/sharefile.env 2>/dev/null | cut -d= -f2 | tr -d ' ')"
TS_PORT="${SHAREFILE_TAILSCALE_HTTPS_PORT:-${TS_PORT:-8443}}"

pause_if_tty() { if [ -t 0 ]; then echo; read -r -t 15 -p "Enterキーで画面を閉じます..." _ || true; fi; }

# 本システムが追加したTailscale Serve設定(自分のポートのみ)を解除
if command -v tailscale >/dev/null && tailscale serve status 2>/dev/null | grep -q "127.0.0.1:$PORT"; then
  if tailscale serve --https="$TS_PORT" off >/dev/null 2>&1; then
    echo "Tailscale Serve (HTTPS $TS_PORT) を解除しました"
  else
    echo "⚠ Tailscale Serveの解除に失敗しました。手動: tailscale serve --https=$TS_PORT off"
  fi
fi

if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE")"
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null && tr '\0' ' ' < "/proc/$PID/cmdline" | grep -q -- "-m app"; then
    kill -TERM "$PID"
    for _ in $(seq 1 40); do kill -0 "$PID" 2>/dev/null || break; sleep 0.25; done
    if kill -0 "$PID" 2>/dev/null; then kill -KILL "$PID" 2>/dev/null; fi
    rm -f "$PID_FILE"
    echo "✅ シェアファイルを停止しました"
    pause_if_tty
    exit 0
  fi
  rm -f "$PID_FILE"
fi
echo "シェアファイルは起動していません"
pause_if_tty
exit 0
