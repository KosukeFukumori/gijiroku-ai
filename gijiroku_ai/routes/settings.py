"""設定（Gemini モデル名・プロンプト）の取得・更新 API。"""

from fastapi import APIRouter

from gijiroku_ai import settings
from gijiroku_ai.config import get_config
from gijiroku_ai.models import SettingsResponse, SettingsUpdate

router = APIRouter(prefix="/api")


def _to_response() -> SettingsResponse:
    saved = settings.load_settings()
    model_default = get_config().gemini_model
    prompt_default = settings.DEFAULT_PROMPT
    return SettingsResponse(
        gemini_model=saved.get("gemini_model") or model_default,
        prompt=saved.get("prompt") or prompt_default,
        gemini_model_is_default="gemini_model" not in saved,
        prompt_is_default="prompt" not in saved,
        gemini_model_default=model_default,
        prompt_default=prompt_default,
    )


@router.get("/settings")
def get_settings() -> SettingsResponse:
    return _to_response()


@router.put("/settings")
def update_settings(body: SettingsUpdate) -> SettingsResponse:
    patch = body.model_dump(exclude_unset=True)
    settings.save_settings(patch)
    return _to_response()
