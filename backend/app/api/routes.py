import logging
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..models.schemas import (
    ArticleGenerationRequest,
    ArticleGenerationResponse,
    TranscriptFetchRequest,
    TranscriptFetchResponse,
)
from ..services.article_generator import ArticleGenerationError, ArticleGenerator
from ..services.markdown_storage import MarkdownStorage
from ..services.persistence import PersistenceService
from ..services.transcript_cleaner import TranscriptCleaner
from ..services.transcript_service import TranscriptService, TranscriptServiceError
from ..services.youtube_url_parser import YouTubeUrlParser

router = APIRouter()
logger = logging.getLogger(__name__)
article_generator = ArticleGenerator()
markdown_storage = MarkdownStorage()
persistence_service = PersistenceService()
youtube_url_parser = YouTubeUrlParser()
transcript_cleaner = TranscriptCleaner()
transcript_service = TranscriptService()


@router.get("/", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/debug/videos", tags=["debug"])
def list_debug_videos() -> list[dict[str, Any]]:
    """Return the most recent persisted video rows."""
    return persistence_service.list_recent_videos(limit=10)


@router.get("/api/debug/transcripts", tags=["debug"])
def list_debug_transcripts() -> list[dict[str, Any]]:
    """Return the most recent persisted transcript rows."""
    return persistence_service.list_recent_transcripts(limit=10)


@router.get("/api/debug/articles", tags=["debug"])
def list_debug_articles() -> list[dict[str, Any]]:
    """Return the most recent persisted article rows."""
    return persistence_service.list_recent_articles(limit=10)


def prepare_transcript(youtube_url: str) -> dict[str, Any]:
    """Parse the URL, fetch the transcript, and clean its text."""
    video_id = youtube_url_parser.extract_video_id(youtube_url)
    persistence_service.ensure_video(video_id=video_id, youtube_url=youtube_url)
    cached_transcript = persistence_service.get_transcript(video_id)

    if cached_transcript:
        return {
            "video_id": video_id,
            "transcript": {
                "video_id": video_id,
                "language": cached_transcript["language"],
                "segment_count": cached_transcript["segment_count"],
            },
            "cleaned_text": cached_transcript["cleaned_text"],
            "cached": True,
        }

    transcript = transcript_service.fetch(video_id)
    cleaned_text = transcript_cleaner.clean(transcript["segments"])
    persistence_service.save_transcript(
        video_id=video_id,
        youtube_url=youtube_url,
        language=transcript["language"],
        segment_count=transcript["segment_count"],
        cleaned_text=cleaned_text,
    )

    return {
        "video_id": video_id,
        "transcript": transcript,
        "cleaned_text": cleaned_text,
        "cached": False,
    }


def prepare_article_source_text(
    video_id: str,
    cleaned_text: str,
    provider: str,
) -> str:
    """Reuse or build a provider-specific combined summary source for long transcripts."""
    if not article_generator.requires_chunking(cleaned_text):
        return cleaned_text

    cached_summary = persistence_service.get_transcript_summary(video_id, provider)
    if cached_summary:
        return cached_summary["summary_text"]

    summary_text = article_generator.build_combined_summary(
        cleaned_text=cleaned_text,
        provider=provider,
    )
    persistence_service.save_transcript_summary(
        video_id=video_id,
        provider=provider,
        summary_text=summary_text,
        source_length=len(cleaned_text),
    )
    return summary_text


def format_markdown_path(markdown_path: str) -> str:
    normalized_path = markdown_path.replace("\\", "/")
    outputs_index = normalized_path.rfind("outputs/")

    if outputs_index >= 0:
        return normalized_path[outputs_index:]

    return normalized_path


def sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post(
    "/api/transcripts/fetch",
    response_model=TranscriptFetchResponse,
    tags=["transcripts"],
)
def fetch_transcript(
    request: TranscriptFetchRequest,
) -> TranscriptFetchResponse:
    """Parse a YouTube URL and return basic transcript details."""
    try:
        prepared_transcript = prepare_transcript(request.youtube_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TranscriptServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    transcript = prepared_transcript["transcript"]
    cleaned_text = prepared_transcript["cleaned_text"]
    cleaned_preview = cleaned_text[:200] or None

    return TranscriptFetchResponse(
        video_id=transcript["video_id"],
        language=transcript["language"],
        segment_count=transcript["segment_count"],
        cleaned_text=cleaned_text,
        cleaned_preview=cleaned_preview,
        cached=prepared_transcript["cached"],
    )


@router.post(
    "/api/articles/generate",
    response_model=ArticleGenerationResponse,
    tags=["articles"],
)
def generate_article(
    request: ArticleGenerationRequest,
) -> ArticleGenerationResponse:
    """Generate a Markdown article from a YouTube transcript."""
    try:
        prepared_transcript = prepare_transcript(request.youtube_url)
        normalized_temperature = persistence_service.normalize_temperature(request.temperature)
        cached_article = persistence_service.get_article(
            video_id=prepared_transcript["video_id"],
            provider=request.provider,
            model=request.model,
            tone=request.tone,
            temperature=normalized_temperature,
        )

        if cached_article:
            return ArticleGenerationResponse(
                video_id=prepared_transcript["video_id"],
                title=cached_article["title"],
                markdown_content=cached_article["markdown_content"],
                markdown_path=cached_article["markdown_path"],
                cached=True,
            )

        source_text = prepare_article_source_text(
            video_id=prepared_transcript["video_id"],
            cleaned_text=prepared_transcript["cleaned_text"],
            provider=request.provider,
        )
        article = article_generator.generate_from_source_text(
            video_id=prepared_transcript["video_id"],
            source_text=source_text,
            provider=request.provider,
            model=request.model,
            tone=request.tone,
            temperature=normalized_temperature,
        )
        markdown_path = markdown_storage.save(
            title=article["title"],
            video_id=prepared_transcript["video_id"],
            markdown_content=article["markdown_content"],
            provider=request.provider,
            tone=request.tone,
        )
        formatted_markdown_path = format_markdown_path(markdown_path)
        persistence_service.save_article(
            video_id=prepared_transcript["video_id"],
            youtube_url=request.youtube_url,
            provider=request.provider,
            model=request.model,
            tone=request.tone,
            temperature=normalized_temperature,
            title=article["title"],
            markdown_content=article["markdown_content"],
            markdown_path=formatted_markdown_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TranscriptServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except ArticleGenerationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ArticleGenerationResponse(
        video_id=prepared_transcript["video_id"],
        title=article["title"],
        markdown_content=article["markdown_content"],
        markdown_path=formatted_markdown_path,
        cached=False,
    )


@router.post("/api/articles/generate/stream", tags=["articles"])
def generate_article_stream(request: ArticleGenerationRequest) -> StreamingResponse:
    """Stream Markdown article generation progress over SSE."""
    try:
        prepared_transcript = prepare_transcript(request.youtube_url)
        normalized_temperature = persistence_service.normalize_temperature(request.temperature)
        cached_article = persistence_service.get_article(
            video_id=prepared_transcript["video_id"],
            provider=request.provider,
            model=request.model,
            tone=request.tone,
            temperature=normalized_temperature,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TranscriptServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except ArticleGenerationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    transcript = prepared_transcript["transcript"]

    def event_stream() -> Any:
        yield sse_event(
            "transcript",
            {
                "video_id": transcript["video_id"],
                "language": transcript["language"],
                "segment_count": transcript["segment_count"],
                "cleaned_text": prepared_transcript["cleaned_text"],
                "status": "Transcript ready",
                "cached": prepared_transcript["cached"],
            },
        )

        if cached_article:
            yield sse_event(
                "done",
                {
                    "video_id": prepared_transcript["video_id"],
                    "title": cached_article["title"],
                    "markdown_content": cached_article["markdown_content"],
                    "markdown_path": cached_article["markdown_path"],
                    "status": "Article ready",
                    "saved": True,
                    "cached": True,
                },
            )
            return

        try:
            source_text = prepare_article_source_text(
                video_id=prepared_transcript["video_id"],
                cleaned_text=prepared_transcript["cleaned_text"],
                provider=request.provider,
            )
            for event in article_generator.stream_from_source_text(
                video_id=prepared_transcript["video_id"],
                source_text=source_text,
                provider=request.provider,
                model=request.model,
                tone=request.tone,
                temperature=normalized_temperature,
            ):
                if event["type"] == "delta":
                    yield sse_event("chunk", {"delta": event["delta"]})
                    continue

                markdown_path = markdown_storage.save(
                    title=event["title"],
                    video_id=prepared_transcript["video_id"],
                    markdown_content=event["markdown_content"],
                    provider=request.provider,
                    tone=request.tone,
                )
                formatted_markdown_path = format_markdown_path(markdown_path)
                persistence_service.save_article(
                    video_id=prepared_transcript["video_id"],
                    youtube_url=request.youtube_url,
                    provider=request.provider,
                    model=request.model,
                    tone=request.tone,
                    temperature=normalized_temperature,
                    title=event["title"],
                    markdown_content=event["markdown_content"],
                    markdown_path=formatted_markdown_path,
                )
                yield sse_event(
                    "done",
                    {
                        "video_id": prepared_transcript["video_id"],
                        "title": event["title"],
                        "markdown_content": event["markdown_content"],
                        "markdown_path": formatted_markdown_path,
                        "status": "Article ready",
                        "saved": True,
                        "cached": False,
                    },
                )
        except ArticleGenerationError as exc:
            yield sse_event("error", {"detail": str(exc)})
        except Exception as exc:
            logger.exception("Failed while saving generated article")
            yield sse_event(
                "error",
                {"detail": f"Failed to save generated article: {exc}"},
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
