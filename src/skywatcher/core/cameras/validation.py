"""Input validation for the Sky Cameras section: URLs, embeds and uploaded video.

Nothing here fetches a URL. The rules are deliberately strict because submissions
come from the public: https only, no credentials in the URL, a bounded length, and
inline players only for the two hosts whose embed players we allow.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

MAX_URL_LENGTH = 2048
CATEGORIES = ("sky", "beach", "coast", "mountain", "river", "lake", "lagoon", "city")
LICENSES = ("cc-by-4.0", "display-only")

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
_VIMEO_ID = re.compile(r"^\d{6,12}$")
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtube-nocookie.com"}
_VIMEO_HOSTS = {"vimeo.com", "www.vimeo.com", "player.vimeo.com"}

EMBED_PLAYERS = {
    "youtube": "https://www.youtube-nocookie.com/embed/{video_id}",
    "vimeo": "https://player.vimeo.com/video/{video_id}",
}


def normalize_text(text: str) -> str:
    """Case- and accent-insensitive comparison key ("Mayagüez" -> "mayaguez")."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.casefold().split())


class SubmissionError(ValueError):
    """A submission field failed validation; the message is safe to show the user."""


def validate_https_url(value: str, field: str = "url") -> str:
    """Return the trimmed URL if it is an absolute https URL without credentials."""
    url = (value or "").strip()
    if not url:
        raise SubmissionError(f"{field} is required")
    if len(url) > MAX_URL_LENGTH:
        raise SubmissionError(f"{field} is longer than {MAX_URL_LENGTH} characters")
    if any(ch.isspace() for ch in url):
        raise SubmissionError(f"{field} must not contain spaces")
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise SubmissionError(f"{field} must start with https://")
    if not parts.hostname or "." not in parts.hostname:
        raise SubmissionError(f"{field} must name a public host")
    if parts.username or parts.password:
        raise SubmissionError(f"{field} must not contain a username or password")
    return url


def parse_embed(url: str) -> dict[str, str] | None:
    """Recognise a YouTube or Vimeo video URL and return ``{"kind", "video_id"}``.

    Returns None for any other URL; those are shown as links, never embedded.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    path = [segment for segment in parts.path.split("/") if segment]
    if host in _YOUTUBE_HOSTS:
        candidate = None
        if host == "youtu.be" and path:
            candidate = path[0]
        elif path[:1] == ["watch"]:
            candidate = next(iter(parse_qs(parts.query).get("v", [])), None)
        elif len(path) >= 2 and path[0] in {"live", "embed", "shorts"}:
            candidate = path[1]
        if candidate and _VIDEO_ID.match(candidate):
            return {"kind": "youtube", "video_id": candidate}
        return None
    if host in _VIMEO_HOSTS:
        digits = [segment for segment in path if _VIMEO_ID.match(segment)]
        if digits:
            return {"kind": "vimeo", "video_id": digits[-1]}
    return None


def embed_url(embed: dict[str, str] | None) -> str | None:
    """The player URL for a validated embed, on an allowlisted host."""
    if not embed:
        return None
    template = EMBED_PLAYERS.get(embed.get("kind", ""))
    video_id = embed.get("video_id", "")
    if template is None or not _VIDEO_ID.match(video_id):
        return None
    return template.format(video_id=video_id)


def validate_categories(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        for item in str(value).split(","):
            item = item.strip().lower()
            if item and item not in cleaned:
                cleaned.append(item)
    if not cleaned:
        raise SubmissionError("choose at least one category")
    unknown = [item for item in cleaned if item not in CATEGORIES]
    if unknown:
        raise SubmissionError(f"unknown category: {', '.join(unknown)}")
    return cleaned


@dataclass(frozen=True)
class VideoType:
    extension: str
    media_type: str


def sniff_video(head: bytes) -> VideoType | None:
    """Identify MP4/MOV (ISO base media) or WebM from the first bytes of a file."""
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand == b"qt  ":
            return VideoType("mov", "video/quicktime")
        return VideoType("mp4", "video/mp4")
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return VideoType("webm", "video/webm")
    return None
