#!/usr/bin/env bash
# シェアファイル 起動スクリプト（ダブルクリック用の ShareFile-start.desktop から呼ばれます）
set -u
cd "$(dirname "$(readlink -f "$0")")" || exit 1
ROOT="$PWD"
RUN_DIR="$ROOT/.run"
PID_FILE="$RUN_DIR/sharefile.pid"
VENV="$ROOT/.venv"

fail() {
  echo
  echo "❌ 起動に失敗しました: $1" >&2
  [ -n "${2:-}" ] && echo "   対処: $2" >&2
  pause_if_tty
  exit 1
}
pause_if_tty() {
  if [ -t 0 ]; then echo; read -r -p "Enterキーでこの画面を閉じます..." _; fi
}
step() { echo "▶ $1"; }

mkdir -p "$RUN_DIR" "$ROOT/logs"

step "Python環境を確認しています"
command -v python3 >/dev/null || fail "python3が見つかりません" "sudo apt install python3 python3-venv"
if [ ! -x "$VENV/bin/python" ]; then
  echo "  初回セットアップ: 仮想環境(.venv)を作成します"
  python3 -m venv "$VENV" || fail "仮想環境を作成できませんでした" "sudo apt install python3-venv を実行してください"
fi
REQ_HASH="$(sha256sum "$ROOT/requirements.txt" | cut -d' ' -f1)"
if [ ! -f "$VENV/.requirements.sha256" ] || [ "$(cat "$VENV/.requirements.sha256")" != "$REQ_HASH" ]; then
  echo "  依存パッケージをインストールします（初回のみ）"
  "$VENV/bin/pip" install --quiet --disable-pip-version-check -r "$ROOT/requirements.txt" \
    || fail "依存パッケージのインストールに失敗しました" "インターネット接続を確認して再度実行してください"
  echo "$REQ_HASH" > "$VENV/.requirements.sha256"
fi

step "設定を確認しています"
[ -f "$ROOT/config/sharefile.env" ] || fail "設定ファイル config/sharefile.env がありません"
SETTINGS="$("$VENV/bin/python" - <<'PY'
from app.config import load_settings
s = load_settings()
s.shared_dir.mkdir(parents=True, exist_ok=True)
s.trash_dir.mkdir(parents=True, exist_ok=True)
s.log_dir.mkdir(parents=True, exist_ok=True)
import os
from app.config import _read_env_file, CONFIG_FILE
v = _read_env_file(CONFIG_FILE); v.update({k: x for k, x in os.environ.items() if k.startswith("SHAREFILE_")})
print(s.host, s.port, v.get("SHAREFILE_TAILSCALE_HTTPS_PORT", "8443"), s.shared_dir, s.log_dir)
PY
)" || fail "設定の読み込みに失敗しました" "config/sharefile.env の内容を確認してください"
read -r HOST PORT TS_PORT SHARED LOGDIR <<<"$SETTINGS"
[ -d "$SHARED" ] || fail "共有フォルダを用意できません: $SHARED"
echo "  共有フォルダ: $SHARED"

is_running() {
  [ -f "$PID_FILE" ] || return 1
  local pid; pid="$(cat "$PID_FILE")"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q -- "-m app"
}
healthy() { curl -fsS --max-time 2 "http://127.0.0.1:$PORT/api/config" >/dev/null 2>&1; }

step "シェアファイルを起動しています"
if is_running && healthy; then
  echo "  すでに起動しています（二重起動はしません）"
else
  if is_running; then kill "$(cat "$PID_FILE")" 2>/dev/null; sleep 1; fi
  if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
    fail "ポート $PORT は別のプログラムが使用中です" "config/sharefile.env の SHAREFILE_PORT を変更してください"
  fi
  [ -f "$LOGDIR/server.log" ] && [ "$(stat -c %s "$LOGDIR/server.log")" -gt 5242880 ] && mv -f "$LOGDIR/server.log" "$LOGDIR/server.log.1"
  setsid nohup "$VENV/bin/python" -m app >> "$LOGDIR/server.log" 2>&1 < /dev/null &
  echo $! > "$PID_FILE"
  for _ in $(seq 1 60); do healthy && break; sleep 0.25; done
  if ! healthy; then
    echo "--- ログ末尾 ($LOGDIR/server.log) ---" >&2
    tail -n 15 "$LOGDIR/server.log" >&2
    fail "サーバーが起動しませんでした" "上のログを確認してください"
  fi
fi

LOCAL_URL="http://127.0.0.1:$PORT/"
TS_URL=""
step "Tailscaleを確認しています"
if ! command -v tailscale >/dev/null; then
  echo "  ⚠ tailscaleコマンドが見つかりません。iPhoneから使うにはTailscaleのインストールとログインが必要です。"
elif ! TS_JSON="$(tailscale status --json 2>/dev/null)"; then
  echo "  ⚠ Tailscaleに接続できません。tailscale up を実行してログインしてください。"
else
  TS_INFO="$(printf '%s' "$TS_JSON" | "$VENV/bin/python" -c 'import json,sys; d=json.load(sys.stdin); print(d.get("BackendState",""), (d.get("Self") or {}).get("DNSName","").rstrip("."))')"
  read -r TS_STATE TS_DNS <<<"$TS_INFO"
  if [ "$TS_STATE" != "Running" ]; then
    echo "  ⚠ Tailscaleは未接続です (状態: $TS_STATE)。接続してから再度起動してください。"
  else
    echo "  Tailscale接続: OK ($TS_DNS)"
    if tailscale serve status 2>/dev/null | grep -q "127.0.0.1:$PORT"; then
      echo "  Tailscale Serve: 設定済み"
    else
      echo "  Tailscale Serveを設定します（HTTPS ポート $TS_PORT → 127.0.0.1:$PORT。Funnelは使いません）"
      if ! tailscale serve --bg --https="$TS_PORT" "http://127.0.0.1:$PORT" >"$RUN_DIR/serve.out" 2>&1; then
        echo "  ⚠ Tailscale Serveの設定に失敗しました:"; sed 's/^/    /' "$RUN_DIR/serve.out"
        echo "    権限不足の場合は一度だけ「sudo tailscale set --operator=\$USER」を実行してください。"
      fi
    fi
    if tailscale serve status 2>/dev/null | grep -q "127.0.0.1:$PORT"; then
      TS_URL="https://$TS_DNS:$TS_PORT/"
    fi
  fi
fi

echo
echo "=============================================="
echo " ✅ シェアファイルが起動しました"
echo "   Ubuntu(このPC) : $LOCAL_URL"
if [ -n "$TS_URL" ]; then echo "   iPhone(Tailscale): $TS_URL"; else echo "   iPhone(Tailscale): （Tailscale Serve未設定のため利用不可）"; fi
echo "   共有フォルダ   : $SHARED"
echo "   停止           : ShareFile-stop.desktop をダブルクリック（または ./stop.sh）"
echo "=============================================="
if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && command -v xdg-open >/dev/null; then
  xdg-open "$LOCAL_URL" >/dev/null 2>&1 &
fi
if [ -t 0 ]; then echo; read -r -t 20 -p "Enterキーで画面を閉じます（20秒後に自動で閉じます。サーバーは動き続けます）" _ || true; fi
exit 0
