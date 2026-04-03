from pathlib import Path

import pytest

from app.services.markdown_storage import MarkdownStorage
from app.services.persistence import PersistenceService
from app.services.youtube_url_parser import YouTubeUrlParser


def create_persistence(tmp_path: Path) -> PersistenceService:
    return PersistenceService(db_path=tmp_path / "test.db")


def test_extract_video_id_from_watch_url() -> None:
    parser = YouTubeUrlParser()

    assert parser.extract_video_id("https://www.youtube.com/watch?v=abc123XYZ") == "abc123XYZ"


def test_extract_video_id_from_short_url() -> None:
    parser = YouTubeUrlParser()

    assert parser.extract_video_id("https://youtu.be/abc123XYZ") == "abc123XYZ"


def test_extract_video_id_rejects_invalid_url() -> None:
    parser = YouTubeUrlParser()

    with pytest.raises(ValueError, match="Unsupported YouTube URL format."):
        parser.extract_video_id("https://example.com/watch?v=abc123XYZ")


def test_normalize_temperature_keeps_valid_values(tmp_path: Path) -> None:
    persistence = create_persistence(tmp_path)

    assert persistence.normalize_temperature(0.6) == 0.6
    assert persistence.normalize_temperature("0.8") == 0.8


def test_normalize_temperature_falls_back_for_invalid_values(tmp_path: Path) -> None:
    persistence = create_persistence(tmp_path)

    assert persistence.normalize_temperature("bad") == 0.6
    assert persistence.normalize_temperature(1.7) == 0.6
    assert persistence.normalize_temperature(0.1) == 0.6


def test_normalize_temperature_is_stable_for_cache_lookup(tmp_path: Path) -> None:
    persistence = create_persistence(tmp_path)

    assert persistence.normalize_temperature(0.64) == 0.6
    assert persistence.normalize_temperature(0.65) == 0.7


def test_markdown_storage_filename_includes_provider_and_tone(tmp_path: Path) -> None:
    storage = MarkdownStorage(output_dir=tmp_path)

    saved_path = storage.save(
        title="A Better Future for AI",
        video_id="abc123XYZ",
        markdown_content="# A Better Future for AI\n\nContent",
        provider="gemini",
        tone="technical",
    )

    saved_name = Path(saved_path).name
    assert saved_name.endswith(".md")
    assert saved_name == "a-better-future-for-ai_gemini_technical.md"


def test_transcript_summary_can_be_saved_and_reused(tmp_path: Path) -> None:
    persistence = create_persistence(tmp_path)
    persistence.ensure_video(
        video_id="abc123XYZ",
        youtube_url="https://www.youtube.com/watch?v=abc123XYZ",
    )
    persistence.save_transcript_summary(
        video_id="abc123XYZ",
        provider="gemini",
        summary_text="Combined neutral summary",
        source_length=24000,
    )

    summary = persistence.get_transcript_summary("abc123XYZ", "gemini")
    assert summary is not None
    assert summary["provider"] == "gemini"
    assert summary["summary_text"] == "Combined neutral summary"
    assert summary["source_length"] == 24000


def test_saving_transcript_invalidates_persisted_summary(tmp_path: Path) -> None:
    persistence = create_persistence(tmp_path)
    persistence.save_transcript(
        video_id="abc123XYZ",
        youtube_url="https://www.youtube.com/watch?v=abc123XYZ",
        language="en",
        segment_count=10,
        cleaned_text="Original cleaned text",
    )
    persistence.save_transcript_summary(
        video_id="abc123XYZ",
        provider="gemini",
        summary_text="Combined neutral summary",
        source_length=24000,
    )

    persistence.save_transcript(
        video_id="abc123XYZ",
        youtube_url="https://www.youtube.com/watch?v=abc123XYZ",
        language="en",
        segment_count=12,
        cleaned_text="Updated cleaned text",
    )

    assert persistence.get_transcript_summary("abc123XYZ", "gemini") is None


def test_transcript_summary_lookup_distinguishes_provider(tmp_path: Path) -> None:
    persistence = create_persistence(tmp_path)
    persistence.ensure_video(
        video_id="abc123XYZ",
        youtube_url="https://www.youtube.com/watch?v=abc123XYZ",
    )
    persistence.save_transcript_summary(
        video_id="abc123XYZ",
        provider="openai",
        summary_text="OpenAI combined summary",
        source_length=24000,
    )
    persistence.save_transcript_summary(
        video_id="abc123XYZ",
        provider="gemini",
        summary_text="Gemini combined summary",
        source_length=24000,
    )

    openai_summary = persistence.get_transcript_summary("abc123XYZ", "openai")
    gemini_summary = persistence.get_transcript_summary("abc123XYZ", "gemini")

    assert openai_summary is not None
    assert gemini_summary is not None
    assert openai_summary["summary_text"] == "OpenAI combined summary"
    assert gemini_summary["summary_text"] == "Gemini combined summary"


def test_article_lookup_distinguishes_provider_tone_and_temperature(tmp_path: Path) -> None:
    persistence = create_persistence(tmp_path)
    persistence.save_article(
        video_id="abc123XYZ",
        youtube_url="https://www.youtube.com/watch?v=abc123XYZ",
        provider="openai",
        model="gpt-5.4",
        tone="editorial",
        temperature=0.6,
        title="First",
        markdown_content="# First\n\nBody",
        markdown_path="outputs/first_openai_editorial.md",
    )

    assert persistence.get_article("abc123XYZ", "openai", "gpt-5.4", "editorial", 0.6) is not None
    assert persistence.get_article(
        "abc123XYZ",
        "gemini",
        "gemini-3.1-pro-preview",
        "editorial",
        0.6,
    ) is None
    assert persistence.get_article("abc123XYZ", "openai", "gpt-5.4-mini", "editorial", 0.6) is None
    assert persistence.get_article("abc123XYZ", "openai", "gpt-5.4", "casual", 0.6) is None
    assert persistence.get_article("abc123XYZ", "openai", "gpt-5.4", "editorial", 0.7) is None
