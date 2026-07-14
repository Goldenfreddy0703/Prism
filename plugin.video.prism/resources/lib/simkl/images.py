"""Simkl CDN image URLs — https://api.simkl.org/conventions/images.md"""
from __future__ import annotations

from typing import Any
from urllib.parse import unquote

# wsrv.nl proxy + simkl.in origin (required by Simkl docs)
SIMKL_IMG_BASE = "https://wsrv.nl/?url=https://simkl.in"
SIMKL_CDN_HOST = "https://simkl.in"
SIMKL_IMG_QUALITY = "&q=90"

# API category path segments (always plural, trailing slash in final URL)
KIND_POSTERS = "posters"
KIND_FANART = "fanart"
KIND_EPISODES = "episodes"
KIND_AVATARS = "avatars"

# Size suffix reference tables (simkl.apib → conventions/images)
POSTER_SIZES = ("_ca", "_cm", "_w", "_m", "_c", "_s")
FANART_SIZES = ("_medium", "_mobile", "_s48", "_w", "_d")
EPISODE_SIZES = ("_w", "_c", "_m")

# artwork.preferredsize: 0=Largest, 1=Medium, 2=Small (matches TMDB/TVDB tier labels)
POSTER_SIZE_BY_PREFERENCE = ("_m", "_c", "_cm")  # 340, 170, 84 px wide
FANART_SIZE_BY_PREFERENCE = ("_medium", "_mobile", "_w")  # 1920, 960, 600 px wide
EPISODE_SIZE_BY_PREFERENCE = ("_w", "_c", "_m")  # 600, 210, 112 px wide

# Legacy defaults when no preference is applied explicitly (largest tier)
DEFAULT_POSTER_SIZE = POSTER_SIZE_BY_PREFERENCE[0]
DEFAULT_FANART_SIZE = FANART_SIZE_BY_PREFERENCE[0]
DEFAULT_EPISODE_THUMB_SIZE = EPISODE_SIZE_BY_PREFERENCE[0]

_ART_KEYS_BY_KIND: dict[str, tuple[str, ...]] = {
    KIND_POSTERS: ("poster", "icon", "tvshow.poster", "season.poster"),
    KIND_FANART: ("fanart", "tvshow.fanart", "season.fanart"),
    KIND_EPISODES: ("thumb", "season.thumb"),
}


def artwork_preference_index(preference: int | None = None) -> int:
    if preference is None:
        from resources.lib.modules.globals import g

        preference = g.get_int_setting("artwork.preferredsize", 0)
    try:
        return max(0, min(2, int(preference)))
    except (TypeError, ValueError):
        return 1


def sizes_for_preference(preference: int | None = None) -> tuple[str, str, str]:
    """Return (poster_suffix, fanart_suffix, episode_suffix) for artwork.preferredsize."""
    idx = artwork_preference_index(preference)
    return (
        POSTER_SIZE_BY_PREFERENCE[idx],
        FANART_SIZE_BY_PREFERENCE[idx],
        EPISODE_SIZE_BY_PREFERENCE[idx],
    )


def _default_size_for_kind(kind: str, preference: int | None = None) -> str:
    poster_size, fanart_size, episode_size = sizes_for_preference(preference)
    if kind == KIND_FANART:
        return fanart_size
    if kind == KIND_EPISODES:
        return episode_size
    return poster_size


def _strip_known_suffix(path: str, sizes: tuple[str, ...]) -> str:
    for ext in (".webp", ".jpg", ".png"):
        for size in sorted(sizes, key=len, reverse=True):
            suffix = f"{size}{ext}"
            if path.endswith(suffix):
                return path[: -len(suffix)]
    for size in sorted(sizes, key=len, reverse=True):
        if path.endswith(size):
            return path[: -len(size)]
    return path


def _sizes_for_kind(kind: str) -> tuple[str, ...]:
    if kind == KIND_FANART:
        return FANART_SIZES
    if kind == KIND_EPISODES:
        return EPISODE_SIZES
    return POSTER_SIZES


def _normalize_image_path(path: str, kind: str) -> str:
    """Strip category prefix and any baked-in size suffix from an API path."""
    path = str(path).strip()
    if not path:
        return ""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    path = path.lstrip("/")
    prefix = f"{kind}/"
    if path.startswith(prefix):
        path = path[len(prefix) :]
    return _strip_known_suffix(path, _sizes_for_kind(kind))


def _default_ext(kind: str, size: str) -> str:
    if kind == KIND_FANART and size == "_d":
        return ".jpg"
    if kind == KIND_AVATARS:
        return ".jpg"
    return ".webp"


def poster_placeholder_url(size: str | None = None) -> str:
    """Built-in Simkl missing-poster placeholder (wsrv-proxied)."""
    if size is None:
        size = sizes_for_preference()[0]
    ph = "_s" if size == "_s" else "_c"
    return f"{SIMKL_IMG_BASE}/poster_no_pic{ph}.png"


def _path_from_simkl_url(url: str, kind: str) -> str | None:
    """Extract a normalized Simkl path fragment from a wsrv/simkl.in URL."""
    if not url or "simkl.in" not in url or "poster_no_pic" in url:
        return None
    try:
        if "url=" in url:
            inner = unquote(url.split("url=", 1)[1].split("&", 1)[0])
        else:
            inner = url
        prefix = f"/{kind}/"
        idx = inner.find(prefix)
        if idx < 0:
            return None
        fragment = inner[idx + len(prefix) :].split("?", 1)[0]
        normalized = _normalize_image_path(fragment, kind)
        return normalized or None
    except (IndexError, ValueError):
        return None


def simkl_image_url(
    path: str | None,
    *,
    kind: str = KIND_POSTERS,
    size: str | None = None,
    ext: str | None = None,
    placeholder: bool = False,
    preference: int | None = None,
) -> str | None:
    """
    Build a Simkl image URL from an API path field (poster, fanart, img, avatar).

    See https://api.simkl.org/conventions/images.md
    """
    if not path:
        if placeholder and kind == KIND_POSTERS:
            return poster_placeholder_url(size or _default_size_for_kind(kind, preference))
        return None

    if str(path).startswith("http://") or str(path).startswith("https://"):
        return str(path).strip()

    if size is None:
        size = _default_size_for_kind(kind, preference)

    if ext is None:
        ext = _default_ext(kind, size)

    normalized = _normalize_image_path(path, kind)
    if not normalized:
        return None

    return f"{SIMKL_IMG_BASE}/{kind}/{normalized}{size}{ext}{SIMKL_IMG_QUALITY}"


def rescale_simkl_image_url(url: str, *, kind: str, size: str | None = None) -> str:
    """Rebuild a Simkl CDN URL at the requested size tier; non-Simkl URLs pass through."""
    if size is None:
        size = _default_size_for_kind(kind)
    path = _path_from_simkl_url(url, kind)
    if not path:
        return url
    return simkl_image_url(path, kind=kind, size=size) or url


def rescale_simkl_art(art: dict[str, Any] | None, *, preference: int | None = None) -> dict[str, Any]:
    """Apply artwork.preferredsize to any Simkl-hosted URLs in a Kodi art dict."""
    if not art:
        return {}
    poster_size, fanart_size, episode_size = sizes_for_preference(preference)
    size_by_kind = {
        KIND_POSTERS: poster_size,
        KIND_FANART: fanart_size,
        KIND_EPISODES: episode_size,
    }
    out = dict(art)
    for kind, keys in _ART_KEYS_BY_KIND.items():
        size = size_by_kind[kind]
        for key in keys:
            value = out.get(key)
            if isinstance(value, str):
                out[key] = rescale_simkl_image_url(value, kind=kind, size=size)
    return out


def episode_thumb_url(
    img: str | None,
    *,
    size: str | None = None,
    preference: int | None = None,
) -> str | None:
    """Episode still from GET /tv/episodes/{id} or /anime/episodes/{id} `img` field."""
    if size is None:
        size = _default_size_for_kind(KIND_EPISODES, preference)
    if img and str(img).startswith("http"):
        return rescale_simkl_image_url(str(img), kind=KIND_EPISODES, size=size)
    return simkl_image_url(img, kind=KIND_EPISODES, size=size, preference=preference)


def attach_episode_still(info: dict, raw_episode: dict, *, preference: int | None = None) -> dict | None:
    """Write simkl_img path + thumb URL onto episode info and return art dict."""
    img = raw_episode.get("img")
    if not img:
        return None
    if str(img).startswith("http"):
        info["simkl_img"] = str(img)
    else:
        info["simkl_img"] = _normalize_image_path(str(img), KIND_EPISODES)
    thumb = episode_thumb_url(img, preference=preference)
    if not thumb:
        return None
    info["thumb"] = thumb
    return {"thumb": thumb}


def attach_show_art(source: dict[str, Any] | None, *, preference: int | None = None) -> dict[str, Any]:
    """Build Kodi art dict from Simkl show/movie `poster` + `fanart` API path fields."""
    if not source or not isinstance(source, dict):
        return {}
    poster_size, fanart_size, _ = sizes_for_preference(preference)
    art: dict[str, Any] = {}
    poster = simkl_image_url(source.get("poster"), kind=KIND_POSTERS, size=poster_size, preference=preference)
    fanart = simkl_image_url(source.get("fanart"), kind=KIND_FANART, size=fanart_size, preference=preference)
    if poster:
        art["poster"] = poster
    if fanart:
        art["fanart"] = fanart
    return art
