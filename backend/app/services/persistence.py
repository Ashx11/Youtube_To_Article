import sqlite3
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterator

BACKEND_DIR = Path(__file__).resolve().parents[2]


class PersistenceService:
    """Lightweight SQLite persistence for videos, transcripts, summaries, and articles."""

    _DEFAULT_TEMPERATURE = 0.6
    _MIN_TEMPERATURE = Decimal("0.2")
    _MAX_TEMPERATURE = Decimal("1.0")
    _DEFAULT_PROVIDER = "openai"
    _SUPPORTED_PROVIDERS = {"openai", "gemini"}
    _DEFAULT_MODELS = {
        "openai": "gpt-5.4",
        "gemini": "gemini-3.1-pro-preview",
    }
    _SUPPORTED_MODELS = {
        "openai": {"gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano"},
        "gemini": {
            "gemini-3.1-pro-preview",
            "gemini-3-flash-preview",
            "gemini-3.1-flash-lite-preview",
        },
    }
    _SUPPORTED_TONES = {"editorial", "casual", "technical"}

    def __init__(self, db_path: str | Path = BACKEND_DIR / "data" / "app.db") -> None:
        self._db_path = Path(db_path)
        self.initialize()

    def initialize(self) -> None:
        """Create the database and tables if they do not already exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as connection:
            self._migrate_legacy_schema(connection)
            self._create_videos_table(connection)
            self._create_transcripts_table(connection)
            self._ensure_transcript_summaries_table(connection)
            self._ensure_articles_table(connection)
            connection.execute("DROP TABLE IF EXISTS channels")

    def normalize_temperature(self, value: Any) -> float:
        """Normalize temperature for cache lookup and persistence stability."""
        try:
            numeric_value = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return self._DEFAULT_TEMPERATURE

        rounded_value = numeric_value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        if self._MIN_TEMPERATURE <= rounded_value <= self._MAX_TEMPERATURE:
            return float(rounded_value)

        return self._DEFAULT_TEMPERATURE

    def ensure_video(
        self,
        video_id: str,
        youtube_url: str,
    ) -> None:
        """Ensure the video row exists and keep its URL up to date."""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO videos (video_id, youtube_url)
                VALUES (?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    youtube_url = excluded.youtube_url
                """,
                (video_id, youtube_url),
            )

    def get_transcript(self, video_id: str) -> dict[str, Any] | None:
        """Return a cached cleaned transcript when present."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    t.video_id,
                    t.language,
                    t.segment_count,
                    t.cleaned_text,
                    v.youtube_url
                FROM transcripts AS t
                JOIN videos AS v ON v.video_id = t.video_id
                WHERE t.video_id = ?
                """,
                (video_id,),
            ).fetchone()

        return self._row_to_dict(row)

    def save_transcript(
        self,
        video_id: str,
        youtube_url: str,
        language: str,
        segment_count: int,
        cleaned_text: str,
    ) -> None:
        """Persist cleaned transcript data for a video."""
        self.ensure_video(video_id=video_id, youtube_url=youtube_url)

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO transcripts (video_id, language, segment_count, cleaned_text)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    language = excluded.language,
                    segment_count = excluded.segment_count,
                    cleaned_text = excluded.cleaned_text
                """,
                (video_id, language, segment_count, cleaned_text),
            )
            connection.execute(
                "DELETE FROM transcript_summaries WHERE video_id = ?",
                (video_id,),
            )

    def get_transcript_summary(self, video_id: str, provider: str) -> dict[str, Any] | None:
        """Return a persisted combined neutral summary for a long transcript."""
        normalized_provider = self._normalize_provider(provider)

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    video_id,
                    provider,
                    summary_text,
                    source_length,
                    created_at
                FROM transcript_summaries
                WHERE video_id = ? AND provider = ?
                """,
                (video_id, normalized_provider),
            ).fetchone()

        return self._row_to_dict(row)

    def save_transcript_summary(
        self,
        video_id: str,
        provider: str,
        summary_text: str,
        source_length: int | None = None,
    ) -> None:
        """Persist a combined neutral summary for reuse across article variants."""
        normalized_provider = self._normalize_provider(provider)

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO transcript_summaries (video_id, provider, summary_text, source_length)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(video_id, provider) DO UPDATE SET
                    summary_text = excluded.summary_text,
                    source_length = excluded.source_length
                """,
                (video_id, normalized_provider, summary_text, source_length),
            )

    def get_article(
        self,
        video_id: str,
        provider: str,
        model: str,
        tone: str,
        temperature: Any,
    ) -> dict[str, Any] | None:
        """Return a cached article when it matches video, provider, tone, and temperature."""
        normalized_provider = self._normalize_provider(provider)
        normalized_model = self._normalize_model(normalized_provider, model)
        normalized_tone = self._normalize_tone(tone)
        normalized_temperature = self.normalize_temperature(temperature)

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    video_id,
                    provider,
                    model,
                    tone,
                    temperature,
                    title,
                    markdown_content,
                    markdown_path,
                    created_at
                FROM articles
                WHERE video_id = ? AND provider = ? AND model = ? AND tone = ? AND temperature = ?
                """,
                (
                    video_id,
                    normalized_provider,
                    normalized_model,
                    normalized_tone,
                    normalized_temperature,
                ),
            ).fetchone()

        return self._row_to_dict(row)

    def save_article(
        self,
        video_id: str,
        youtube_url: str,
        provider: str,
        model: str,
        tone: str,
        temperature: Any,
        title: str,
        markdown_content: str,
        markdown_path: str,
    ) -> dict[str, Any]:
        """Persist a generated article and return the saved row data."""
        normalized_provider = self._normalize_provider(provider)
        normalized_model = self._normalize_model(normalized_provider, model)
        normalized_tone = self._normalize_tone(tone)
        normalized_temperature = self.normalize_temperature(temperature)
        self.ensure_video(video_id=video_id, youtube_url=youtube_url)

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO articles (
                    video_id,
                    provider,
                    model,
                    tone,
                    temperature,
                    title,
                    markdown_content,
                    markdown_path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id, provider, model, tone, temperature) DO UPDATE SET
                    title = excluded.title,
                    markdown_content = excluded.markdown_content,
                    markdown_path = excluded.markdown_path
                """,
                (
                    video_id,
                    normalized_provider,
                    normalized_model,
                    normalized_tone,
                    normalized_temperature,
                    title,
                    markdown_content,
                    markdown_path,
                ),
            )

        saved_article = self.get_article(
            video_id=video_id,
            provider=normalized_provider,
            model=normalized_model,
            tone=normalized_tone,
            temperature=normalized_temperature,
        )
        if not saved_article:
            raise RuntimeError("Failed to read back the saved article record.")

        return saved_article

    def list_recent_videos(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return the most recent video rows."""
        return self._list_recent_rows(
            query="""
                SELECT
                    video_id,
                    youtube_url,
                    created_at
                FROM videos
                ORDER BY created_at DESC
                LIMIT ?
            """,
            limit=limit,
        )

    def list_recent_transcripts(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return the most recent transcript rows."""
        return self._list_recent_rows(
            query="""
                SELECT
                    id,
                    video_id,
                    language,
                    segment_count,
                    cleaned_text,
                    created_at
                FROM transcripts
                ORDER BY created_at DESC
                LIMIT ?
            """,
            limit=limit,
        )

    def list_recent_articles(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return the most recent article rows."""
        return self._list_recent_rows(
            query="""
                SELECT
                    id,
                    video_id,
                    provider,
                    model,
                    tone,
                    temperature,
                    title,
                    markdown_content,
                    markdown_path,
                    created_at
                FROM articles
                ORDER BY created_at DESC
                LIMIT ?
            """,
            limit=limit,
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")

        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _normalize_tone(self, tone: str) -> str:
        normalized_tone = (tone or "editorial").strip().casefold()
        return normalized_tone if normalized_tone in self._SUPPORTED_TONES else "editorial"

    def _normalize_provider(self, provider: str) -> str:
        normalized_provider = (provider or self._DEFAULT_PROVIDER).strip().casefold()
        return (
            normalized_provider
            if normalized_provider in self._SUPPORTED_PROVIDERS
            else self._DEFAULT_PROVIDER
        )

    def _normalize_model(self, provider: str, model: str) -> str:
        normalized_provider = self._normalize_provider(provider)
        normalized_model = (model or self._DEFAULT_MODELS[normalized_provider]).strip().casefold()
        supported_models = self._SUPPORTED_MODELS[normalized_provider]
        return (
            normalized_model
            if normalized_model in supported_models
            else self._DEFAULT_MODELS[normalized_provider]
        )

    def _migrate_legacy_schema(self, connection: sqlite3.Connection) -> None:
        video_columns = self._get_table_columns(connection, "videos")
        if "channel_id" not in video_columns:
            return

        article_columns = self._get_table_columns(connection, "articles")
        has_provider_column = "provider" in article_columns

        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.execute("ALTER TABLE videos RENAME TO videos_legacy")
            connection.execute("ALTER TABLE transcripts RENAME TO transcripts_legacy")

            if article_columns:
                connection.execute("ALTER TABLE articles RENAME TO articles_legacy")

            self._create_videos_table(connection)
            self._create_transcripts_table(connection)
            self._create_transcript_summaries_table(connection)
            self._create_articles_table(connection)

            connection.execute(
                """
                INSERT INTO videos (video_id, youtube_url, created_at)
                SELECT
                    video_id,
                    youtube_url,
                    created_at
                FROM videos_legacy
                """
            )
            connection.execute(
                """
                INSERT INTO transcripts (
                    id,
                    video_id,
                    language,
                    segment_count,
                    cleaned_text,
                    created_at
                )
                SELECT
                    id,
                    video_id,
                    language,
                    segment_count,
                    cleaned_text,
                    created_at
                FROM transcripts_legacy
                """
            )

            if article_columns:
                if has_provider_column:
                    connection.execute(
                        """
                        INSERT INTO articles (
                            id,
                            video_id,
                            provider,
                            tone,
                            temperature,
                            title,
                            markdown_content,
                            markdown_path,
                            created_at
                        )
                        SELECT
                            id,
                            video_id,
                            provider,
                            tone,
                            temperature,
                            title,
                            markdown_content,
                            markdown_path,
                            created_at
                        FROM articles_legacy
                        """
                    )
                else:
                    connection.execute(
                        """
                        INSERT INTO articles (
                            id,
                            video_id,
                            provider,
                            tone,
                            temperature,
                            title,
                            markdown_content,
                            markdown_path,
                            created_at
                        )
                        SELECT
                            id,
                            video_id,
                            ?,
                            tone,
                            temperature,
                            title,
                            markdown_content,
                            markdown_path,
                            created_at
                        FROM articles_legacy
                        """,
                        (self._DEFAULT_PROVIDER,),
                    )

            connection.execute("DROP TABLE IF EXISTS videos_legacy")
            connection.execute("DROP TABLE IF EXISTS transcripts_legacy")
            connection.execute("DROP TABLE IF EXISTS articles_legacy")
            connection.execute("DROP TABLE IF EXISTS channels")
        finally:
            connection.execute("PRAGMA foreign_keys = ON")

    def _create_videos_table(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS videos (
                video_id TEXT PRIMARY KEY,
                youtube_url TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    def _create_transcripts_table(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS transcripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT NOT NULL UNIQUE,
                language TEXT NOT NULL,
                segment_count INTEGER NOT NULL,
                cleaned_text TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (video_id) REFERENCES videos (video_id)
            )
            """
        )

    def _create_transcript_summaries_table(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS transcript_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                summary_text TEXT NOT NULL,
                source_length INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (video_id) REFERENCES videos (video_id),
                UNIQUE (video_id, provider)
            )
            """
        )

    def _ensure_transcript_summaries_table(self, connection: sqlite3.Connection) -> None:
        table_exists = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'transcript_summaries'
            """
        ).fetchone()

        if not table_exists:
            self._create_transcript_summaries_table(connection)
            return

        column_names = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(transcript_summaries)").fetchall()
        }
        if "provider" in column_names:
            return

        # Legacy long-summary cache entries were keyed only by video and are safe to drop.
        # They are derived artifacts and can be rebuilt with the correct provider on demand.
        connection.execute("ALTER TABLE transcript_summaries RENAME TO transcript_summaries_legacy")
        self._create_transcript_summaries_table(connection)
        connection.execute("DROP TABLE transcript_summaries_legacy")

    def _ensure_articles_table(self, connection: sqlite3.Connection) -> None:
        table_exists = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'articles'
            """
        ).fetchone()

        if not table_exists:
            self._create_articles_table(connection)
            return

        column_names = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(articles)").fetchall()
        }
        if "provider" in column_names and "model" in column_names:
            return

        connection.execute("ALTER TABLE articles RENAME TO articles_legacy")
        self._create_articles_table(connection)
        if "provider" in column_names:
            connection.execute(
                """
                INSERT INTO articles (
                    id,
                    video_id,
                    provider,
                    model,
                    tone,
                    temperature,
                    title,
                    markdown_content,
                    markdown_path,
                    created_at
                )
                SELECT
                    id,
                    video_id,
                    provider,
                    CASE
                        WHEN provider = 'gemini' THEN ?
                        ELSE ?
                    END,
                    tone,
                    temperature,
                    title,
                    markdown_content,
                    markdown_path,
                    created_at
                FROM articles_legacy
                """,
                (
                    self._DEFAULT_MODELS["gemini"],
                    self._DEFAULT_MODELS["openai"],
                ),
            )
        else:
            connection.execute(
                """
                INSERT INTO articles (
                    id,
                    video_id,
                    provider,
                    model,
                    tone,
                    temperature,
                    title,
                    markdown_content,
                    markdown_path,
                    created_at
                )
                SELECT
                    id,
                    video_id,
                    ?,
                    ?,
                    tone,
                    temperature,
                    title,
                    markdown_content,
                    markdown_path,
                    created_at
                FROM articles_legacy
                """,
                (
                    self._DEFAULT_PROVIDER,
                    self._DEFAULT_MODELS[self._DEFAULT_PROVIDER],
                ),
            )
        connection.execute("DROP TABLE articles_legacy")

    def _create_articles_table(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                tone TEXT NOT NULL,
                temperature REAL NOT NULL,
                title TEXT NOT NULL,
                markdown_content TEXT NOT NULL,
                markdown_path TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (video_id) REFERENCES videos (video_id),
                UNIQUE (video_id, provider, model, tone, temperature)
            )
            """
        )

    def _get_table_columns(self, connection: sqlite3.Connection, table_name: str) -> set[str]:
        table_exists = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table_name,),
        ).fetchone()
        if not table_exists:
            return set()

        return {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }

    def _list_recent_rows(self, query: str, limit: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(query, (limit,)).fetchall()

        return [dict(row) for row in rows]

    def _row_to_dict(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None
