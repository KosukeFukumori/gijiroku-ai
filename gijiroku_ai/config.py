"""環境変数ベースの設定（インフラ系）。

ホスト上で直接起動するため（Docker の env_file による注入は無い）、
`.env` ファイルをこの設定クラスが直接読み込む。
"""

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Vertex AI / GCS 接続情報（文字起こし・話者識別・議事録生成に使う）
    gcp_project: str = ""
    gcp_location: str = "global"
    # サービスアカウント鍵 JSON のパス。google-genai は
    # GOOGLE_APPLICATION_CREDENTIALS 環境変数を直接参照するため、
    # 起動時にこの値をプロセス環境変数へ反映する（get_config 参照）
    google_application_credentials: Path = Path("")

    # 議事録生成に使う Gemini モデル（文字起こし・話者識別はローカルで行う）
    gemini_model: str = "gemini-2.5-flash"

    # ローカル文字起こし（mlx-whisper）で使うモデル。Apple Silicon 向けの
    # MLX 変換済みリポジトリを指定する。日本語議事録なら large-v3 が高精度。
    whisper_model: str = "mlx-community/whisper-large-v3-mlx"

    # 文字起こしの言語（None/空 なら自動判定）。日本語会議は "ja" を推奨。
    whisper_language: str = "ja"

    # pyannote 話者ダイアライゼーション用の HuggingFace アクセストークン。
    # 未設定の場合は話者識別をスキップし文字起こしのみ行う（speaker=None）。
    # pyannote/speaker-diarization-3.1 はゲートモデルのため、トークン取得に
    # 加えて HuggingFace 上での規約同意が必要。
    hf_token: str = ""

    # データ永続化ディレクトリ（録音ファイル・一時ファイル置き場）
    data_dir: Path = Path("data")

    # フロントエンドのビルド成果物ディレクトリ。ホスト実行では
    # `npm run build` の出力先（frontend/dist）をそのまま配信する
    static_dir: Path = Path("frontend/dist")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "gijiroku_ai.db"

    @property
    def recordings_dir(self) -> Path:
        return self.data_dir / "recordings"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"


@lru_cache
def get_config() -> Config:
    config = Config()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.recordings_dir.mkdir(parents=True, exist_ok=True)
    config.tmp_dir.mkdir(parents=True, exist_ok=True)
    # google-genai は GOOGLE_APPLICATION_CREDENTIALS 環境変数を直接参照する
    # ため、.env 由来の値をプロセス環境変数へ反映する（Docker の env_file が
    # 担っていた役割をホスト実行で肩代わりする）。
    cred = str(config.google_application_credentials)
    if cred and cred != ".":
        os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", cred)
    return config
