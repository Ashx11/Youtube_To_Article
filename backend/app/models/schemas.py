from pydantic import BaseModel, field_validator, model_validator

DEFAULT_PROVIDER = "openai"
DEFAULT_TONE = "editorial"
DEFAULT_TEMPERATURE = 0.6
SUPPORTED_MODELS = {
    "openai": {"gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano"},
    "gemini": {
        "gemini-3.1-pro-preview",
        "gemini-3-flash-preview",
        "gemini-3.1-flash-lite-preview",
    },
}
DEFAULT_MODELS = {
    "openai": "gpt-5.4",
    "gemini": "gemini-3.1-pro-preview",
}


class TranscriptFetchRequest(BaseModel):
    youtube_url: str


class TranscriptFetchResponse(BaseModel):
    video_id: str
    language: str
    segment_count: int
    cleaned_text: str
    cleaned_preview: str | None = None
    cached: bool


class ArticleGenerationRequest(BaseModel):
    youtube_url: str
    provider: str = DEFAULT_PROVIDER
    model: str | None = None
    tone: str = DEFAULT_TONE
    temperature: float = DEFAULT_TEMPERATURE

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: object) -> str:
        normalized_value = str(value or DEFAULT_PROVIDER).strip().casefold()
        return normalized_value if normalized_value in SUPPORTED_MODELS else DEFAULT_PROVIDER

    @model_validator(mode="after")
    def normalize_model(self) -> "ArticleGenerationRequest":
        normalized_model = str(self.model or "").strip().casefold()
        supported_models = SUPPORTED_MODELS[self.provider]
        self.model = (
            normalized_model
            if normalized_model in supported_models
            else DEFAULT_MODELS[self.provider]
        )
        return self

    @field_validator("tone", mode="before")
    @classmethod
    def normalize_tone(cls, value: object) -> str:
        normalized_value = str(value or DEFAULT_TONE).strip().casefold()
        return (
            normalized_value
            if normalized_value in {"editorial", "casual", "technical"}
            else DEFAULT_TONE
        )

    @field_validator("temperature", mode="before")
    @classmethod
    def normalize_temperature(cls, value: object) -> float:
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return DEFAULT_TEMPERATURE

        if 0.2 <= numeric_value <= 1.0:
            return numeric_value

        return DEFAULT_TEMPERATURE


class ArticleGenerationResponse(BaseModel):
    video_id: str
    title: str
    markdown_content: str
    markdown_path: str
    cached: bool
