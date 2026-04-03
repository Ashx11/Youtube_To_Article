from __future__ import annotations

import os
from typing import Iterator, Protocol

from openai import OpenAI

try:
    from google import genai
    from google.genai import types as gemini_types
except ImportError:  # pragma: no cover - optional dependency fallback
    genai = None
    gemini_types = None


class ArticleProvider(Protocol):
    """Minimal interface for provider-specific text generation."""

    def generate(
        self,
        instructions: str,
        input_text: str,
        temperature: float,
        model: str | None = None,
    ) -> str:
        """Generate the full text response."""

    def stream(
        self,
        instructions: str,
        input_text: str,
        temperature: float,
        model: str | None = None,
    ) -> Iterator[str]:
        """Yield incremental text deltas when supported."""


class OpenAIArticleProvider:
    """OpenAI-backed article generation provider."""

    _DEFAULT_MODEL = "gpt-5.4"

    def generate(
        self,
        instructions: str,
        input_text: str,
        temperature: float,
        model: str | None = None,
    ) -> str:
        response = self._get_client().responses.create(
            model=self._get_model(model),
            instructions=instructions,
            input=input_text,
            temperature=temperature,
        )
        return getattr(response, "output_text", "").strip()

    def stream(
        self,
        instructions: str,
        input_text: str,
        temperature: float,
        model: str | None = None,
    ) -> Iterator[str]:
        with self._get_client().responses.stream(
            model=self._get_model(model),
            instructions=instructions,
            input=input_text,
            temperature=temperature,
        ) as stream:
            for event in stream:
                if event.type == "response.output_text.delta" and event.delta:
                    yield event.delta

    def _get_client(self) -> OpenAI:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")

        return OpenAI(api_key=api_key)

    def _get_model(self, model: str | None = None) -> str:
        if model and model.strip():
            return model.strip()

        return os.getenv("OPENAI_MODEL", self._DEFAULT_MODEL).strip() or self._DEFAULT_MODEL


class GeminiArticleProvider:
    """Gemini-backed article generation provider."""

    _DEFAULT_MODEL = "gemini-3.1-pro-preview"

    def generate(
        self,
        instructions: str,
        input_text: str,
        temperature: float,
        model: str | None = None,
    ) -> str:
        client = self._get_client()
        response = client.models.generate_content(
            model=self._get_model(model),
            contents=input_text,
            config=self._build_config(instructions=instructions, temperature=temperature),
        )
        return getattr(response, "text", "").strip()

    def stream(
        self,
        instructions: str,
        input_text: str,
        temperature: float,
        model: str | None = None,
    ) -> Iterator[str]:
        client = self._get_client()
        response = client.models.generate_content_stream(
            model=self._get_model(model),
            contents=input_text,
            config=self._build_config(instructions=instructions, temperature=temperature),
        )

        for chunk in response:
            if getattr(chunk, "text", ""):
                yield chunk.text

    def _get_client(self) -> genai.Client:
        if genai is None:
            raise RuntimeError("google-genai is not installed.")

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured.")

        return genai.Client(api_key=api_key)

    def _get_model(self, model: str | None = None) -> str:
        if model and model.strip():
            return model.strip()

        return os.getenv("GEMINI_MODEL", self._DEFAULT_MODEL).strip() or self._DEFAULT_MODEL

    def _build_config(
        self,
        instructions: str,
        temperature: float,
    ) -> gemini_types.GenerateContentConfig:
        if gemini_types is None:
            raise RuntimeError("google-genai is not installed.")

        return gemini_types.GenerateContentConfig(
            system_instruction=instructions,
            temperature=temperature,
        )
