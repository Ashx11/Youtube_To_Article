import re
from typing import Any


class TranscriptCleaner:
    """Converts transcript segments into lightly cleaned plain text."""

    _NOISE_PATTERN = re.compile(
        r"^\s*[\[(](music|applause|laughter)[\])]\s*$",
        re.IGNORECASE,
    )
    _WHITESPACE_PATTERN = re.compile(r"\s+")

    def clean(self, segments: list[dict[str, Any]]) -> str:
        """Join transcript segment text and remove obvious transcript noise."""
        cleaned_lines: list[str] = []
        previous_line = ""

        for segment in segments:
            text = self._normalize_text(segment.get("text", ""))
            if not text or self._is_noise(text):
                continue

            if text.casefold() == previous_line:
                continue

            cleaned_lines.append(text)
            previous_line = text.casefold()

        return " ".join(cleaned_lines)

    def _normalize_text(self, value: Any) -> str:
        text = self._WHITESPACE_PATTERN.sub(" ", str(value)).strip()
        return text

    def _is_noise(self, text: str) -> bool:
        return bool(self._NOISE_PATTERN.fullmatch(text))
