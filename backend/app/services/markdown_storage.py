import re
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]


class MarkdownStorage:
    """Saves generated articles as Markdown files."""

    _INVALID_FILENAME_CHARS = re.compile(r"[^a-z0-9]+")
    _SUPPORTED_PROVIDERS = {"openai", "gemini"}
    _SUPPORTED_TONES = {"editorial", "casual", "technical"}

    def __init__(self, output_dir: str | Path = BACKEND_DIR / "outputs") -> None:
        self._output_dir = Path(output_dir)

    def save(
        self,
        title: str,
        video_id: str,
        markdown_content: str,
        provider: str,
        tone: str,
    ) -> str:
        """Save Markdown content to disk and return the file path."""
        self._output_dir.mkdir(parents=True, exist_ok=True)

        filename_stem = self._build_filename_stem(
            title=title,
            video_id=video_id,
            provider=provider,
            tone=tone,
        )
        file_path = self._output_dir / f"{filename_stem}.md"
        file_path.write_text(markdown_content, encoding="utf-8")

        return str(file_path)

    def _build_filename_stem(self, title: str, video_id: str, provider: str, tone: str) -> str:
        base_name = title.strip() or video_id.strip()
        slug = self._INVALID_FILENAME_CHARS.sub("-", base_name.casefold()).strip("-")
        normalized_provider = self._normalize_provider(provider)
        normalized_tone = self._normalize_tone(tone)
        fallback_slug = self._INVALID_FILENAME_CHARS.sub("-", video_id.strip().casefold()).strip("-")
        return f"{slug or fallback_slug}_{normalized_provider}_{normalized_tone}"

    def _normalize_provider(self, provider: str) -> str:
        normalized_provider = (provider or "openai").strip().casefold()
        return normalized_provider if normalized_provider in self._SUPPORTED_PROVIDERS else "openai"

    def _normalize_tone(self, tone: str) -> str:
        normalized_tone = (tone or "editorial").strip().casefold()
        return normalized_tone if normalized_tone in self._SUPPORTED_TONES else "editorial"
