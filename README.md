# 当直表 一括作成システム

ICU当直・準夜当直・レジデント当直の3種類の当直表を、1画面でまとめて生成できるWebアプリケーションです。

## 概要

- Excelファイル（希望休・担当制限入力済み）をアップロードするだけで、制約充足ソルバー（CP-SAT）が最適な当直割当を自動生成します
- ICU・準夜・レジデントの3タイプをタブで切り替え、「全て作成」ボタンで同時生成も可能です
- 生成結果はExcelファイルとしてダウンロードできます（個別 / まとめてZIP）

## ディレクトリ構成

```
shift-maker/
├── general-shift-maker/     # 統合アプリ（メイン）
│   ├── main.py              # FastAPIサーバー
│   ├── solver.py            # CP-SAT統合ソルバー
│   ├── excel_handler.py     # Excel読み書き
│   ├── configs.py           # 当直タイプごとの設定（ShiftConfig）
│   ├── requirements.txt
│   └── static/
│       ├── index.html       # タブUI（ICU / 準夜 / レジデント）
│       ├── app.js           # フロントエンド状態管理
│       ├── style.css        # 共通スタイル
│       └── login.html       # 認証画面
├── icu-shift-maker/         # ICU専用アプリ（旧）
├── junya-shift-maker/       # 準夜専用アプリ（旧）
├── resident-shift-maker/    # レジデント専用アプリ（旧）
└── exel-to-kingotime/       # 勤怠管理補助ツール
```

> 日常運用は `general-shift-maker` を使用してください。個別アプリは参照用として残しています。

## セットアップ

### 前提条件

- Python 3.11 以上

### インストール

```bash
cd general-shift-maker
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 起動方法

```bash
cd general-shift-maker
APP_PASSWORD=your_password SECRET_KEY=your_secret_key HTTPS_ONLY=false python main.py
```

| 環境変数 | 必須 | 説明 |
|---|---|---|
| `APP_PASSWORD` | 必須 | ログイン画面で使用するパスワード |
| `SECRET_KEY` | 必須 | セッション署名用の秘密鍵（ランダムな長い文字列を推奨） |
| `HTTPS_ONLY` | 任意 | `false` にするとHTTPでも動作（ローカル開発用）。デフォルト: `true` |
| `PORT` | 任意 | リッスンポート。デフォルト: `8000` |

起動後、ブラウザで `http://localhost:8000` にアクセスしてください。

## 使い方

1. **ログイン** — パスワードを入力してログイン
2. **月を選択** — 画面上部で対象年月を選択（祝日・日曜日が自動で設定されます）
3. **Excelをアップロード** — 各タブで希望休・担当制限を記入したExcelファイルをアップロード
4. **当直表を生成** — 各タブの「当直表を作成」ボタン、または「全て作成」ボタンで一括生成
5. **ダウンロード** — 「ダウンロード」または「全てダウンロード（ZIP）」で取得

## API エンドポイント

| メソッド | パス | 説明 |
|---|---|---|
| `GET` | `/api/holidays` | 指定年月の祝日・日曜インデックスを取得 |
| `POST` | `/api/{shift_type}/upload` | Excelファイルをアップロード |
| `POST` | `/api/{shift_type}/generate` | 当直表を生成 |
| `POST` | `/api/{shift_type}/download` | 結果をExcelでダウンロード |
| `POST` | `/api/download-all` | 複数タイプをまとめてZIPダウンロード |

`shift_type` は `icu` / `junya` / `resident` のいずれか。

## 当直タイプの設定（configs.py）

各当直タイプの挙動は `ShiftConfig` で定義されています。新しい当直タイプを追加する場合は `SHIFT_CONFIGS` に設定を追加するだけで対応できます。

| 設定項目 | ICU | 準夜 | レジデント |
|---|---|---|---|
| 通常 min_gap | 中2日 | 中3日 | 中3日 |
| 緊急 min_gap | 中1日 | 中2日 | 中2日 |
| 日直未充足を警告 | あり | なし | なし |
| 緊急割当フラグ表示 | なし | あり | あり |

## 技術スタック

| レイヤー | 技術 |
|---|---|
| バックエンド | Python / FastAPI |
| ソルバー | Google OR-Tools（CP-SAT） |
| Excel | openpyxl |
| 祝日判定 | jpholiday |
| フロントエンド | Vanilla JS / HTML / CSS |
