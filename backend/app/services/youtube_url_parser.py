from urllib.parse import parse_qs, urlparse


class YouTubeUrlParser:
    """Extracts video IDs from supported YouTube URL formats."""

    _ALLOWED_SCHEMES = {"http", "https"}
    _WATCH_HOSTS = {"www.youtube.com", "youtube.com", "m.youtube.com"}
    _SHORT_HOSTS = {"youtu.be"}

    def extract_video_id(self, url: str) -> str:
        """Return the YouTube video ID from a supported URL."""
        if not url or not url.strip():
            raise ValueError("YouTube URL is required.")

        parsed_url = urlparse(url.strip())
        hostname = parsed_url.hostname

        if parsed_url.scheme not in self._ALLOWED_SCHEMES or not hostname:
            raise ValueError("Invalid YouTube URL.")

        host = hostname.lower()
        path_parts = [part for part in parsed_url.path.split("/") if part]

        if host in self._WATCH_HOSTS:
            if parsed_url.path == "/watch":
                video_id = parse_qs(parsed_url.query).get("v", [""])[0]
                if video_id:
                    return video_id

            if len(path_parts) >= 2 and path_parts[0] in {"shorts", "embed"}:
                return path_parts[1]

        if host in self._SHORT_HOSTS and path_parts:
            return path_parts[0]

        raise ValueError("Unsupported YouTube URL format.")
