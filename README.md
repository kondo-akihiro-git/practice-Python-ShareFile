# シェアファイル（ShareFile）

## 概要
このアプリは、**Ubuntu PCとiPhoneの間で、ファイルを双方向に共有できる**個人用Webアプリです。  
Tailscale VPNの中だけで動き、ログインは不要です。ファイルはUbuntuの`shared/`フォルダにそのまま保存されます。

<br>
主な機能
- iPhoneからのアップロード（複数可・保存先フォルダの選択・新規フォルダ作成）
- iPhoneへのダウンロード、「写真に保存」「ファイルに保存」
- 画像・PDF・動画・テキストのプレビュー
- 検索、並び替え、フォルダ作成、名前変更、移動、削除（`trash/`へ退避）
- Ubuntu側で`shared/`を変更すると、約5秒でWeb画面に反映
- 圧縮・変換をせず、SHA-256でアップロードの一致を確認
---

## 利用の流れ
1. `Ubuntu` : デスクトップの「シェアファイル 起動」をダブルクリック
2. `iPhone` : Tailscaleをオンにして、シェアファイルを開く
3. `iPhone → Ubuntu` : 「アップロード」でファイルを選んで送信し、Ubuntuの`shared/`フォルダで確認
4. `Ubuntu → iPhone` : `shared/`にファイルを置き、iPhoneの一覧から開いてダウンロード
5. `Ubuntu` : 使い終わったら「シェアファイル 停止」をダブルクリック

---

## 主な画面
- `トップ画面（iPhone）` : ファイル・フォルダの一覧、アップロード、フォルダ作成、検索、並び替えをする画面
<kbd>
<img width="603" height="1311" alt="IMG_2296" src="https://github.com/user-attachments/assets/682afacc-12f5-4e40-aa8a-8811f81f9c91" />
</kbd>
</br></br>


- `アップロード画面（iPhone）` : 保存先フォルダとファイルを選んで送信する画面。完了するとSHA-256の一致を表示
<kbd>
<img width="603" height="1311" alt="IMG_2297" src="https://github.com/user-attachments/assets/b1ec5207-a9dc-4208-aa17-d2c86713a1f9" />
</kbd>
</br></br>


- `共有フォルダ（Ubuntu）` : iPhoneから送ったファイルが、ファイルマネージャーの`shared/`にそのまま入っている様子
<kbd>
<img width="933" height="274" alt="Screenshot from 2026-11-10 17-22-45" src="https://github.com/user-attachments/assets/04a232f2-00d7-48e0-a502-299c2b7715a7" />
</kbd>
</br></br>


---

## フォルダ構成
- `app/`
  - `main.py` : Starletteのエントリポイント（API・ファイル配信）
  - `storage.py` : 共有フォルダの操作と安全対策（共有フォルダ外へのアクセス防止）
  - `config.py` : 設定の読み込み
  - `static/` : 画面（`index.html`・`app.js`・`style.css`）
- `config/`
  - `sharefile.env` : 設定（共有フォルダ・ポート・最大サイズなど）
- `shared/` : 共有フォルダ
- `trash/` : 削除したファイルの退避先
- `logs/` : ログ
- `tests/` : 機能・セキュリティ・大容量・ブラウザのテスト
- `docs/`
  - `起動停止手順.md` : 起動・停止・iPhone設定の手順
  - `test-results.md` : テスト結果
- `start.sh` / `stop.sh` : 起動・停止スクリプト
- `requirements.txt` : 依存ライブラリ定義
---

## 主な技術要件
- Python : バックエンド実装
- Starlette / uvicorn : Webフレームワーク・サーバー
- HTML / CSS / JavaScript : フロントエンド実装（ビルド不要）
- Tailscale Serve : iPhoneからのHTTPSアクセス（tailnet内のみ）
---

## 起動方法
起動・停止・iPhoneの設定は [docs/起動停止手順.md](docs/起動停止手順.md) を参照してください。
