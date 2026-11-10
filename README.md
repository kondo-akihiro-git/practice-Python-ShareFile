# シェアファイル（ShareFile）

Ubuntu PC と iPhone の間で、ファイルを双方向に共有する個人用 Web システムです。Tailscale VPN の中だけで動き、ログインは不要です。

左から、iPhone のトップ画面、アップロード画面、Ubuntu の共有フォルダです。

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

## 使い方

**iPhone → Ubuntu**
1. Ubuntu でデスクトップの「シェアファイル 起動」をダブルクリックします。
2. iPhone で Tailscale をオンにし、シェアファイルを開きます。
3. 「アップロード」でファイルを選び、保存先を決めて送ります。
4. Ubuntu の `shared/` フォルダに、そのままのファイルが入ります。

**Ubuntu → iPhone**
1. Ubuntu の `shared/` フォルダにファイルを置きます。
2. 数秒で iPhone の一覧に出ます。
3. ファイルを開き、「ダウンロード」か「写真に保存」で iPhone に取り込みます。

停止は「シェアファイル 停止」をダブルクリックします。設定方法は [docs/起動停止手順.md](docs/起動停止手順.md) を参照してください。

## できること

- アップロード（複数可）・ダウンロード。圧縮や変換はせず、SHA-256 で一致を確認します。
- 一覧、検索、並び替え、フォルダ作成、名前変更、移動、削除（`trash/` へ退避）。
- 画像・PDF・動画・テキストのプレビュー。
- `shared/` を直接見るので、Ubuntu 側の変更は約5秒で反映されます。

## 構成

Python 3.12、Starlette、uvicorn、標準の HTML・CSS・JavaScript、Tailscale Serve（HTTPS）。

- `app/`: サーバーと画面
- `config/sharefile.env`: 設定
- `shared/`: 共有フォルダ
- `trash/`、`logs/`: ゴミ箱、ログ
- `tests/`、`docs/`: テストと手順書
- `start.sh`、`stop.sh`: 起動・停止
