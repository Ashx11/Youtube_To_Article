from typing import Iterator

from .article_providers import (
    ArticleProvider,
    GeminiArticleProvider,
    OpenAIArticleProvider,
)


class ArticleGenerationError(Exception):
    """Raised when article generation fails."""


class ArticleGenerator:
    """Generates Markdown articles from cleaned transcript text."""

    _DEFAULT_PROVIDER = "openai"
    _DEFAULT_TONE = "editorial"
    _DEFAULT_TEMPERATURE = 0.6
    _MIN_TEMPERATURE = 0.2
    _MAX_TEMPERATURE = 1.0
    _DIRECT_SOURCE_LIMIT = 12000
    _CHUNK_SIZE = 7000
    _CHUNK_OVERLAP = 400
    _BOUNDARY_WINDOW = 500
    _SUMMARY_TEMPERATURE = 0.2
    _BASE_INSTRUCTIONS = (
        "You are an expert editor. Write a readable Markdown article grounded only "
        "in the provided source text. The article must start with exactly one '# ' "
        "title, include a short natural introduction, then 2 to 5 '##' section "
        "headings with clear paragraphs. For medium and long source material, aim "
        "for a fuller article of roughly 700 to 900 words, but keep the length "
        "proportional to the source and do not force that range for short material. "
        "Expand only where the source supports additional detail, explanation, or "
        "examples. Do not pad the article or add fluff. Preserve meaning and some "
        "of the speaker's voice. Adapt to the tone and rhythm of the original "
        "speaker where appropriate. Maintain a consistent tone throughout the "
        "entire article. Remove transcript-style repetition and filler. Do not "
        "invent facts, context, or examples. Do not mention the words 'transcript' "
        "or 'video'. Avoid generic AI-sounding phrasing. Avoid formulaic framing "
        "such as 'In conclusion', 'This article explores', or similar stock "
        "transitions."
    )
    _TONE_INSTRUCTIONS = {
        "editorial": (
            "Write in a polished, structured, slightly formal voice with the feel of "
            "a high-quality published article. Use smooth transitions, well-formed "
            "paragraphs, and confident phrasing. Keep the writing refined and avoid "
            "overly casual wording."
        ),
        "casual": (
            "Write in a conversational, engaging voice with simpler phrasing and "
            "shorter sentences. Aim for a natural explanation style with a bit more "
            "personality, while staying grounded in the source. Keep it warm and "
            "approachable without becoming sloppy or overly informal."
        ),
        "technical": (
            "Write in a precise, structured, analytical voice with exact wording and "
            "slightly denser explanations. Prioritize clarity and logical flow, use "
            "formal phrasing, keep the reasoning crisp, and avoid emotional or casual "
            "language."
        ),
    }

    def __init__(self) -> None:
        self._providers: dict[str, ArticleProvider] = {
            "openai": OpenAIArticleProvider(),
            "gemini": GeminiArticleProvider(),
        }

    def generate(
        self,
        video_id: str,
        cleaned_text: str,
        provider: str = _DEFAULT_PROVIDER,
        model: str | None = None,
        tone: str = _DEFAULT_TONE,
        temperature: float = _DEFAULT_TEMPERATURE,
    ) -> dict[str, str]:
        """Generate a title and Markdown article from cleaned transcript text."""
        source_text = cleaned_text

        try:
            self._validate_inputs(video_id=video_id, cleaned_text=cleaned_text)
            if self.requires_chunking(cleaned_text):
                source_text = self.build_combined_summary(
                    cleaned_text=cleaned_text,
                    provider=provider,
                )

            return self.generate_from_source_text(
                video_id=video_id,
                source_text=source_text,
                provider=provider,
                model=model,
                tone=tone,
                temperature=temperature,
            )
        except ArticleGenerationError:
            raise
        except ValueError:
            raise
        except Exception as exc:
            raise ArticleGenerationError(
                f"Failed to generate an article from the cleaned transcript: {exc}"
            ) from exc

    def stream(
        self,
        video_id: str,
        cleaned_text: str,
        provider: str = _DEFAULT_PROVIDER,
        model: str | None = None,
        tone: str = _DEFAULT_TONE,
        temperature: float = _DEFAULT_TEMPERATURE,
    ) -> Iterator[dict[str, str]]:
        """Stream article content and yield a final completed payload."""
        source_text = cleaned_text

        try:
            self._validate_inputs(video_id=video_id, cleaned_text=cleaned_text)
            if self.requires_chunking(cleaned_text):
                source_text = self.build_combined_summary(
                    cleaned_text=cleaned_text,
                    provider=provider,
                )

            yield from self.stream_from_source_text(
                video_id=video_id,
                source_text=source_text,
                provider=provider,
                model=model,
                tone=tone,
                temperature=temperature,
            )
        except ArticleGenerationError:
            raise
        except ValueError:
            raise
        except Exception as exc:
            raise ArticleGenerationError(
                f"Failed to generate an article from the cleaned transcript: {exc}"
            ) from exc

    def generate_from_source_text(
        self,
        video_id: str,
        source_text: str,
        provider: str = _DEFAULT_PROVIDER,
        model: str | None = None,
        tone: str = _DEFAULT_TONE,
        temperature: float = _DEFAULT_TEMPERATURE,
    ) -> dict[str, str]:
        """Generate an article from already prepared source text."""
        try:
            article_provider = self._get_provider(provider)
            request = self._build_request(
                video_id=video_id,
                source_text=source_text,
                model=model,
                tone=tone,
                temperature=temperature,
            )
            output_text = article_provider.generate(**request)
            return self._build_article_payload(output_text)
        except ValueError:
            raise
        except Exception as exc:
            raise ArticleGenerationError(
                f"Failed to generate an article from the cleaned transcript: {exc}"
            ) from exc

    def stream_from_source_text(
        self,
        video_id: str,
        source_text: str,
        provider: str = _DEFAULT_PROVIDER,
        model: str | None = None,
        tone: str = _DEFAULT_TONE,
        temperature: float = _DEFAULT_TEMPERATURE,
    ) -> Iterator[dict[str, str]]:
        """Stream article generation from already prepared source text."""
        try:
            article_provider = self._get_provider(provider)
            request = self._build_request(
                video_id=video_id,
                source_text=source_text,
                model=model,
                tone=tone,
                temperature=temperature,
            )
            markdown_chunks: list[str] = []

            for delta in article_provider.stream(**request):
                if delta:
                    markdown_chunks.append(delta)
                    yield {"type": "delta", "delta": delta}

            final_article = self._build_article_payload("".join(markdown_chunks))
            yield {
                "type": "completed",
                "title": final_article["title"],
                "markdown_content": final_article["markdown_content"],
            }
        except ValueError:
            raise
        except Exception as exc:
            raise ArticleGenerationError(
                f"Failed to generate an article from the cleaned transcript: {exc}"
            ) from exc

    def requires_chunking(self, cleaned_text: str) -> bool:
        """Return whether the cleaned transcript should be summarized before generation."""
        return self._requires_chunking(cleaned_text)

    def build_combined_summary(
        self,
        cleaned_text: str,
        provider: str = _DEFAULT_PROVIDER,
    ) -> str:
        """Build a reusable combined neutral summary for long transcripts."""
        if not cleaned_text or not cleaned_text.strip():
            raise ValueError("Cleaned transcript text is required.")

        article_provider = self._get_provider(provider)
        return self._prepare_source_text(
            provider=article_provider,
            cleaned_text=cleaned_text,
        )

    def _build_request(
        self,
        video_id: str,
        source_text: str,
        model: str | None,
        tone: str,
        temperature: float,
    ) -> dict[str, object]:
        normalized_tone = self._normalize_tone(tone)
        normalized_temperature = self._normalize_temperature(temperature)

        return {
            "instructions": self._build_instructions(normalized_tone),
            "input_text": f"Video ID: {video_id}\n\nSource text:\n{source_text}",
            "model": model,
            "temperature": normalized_temperature,
        }

    def _prepare_source_text(self, provider: ArticleProvider, cleaned_text: str) -> str:
        if not self._requires_chunking(cleaned_text):
            return cleaned_text

        chunk_summaries = self._summarize_chunks(provider=provider, cleaned_text=cleaned_text)
        combined_summary = self._combine_chunk_summaries(chunk_summaries)

        if not self._requires_chunking(combined_summary):
            return combined_summary

        return self._summarize_combined_summary(
            provider=provider,
            combined_summary=combined_summary,
        )

    def _requires_chunking(self, cleaned_text: str) -> bool:
        return len(cleaned_text) > self._DIRECT_SOURCE_LIMIT

    def _summarize_chunks(self, provider: ArticleProvider, cleaned_text: str) -> list[str]:
        chunks = self._split_into_chunks(cleaned_text)
        total_chunks = len(chunks)
        summaries: list[str] = []

        for index, chunk in enumerate(chunks, start=1):
            summaries.append(
                self._summarize_chunk(
                    provider=provider,
                    chunk_text=chunk,
                    chunk_index=index,
                    total_chunks=total_chunks,
                )
            )

        return summaries

    def _split_into_chunks(self, cleaned_text: str) -> list[str]:
        chunks: list[str] = []
        text_length = len(cleaned_text)
        start = 0

        while start < text_length:
            target_end = min(start + self._CHUNK_SIZE, text_length)
            end = self._find_chunk_end(cleaned_text, start, target_end)
            chunk = cleaned_text[start:end].strip()

            if chunk:
                chunks.append(chunk)

            if end >= text_length:
                break

            start = max(end - self._CHUNK_OVERLAP, start + 1)

        return chunks or [cleaned_text]

    def _find_chunk_end(self, cleaned_text: str, start: int, target_end: int) -> int:
        if target_end >= len(cleaned_text):
            return len(cleaned_text)

        search_end = min(len(cleaned_text), target_end + self._BOUNDARY_WINDOW)
        boundary_markers = ("\n\n", ". ", "! ", "? ", "\n")

        for marker in boundary_markers:
            boundary = cleaned_text.rfind(marker, start, search_end)
            if boundary > start:
                if marker == "\n\n":
                    return boundary + 2

                return boundary + 1

        return target_end

    def _summarize_chunk(
        self,
        provider: ArticleProvider,
        chunk_text: str,
        chunk_index: int,
        total_chunks: int,
    ) -> str:
        summary = provider.generate(
            instructions=(
                "Summarize this source chunk faithfully and neutrally. Preserve key "
                "ideas, important details, names, claims, and examples. Remove "
                "repetition and filler. Do not invent facts. Do not rewrite it in "
                "editorial, casual, or technical style. Return concise plain text."
            ),
            input_text=(
                f"Chunk {chunk_index} of {total_chunks}\n\n"
                f"Source text:\n{chunk_text}"
            ),
            temperature=self._SUMMARY_TEMPERATURE,
        ).strip()
        if not summary:
            raise ArticleGenerationError("Failed to summarize a transcript chunk.")

        return summary

    def _combine_chunk_summaries(self, chunk_summaries: list[str]) -> str:
        return "\n\n".join(
            f"Chunk summary {index}:\n{summary}"
            for index, summary in enumerate(chunk_summaries, start=1)
        )

    def _summarize_combined_summary(self, provider: ArticleProvider, combined_summary: str) -> str:
        summary = provider.generate(
            instructions=(
                "Consolidate these chunk summaries into one faithful neutral summary. "
                "Preserve the most important details, examples, and through-lines. "
                "Keep it concise, plain text, and do not invent facts."
            ),
            input_text=f"Chunk summaries:\n{combined_summary}",
            temperature=self._SUMMARY_TEMPERATURE,
        ).strip()
        if not summary:
            raise ArticleGenerationError("Failed to build a combined transcript summary.")

        return summary

    def _build_article_payload(self, output_text: str) -> dict[str, str]:
        markdown_content = self._normalize_markdown(output_text)
        title = self._extract_title(markdown_content)

        if not markdown_content or not title:
            raise ArticleGenerationError("The generated article response was incomplete.")

        return {"title": title, "markdown_content": markdown_content}

    def _build_instructions(self, tone: str) -> str:
        return f"{self._BASE_INSTRUCTIONS}\n\nTone:\n{self._TONE_INSTRUCTIONS[tone]}"

    def _get_provider(self, provider: str) -> ArticleProvider:
        normalized_provider = self._normalize_provider(provider)
        return self._providers[normalized_provider]

    def _normalize_provider(self, provider: str) -> str:
        normalized_provider = (provider or self._DEFAULT_PROVIDER).strip().casefold()
        return normalized_provider if normalized_provider in self._providers else self._DEFAULT_PROVIDER

    def _normalize_tone(self, tone: str) -> str:
        normalized_tone = (tone or self._DEFAULT_TONE).strip().casefold()
        return normalized_tone if normalized_tone in self._TONE_INSTRUCTIONS else self._DEFAULT_TONE

    def _normalize_temperature(self, temperature: float) -> float:
        try:
            numeric_temperature = float(temperature)
        except (TypeError, ValueError):
            return self._DEFAULT_TEMPERATURE

        if self._MIN_TEMPERATURE <= numeric_temperature <= self._MAX_TEMPERATURE:
            return numeric_temperature

        return self._DEFAULT_TEMPERATURE

    def _validate_inputs(self, video_id: str, cleaned_text: str) -> None:
        if not video_id or not video_id.strip():
            raise ValueError("Video ID is required.")

        if not cleaned_text or not cleaned_text.strip():
            raise ValueError("Cleaned transcript text is required.")

    def _normalize_markdown(self, content: str) -> str:
        markdown = content.strip()

        if markdown.startswith("```") and markdown.endswith("```"):
            lines = markdown.splitlines()
            markdown = "\n".join(lines[1:-1]).strip()

        return markdown

    def _extract_title(self, markdown_content: str) -> str:
        for line in markdown_content.splitlines():
            stripped_line = line.strip()
            if stripped_line.startswith("# "):
                return stripped_line[2:].strip()

        return ""
