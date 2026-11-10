# シェアファイル 利用手順（README.mdではなく簡易手順書）

## 起動
ファイルマネージャーでこのフォルダを開き、`ShareFile-start.desktop` をダブルクリックします。
- 初回のみ: 仮想環境(.venv)作成と依存パッケージのインストールが自動で行われます。
- 2回目以降は数秒で起動します。二重起動はしません。
- 起動後、Ubuntu側ブラウザで http://127.0.0.1:8765/ が開きます。
- ダブルクリックで「信頼されていない」と出る場合: 右クリック →「起動を許可」（初回のみ）。

## 停止
`ShareFile-stop.desktop` をダブルクリック（または `./stop.sh`）。シェアファイルのプロセスと、本システムが設定したTailscale Serve(HTTPSポート8443)のみ停止・解除します。

## iPhoneから使う（Tailscale）
1. UbuntuとiPhoneの両方でTailscaleにログインして接続済みにする。
2. Ubuntuにtailscaleをインストール済みであること（未導入なら https://tailscale.com/download/linux ）。
3. 一度だけ: `sudo tailscale set --operator=$USER`（sudoなしで tailscale serve を実行するため）。
4. TailnetでHTTPS証明書(MagicDNS + HTTPS)が有効であること（管理画面 DNS設定）。
5. start.sh が `tailscale serve --bg --https=8443 http://127.0.0.1:8765` を自動実行し、起動画面に `https://<ホスト名>.<tailnet>.ts.net:8443/` が表示されます。iPhoneのSafari/Chromeでそのまま開きます。
- Tailscale Funnel（インターネット公開）は使いません。アプリは127.0.0.1のみで待ち受けます。
- 独自ログインがないため、同じTailnetの全端末が操作可能です。必要ならTailscale ACLでこのPC(tcp:8443)への接続元をiPhoneに限定してください（管理画面 Access controls）。

## 設定
`config/sharefile.env`（環境変数 `SHAREFILE_*` が優先）。共有フォルダ、ポート、最大アップロードサイズ(MB)、ログ先、Tailscale HTTPSポートなど。変更後は再起動。

## ファイルの場所
- 共有フォルダ: `shared/`（ファイルマネージャーと双方向に同じ実体）
- ゴミ箱: `trash/`（Webで削除した物の退避先。共有フォルダ外。必要なら手動で戻す／削除）
- ログ: `logs/server.log`

## テスト
`.venv/bin/pip install -r requirements-dev.txt && .venv/bin/pytest`
結果の記録: `docs/test-results.md`
