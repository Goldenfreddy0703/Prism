"""Legacy router/widget action names for discover lists (no heavy imports)."""
from __future__ import annotations

# Anime shows + movies shortcuts → discover endpoint keys in browse.DISCOVER_ENDPOINTS.
ANIME_LEGACY_DISCOVER_ACTIONS: dict[str, str] = {
    "animeShowsPopular": "popular",
    "animeMoviesPopular": "popular",
    "animeShowsTrending": "trending",
    "animeMoviesTrending": "trending",
    "animeShowsPopularRecent": "popular_recent",
    "animeMoviesPopularRecent": "popular_recent",
    "animeShowsTrendingRecent": "trending_recent",
    "animeMoviesTrendingRecent": "trending_recent",
    "animeShowsNew": "new",
    "animeMoviesNew": "new",
    "animeShowsPlayed": "played",
    "animeMoviesPlayed": "played",
    "animeShowsWatched": "watched",
    "animeMoviesWatched": "watched",
    "animeShowsCollected": "collected",
    "animeMoviesCollected": "collected",
    "animeShowsAnticipated": "anticipated",
    "animeMoviesAnticipated": "anticipated",
}
