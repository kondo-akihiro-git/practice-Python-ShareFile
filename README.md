# シェアファイル（ShareFile）

Ubuntu PC と iPhone の間で、ファイルを双方向に共有する個人用の Web システムです。Tailscale VPN の中だけで動き、独自のログインはありません。

<kbd>
<img width="603" height="1311" alt="IMG_2296" src="https://github.com/user-attachments/assets/682afacc-12f5-4e40-aa8a-8811f81f9c91" />
</kbd>
</br></br>

<kbd>
<img width="603" height="1311" alt="IMG_2297" src="https://github.com/user-attachments/assets/b1ec5207-a9dc-4208-aa17-d2c86713a1f9" />
</kbd>
</br></br>

<kbd>
<img width="933" height="274" alt="Screenshot from 2026-11-10 17-22-45" src="https://github.com/user-attachments/assets/04a232f2-00d7-48e0-a502-299c2b7715a7" />
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

## ディレクトリ

- `app/`: サーバーと画面（`static/`）
- `config/sharefile.env`: 設定
- `shared/`: 共有フォルダ
- `trash/`: 削除したファイルの退避先
- `logs/`: ログ
- `tests/`: テスト
- `docs/`: 手順書とテスト結果
- `start.sh`、`stop.sh`: 起動・停止スクリプト

