# 議事録AI

会議などの録音ファイルを追加すると、自動で文字起こし・議事録（要約・決定事項・
アクションアイテム）を生成するローカル Web アプリです。

## 概要

- **手動アップロード**: 会議の録音ファイルをドラッグ&ドロップ、またはファイル選択で
  追加すると、その場で処理を開始します（NAS 監視などは行いません）
- **文字起こし・話者識別・議事録生成**: Vertex AI (Gemini) に音声を直接渡し、
  文字起こし・話者識別・要約・決定事項・アクションアイテムの生成までを
  1 回の呼び出しでまとめて行います
- **話者識別**: 発話内容から個人名を特定できる場合はその名前を、特定できない
  場合は「話者A」「話者B」…の匿名ラベルを割り当てます
- **詳細画面**: 録音ごとに「文字起こし」「議事録」のタブを切り替えて閲覧できます
- **完全削除**: アプリ上で削除すると、音源ファイル・文字起こし・議事録を
  すべて削除します

## 必要要件

- Docker（Docker Compose V2）
- Vertex AI (Gemini) を利用できる GCP プロジェクト

## セットアップ手順

### 1. Vertex AI の準備

```bash
gcloud config set project <GCP プロジェクト ID>
gsutil mb -l asia-northeast1 gs://<議事録AI 用バケット名>
```

サービスアカウントを発行し（Vertex AI User + 対象バケットの Storage
Object Admin ロール）、鍵 JSON を `gcp/service-account.json` に配置してください。

### 2. 環境変数ファイルの作成

```bash
cp .env.example .env
```

`.env` を開き、`GCP_PROJECT` / `GCS_BUCKET` などを設定してください。

### 3. コンテナの起動

```bash
docker compose up -d --build
```

### 4. ブラウザでアクセス

```text
http://localhost:8000
```

## 環境変数一覧

| 変数名 | 説明 | 既定値 |
| --- | --- | --- |
| `GCP_PROJECT` | Vertex AI の GCP プロジェクト ID | （必須） |
| `GCP_LOCATION` | Vertex AI のリージョン | `global` |
| `GCS_BUCKET` | 音声アップロード用 GCS バケット名 | （必須） |
| `GEMINI_MODEL` | 文字起こし・話者識別・議事録生成に使う Gemini モデル | `gemini-2.5-flash` |
| `GOOGLE_APPLICATION_CREDENTIALS` | サービスアカウント鍵 JSON のコンテナ内パス | `/secrets/service-account.json` |
| `PORT` | 公開ポート | `8000` |
| `TZ` | コンテナのタイムゾーン | `Asia/Tokyo` |

## 開発時の起動方法

### バックエンド

```bash
# 依存関係のインストール
uv sync

# 開発サーバーの起動（ホットリロード有効）
uv run uvicorn gijiroku_ai.main:app --reload
```

### フロントエンド

```bash
cd frontend
npm install
npm run dev
```

フロントエンドの開発サーバーは既定で `http://localhost:5173` で起動します
（`/api` へのリクエストは `vite.config.ts` の proxy 設定でバックエンド
（`http://localhost:8000`）に転送されます）。
