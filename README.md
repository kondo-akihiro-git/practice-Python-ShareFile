# シェアファイル（ShareFile）

Ubuntu PC と iPhone の間で、ファイルを双方向に共有する個人用の Web システムです。Tailscale VPN の中だけで動き、独自のログインはありません。

<kbd>
<img width="778" height="287" alt="スクリーンショット 2025-12-02 19 59 02" src="https://github.com/user-attachments/assets/69477807-46c0-4646-bd75-e4ffbc73348e" />
</kbd>
</br></br>

## 特徴

- Ubuntu の `shared/` フォルダの実ファイルを直接扱います。ファイルマネージャーでの追加・削除も、約5秒で Web に反映されます。
- アップロードしたファイルは、圧縮・変換せずバイナリのまま保存します。アップロード後に SHA-256 を照合します。
- 一覧、検索、並び替え、フォルダ作成、名前変更、移動、削除（ゴミ箱へ移動）に対応しています。
- 画像、PDF、動画、テキストをブラウザでプレビューできます。
- iPhone では、共有シートから写真アプリやファイルアプリへ保存できます。

## 技術構成

- Python 3.12、Starlette、uvicorn
- フロントエンド: 標準の HTML・CSS・JavaScript（フレームワークなし）
- ネットワーク: Tailscale Serve（HTTPS、tailnet 内のみ）

## 使い方

起動・停止、iPhone の設定、ショートカットの作り方は [docs/起動停止手順.md](docs/起動停止手順.md) を参照してください。

- 起動: デスクトップの「シェアファイル 起動」をダブルクリック
- 停止: デスクトップの「シェアファイル 停止」をダブルクリック

## ディレクトリ

- `app/`: サーバーと画面（`static/`）
- `config/sharefile.env`: 設定
- `shared/`: 共有フォルダ
- `trash/`: 削除したファイルの退避先
- `logs/`: ログ
- `tests/`: テスト
- `docs/`: 手順書とテスト結果
- `start.sh`、`stop.sh`: 起動・停止スクリプト

## テスト

    .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/pytest

結果は [docs/test-results.md](docs/test-results.md) にあります。iPhone 実機での確認状況もここに記載します。
