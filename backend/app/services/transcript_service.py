from typing import Any

from youtube_transcript_api import YouTubeTranscriptApi

try:
    from youtube_transcript_api import (
        CouldNotRetrieveTranscript,
        NoTranscriptFound,
        TranscriptsDisabled,
        VideoUnavailable,
    )
except ImportError:
    from youtube_transcript_api._errors import (  # type: ignore[attr-defined]
        CouldNotRetrieveTranscript,
        NoTranscriptFound,
        TranscriptsDisabled,
        VideoUnavailable,
    )


class TranscriptServiceError(Exception):
    """Raised when transcript retrieval fails after input validation."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class TranscriptService:
    """Fetches transcripts and normalizes them for the API layer."""

    _ENGLISH_LANGUAGES = ["en", "en-US", "en-GB", "en-CA", "en-AU"]

    def __init__(self) -> None:
        self._client = YouTubeTranscriptApi()

    def fetch(self, video_id: str) -> dict[str, Any]:
        """Fetch an English transcript for the given YouTube video ID."""
        if not video_id or not video_id.strip():
            raise ValueError("Video ID is required.")

        clean_video_id = video_id.strip()

        try:
            transcript = self._fetch_transcript(clean_video_id)
        except NoTranscriptFound as exc:
            raise TranscriptServiceError(
                "No English transcript was found for this video.",
                status_code=404,
            ) from exc
        except TranscriptsDisabled as exc:
            raise TranscriptServiceError(
                "Transcripts are disabled for this video.",
                status_code=403,
            ) from exc
        except VideoUnavailable as exc:
            raise TranscriptServiceError(
                "The requested video is unavailable.",
                status_code=404,
            ) from exc
        except CouldNotRetrieveTranscript as exc:
            raise TranscriptServiceError(
                "The transcript could not be retrieved.",
                status_code=502,
            ) from exc
        except Exception as exc:
            raise TranscriptServiceError(
                "An unexpected error occurred while fetching the transcript.",
                status_code=500,
            ) from exc

        segments = self._normalize_segments(transcript)

        return {
            "video_id": clean_video_id,
            "language": self._extract_language(transcript),
            "segment_count": len(segments),
            "segments": segments,
        }

    def _fetch_transcript(self, video_id: str) -> Any:
        if hasattr(self._client, "fetch"):
            return self._client.fetch(video_id, languages=self._ENGLISH_LANGUAGES)

        return YouTubeTranscriptApi.get_transcript(
            video_id,
            languages=self._ENGLISH_LANGUAGES,
        )

    def _normalize_segments(self, transcript: Any) -> list[dict[str, Any]]:
        raw_segments = (
            transcript.to_raw_data() if hasattr(transcript, "to_raw_data") else transcript
        )

        return [
            {
                "text": str(segment.get("text", "")),
                "start": float(segment.get("start", 0.0)),
                "duration": float(segment.get("duration", 0.0)),
            }
            for segment in raw_segments
        ]

    def _extract_language(self, transcript: Any) -> str:
        if hasattr(transcript, "language") and transcript.language:
            return str(transcript.language)

        if hasattr(transcript, "language_code") and transcript.language_code:
            return str(transcript.language_code)

        return "en"
