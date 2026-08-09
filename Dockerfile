# ── Stage 1: フロントエンドビルド ─────────────────────────────
FROM node:22-slim AS frontend-builder

WORKDIR /app/frontend

# package-lock.json を使って再現性の高いインストール
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python バックエンド ──────────────────────────────
FROM python:3.13-slim AS runtime

# ffmpeg（音声変換・ブラウザ非対応形式の再生用トランスコード用）と
# tzdata（TZ 環境変数でコンテナをローカル時刻にするため）をインストール
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tzdata \
    && rm -rf /var/lib/apt/lists/*

# uv を公式イメージから導入
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 依存関係のみを先にインストールしてレイヤーキャッシュを活用する。
# --no-install-project: プロジェクト本体は後のステップでコピー後にインストール
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# アプリケーションコードをコピー
COPY gijiroku_ai/ ./gijiroku_ai/

# フロントエンドのビルド成果物をコピー
COPY --from=frontend-builder /app/frontend/dist /app/static

# 環境変数のデフォルト値
ENV DATA_DIR=/data \
    STATIC_DIR=/app/static

EXPOSE 8000

# .venv 内の uvicorn を直接呼び出す
CMD ["/app/.venv/bin/uvicorn", "gijiroku_ai.main:app", "--host", "0.0.0.0", "--port", "8000"]
