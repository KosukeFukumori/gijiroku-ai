# 議事録AI

会議などの録音ファイルを追加すると、自動で文字起こし・議事録（要約・決定事項・
アクションアイテム）を生成するローカル Web アプリです。

文字起こしと話者識別は **macOS ホスト上でローカルに実行**（Apple Silicon の
Metal / MLX を利用）し、確定したトランスクリプトだけを Gemini に渡して議事録化
する二段構成です。長時間会議の音声をクラウド API に丸ごと渡さないため、安定して
処理できます。

## 概要

- **手動アップロード**: 会議の録音ファイルをドラッグ&ドロップ、またはファイル選択で
  追加すると、その場で処理を開始します（NAS 監視などは行いません）
- **ローカル文字起こし**: mlx-whisper（large-v3）で Apple Silicon の GPU を使って
  文字起こしします。音声はローカルから外部へ送信されません
- **話者識別**: pyannote.audio 3.1（Metal / MPS）で「誰が話したか」を推定し、
  出現順に「話者A」「話者B」…のラベルを割り当てます
- **議事録生成**: 話者ラベル付きトランスクリプトを Vertex AI (Gemini) に渡し、
  要約・決定事項・アクションアイテムを生成します
- **逐次表示**: 文字起こしは確定した区間から順に画面へ流れます（処理段階の表示付き）。
  この途中経過は表示専用で、全区間の確定後に話者ラベル付きで保存し直します
- **処理の中断**: 処理待ち・処理中の録音は「中断」ボタンで打ち切れます。文字起こしは
  別プロセスで動かしているため、実行中でも即座に停止できます（中断後は「再試行」で
  最初からやり直せます）
- **詳細画面**: 録音ごとに「文字起こし」「議事録」のタブを切り替えて閲覧できます
- **完全削除**: アプリ上で削除すると、音源ファイル・文字起こし・議事録を
  すべて削除します
- **表示テーマ**: 画面右上のボタンでダーク / ライトを切り替えられます（初回は
  OS の設定に従い、選択内容はブラウザに保存されます）

## 必要要件

- **Apple Silicon の Mac（macOS）** … ローカル文字起こし・話者識別が Metal を使うため
- [uv](https://docs.astral.sh/uv/)（Python 環境・依存管理）
- Node.js 22+（フロントエンドのビルド用）
- ffmpeg（音声変換用。`brew install ffmpeg`）
- Vertex AI (Gemini) を利用できる GCP プロジェクト（議事録生成用）
- HuggingFace アカウントとアクセストークン（話者識別用。任意）

> ⚠️ Docker Desktop for Mac は Linux VM 上で動作しホストの Metal GPU に
> アクセスできないため、GPU を使うローカル文字起こしは **ホスト上で直接
> 実行**します（コンテナ運用はしません）。

## セットアップ手順

### 1. Vertex AI の準備

```bash
gcloud config set project <GCP プロジェクト ID>
```

サービスアカウントを発行し（Vertex AI User ロール）、鍵 JSON を
`gcp/service-account.json` に配置してください。

### 2. 話者識別（pyannote）の準備 ※任意

「誰が話したか」を識別したい場合は、以下2つのモデルページで規約に同意し、
アクセストークンを取得してください（同意しないとダウンロードできません）。

- <https://huggingface.co/pyannote/speaker-diarization-3.1> → Agree
- <https://huggingface.co/pyannote/segmentation-3.0> → Agree
- <https://huggingface.co/settings/tokens> で Read トークンを発行

取得したトークンを `.env` の `HF_TOKEN` に設定します。未設定の場合は
話者識別をスキップし、文字起こしのみ行います。

### 3. 環境変数ファイルの作成

```bash
cp .env.example .env
```

`.env` を開き、`GCP_PROJECT` や `HF_TOKEN` などを設定してください。

### 4. 依存関係のインストール

```bash
# バックエンド（Python）
uv sync

# フロントエンドのビルド
cd frontend && npm install && npm run build && cd ..
```

### 5. 起動

```bash
uv run uvicorn gijiroku_ai.main:app --host 0.0.0.0 --port 8000
```

起動ポートは `.env` ではなく、上記コマンドの `--port` オプションで指定します。
変更したい場合は `--port` の値を書き換えてください。

初回の文字起こし時に mlx-whisper / pyannote のモデル（数 GB）が
自動でダウンロードされます。

### 6. ブラウザでアクセス

```text
http://localhost:8000
```

## 環境変数一覧

<!-- markdownlint-disable MD013 -->

| 変数名 | 説明 | 既定値 |
| --- | --- | --- |
| `WHISPER_MODEL` | ローカル文字起こしの mlx-whisper モデル | `mlx-community/whisper-large-v3-mlx` |
| `WHISPER_LANGUAGE` | 文字起こしの言語（空で自動判定） | `ja` |
| `HF_TOKEN` | 話者識別用 HuggingFace トークン（空で話者識別スキップ） | （空） |
| `GCP_PROJECT` | Vertex AI の GCP プロジェクト ID | （必須） |
| `GCP_LOCATION` | Vertex AI のリージョン | `global` |
| `GEMINI_MODEL` | 議事録生成に使う Gemini モデル | `gemini-2.5-flash` |
| `GOOGLE_APPLICATION_CREDENTIALS` | サービスアカウント鍵 JSON のパス | `./gcp/service-account.json` |
| `STATIC_DIR` | フロントエンドのビルド成果物ディレクトリ | `frontend/dist` |
| `TZ` | タイムゾーン | `Asia/Tokyo` |

<!-- markdownlint-enable MD013 -->

## 開発時の起動方法

### バックエンド

```bash
uv sync
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
