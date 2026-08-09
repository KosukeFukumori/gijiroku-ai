"""環境変数ベースの設定（インフラ系）。"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Config(BaseSettings):
    # Vertex AI / GCS 接続情報（文字起こし・話者識別・議事録生成に使う）
    gcp_project: str = ""
    gcp_location: str = "global"
    gcs_bucket: str = ""
    # サービスアカウント鍵 JSON のコンテナ内パス。google-genai / google-cloud
    # -storage は GOOGLE_APPLICATION_CREDENTIALS 環境変数を直接参照するため、
    # 起動時にこの値をプロセス環境変数へ反映する（gijiroku_ai/gemini.py 参照）
    google_application_credentials: Path = Path("")

    # 文字起こし・話者識別・議事録生成に使う Gemini モデル
    gemini_model: str = "gemini-2.5-flash"

    # データ永続化ディレクトリ（録音ファイル・一時ファイル置き場）
    data_dir: Path = Path("data")

    # SQLite ファイルの置き場所。未設定時は data_dir 配下を使う。
    # Docker Desktop for Mac のバインドマウント上では WAL モードの
    # 共有メモリファイルのロックが不安定なため、本番では data_dir とは別の
    # Docker named volume を指定する（docker-compose.yml 参照）
    db_dir: Path | None = None

    # フロントエンドのビルド成果物ディレクトリ
    static_dir: Path = Path("static")

    @property
    def db_path(self) -> Path:
        return (self.db_dir or self.data_dir) / "gijiroku_ai.db"

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
    if config.db_dir is not None:
        config.db_dir.mkdir(parents=True, exist_ok=True)
    return config
