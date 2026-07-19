from __future__ import annotations

import datetime
from collections import OrderedDict
from functools import cached_property

from resources.lib.common import tools
from resources.lib.modules.globals import g
from resources.lib.modules.language_lookup import get_country_set_for_language

ART_FANART = 0
ART_TMDB = 1
ART_TVDB = 2

# Simkl metadata is authoritative. TMDB, TVDB, MDBList, and Fanart only gap-fill empty fields.
# All merges into info/art use keep_original=True so Simkl values are never overwritten.


class MetadataHandler:
    def __init__(self):
        self.lang_code = g.get_language_code()
        self.lang_full_code = g.get_language_code(True)
        self.lang_region_code = self.lang_full_code.split("-")[-1]
        self.lang_based_movie_releases = g.get_bool_setting("movies.language_based_releases", True)
        self.allowed_artwork_languages = {None, "en", self.lang_code}
        self.preferred_artwork_size = g.get_int_setting("artwork.preferredsize", 0)

        self.genres = {
            "action": g.get_language_string(30491),
            "adventure": g.get_language_string(30492),
            "animation": g.get_language_string(30493),
            "anime": g.get_language_string(30494),
            "biography": g.get_language_string(30495),
            "children": g.get_language_string(30496),
            "comedy": g.get_language_string(30497),
            "crime": g.get_language_string(30498),
            "documentary": g.get_language_string(30499),
            "drama": g.get_language_string(30500),
            "family": g.get_language_string(30501),
            "fantasy": g.get_language_string(30502),
            "game-show": g.get_language_string(30503),
            "history": g.get_language_string(30504),
            "holiday": g.get_language_string(30505),
            "home-and-garden": g.get_language_string(30506),
            "horror": g.get_language_string(30507),
            "mini-series": g.get_language_string(30508),
            "music": g.get_language_string(30509),
            "musical": g.get_language_string(30510),
            "mystery": g.get_language_string(30511),
            "news": g.get_language_string(30512),
            "none": g.get_language_string(30513),
            "reality": g.get_language_string(30514),
            "romance": g.get_language_string(30515),
            "science-fiction": g.get_language_string(30516),
            "sci-fi": g.get_language_string(30516),
            "short": g.get_language_string(30517),
            "soap": g.get_language_string(30518),
            "special-interest": g.get_language_string(30519),
            "sporting-event": g.get_language_string(30520),
            "superhero": g.get_language_string(30521),
            "suspense": g.get_language_string(30522),
            "talk-show": g.get_language_string(30523),
            "talkshow": g.get_language_string(30523),
            "thriller": g.get_language_string(30524),
            "tv-movie": g.get_language_string(30525),
            "war": g.get_language_string(30526),
            "western": g.get_language_string(30527),
        }

    @property
    def meta_hash(self):
        from resources.lib.modules.metadata_providers import art_limit, art_option_enabled

        return tools.md5_hash(
            [
                self.lang_code,
                art_limit("movies.poster_limit", "movie"),
                art_limit("movies.fanart_limit", "movie"),
                art_limit("movies.keyart_limit", "movie"),
                art_limit("movies.characterart_limit", "movie"),
                art_option_enabled("movies.banner", "movie"),
                art_option_enabled("movies.clearlogo", "movie"),
                art_option_enabled("movies.landscape", "movie"),
                art_option_enabled("movies.clearart", "movie"),
                art_option_enabled("movies.discart", "movie"),
                art_limit("anime.poster_limit", "anime"),
                art_limit("anime.fanart_limit", "anime"),
                art_limit("anime.keyart_limit", "anime"),
                art_limit("anime.characterart_limit", "anime"),
                art_option_enabled("anime.banner", "anime_series"),
                art_option_enabled("anime.clearlogo", "anime_series"),
                art_option_enabled("anime.landscape", "anime_series"),
                art_option_enabled("anime.clearart", "anime_series"),
                art_option_enabled("anime.discart", "anime_movie"),
                art_option_enabled("anime.season.poster", "anime_series"),
                art_option_enabled("anime.season.banner", "anime_series"),
                art_option_enabled("anime.season.landscape", "anime_series"),
                art_option_enabled("anime.season.fanart", "anime_series"),
                art_option_enabled("anime.episode.fanart", "anime_series"),
                art_limit("tvshows.poster_limit", "tvshow"),
                art_limit("tvshows.fanart_limit", "tvshow"),
                art_limit("tvshows.keyart_limit", "tvshow"),
                art_limit("tvshows.characterart_limit", "tvshow"),
                art_option_enabled("tvshows.banner", "tvshow"),
                art_option_enabled("tvshows.clearlogo", "tvshow"),
                art_option_enabled("tvshows.landscape", "tvshow"),
                art_option_enabled("tvshows.clearart", "tvshow"),
                g.get_bool_setting("season.poster", True),
                g.get_bool_setting("season.banner", True),
                g.get_bool_setting("season.landscape", True),
                g.get_bool_setting("season.fanart", True),
                g.get_bool_setting("episode.fanart", True),
                g.get_int_setting("tvshows.preferedsource", 1),
                g.get_int_setting("movies.preferedsource", 1),
                g.get_int_setting("anime.preferedsource", 1),
                self._effective_preferred_art_source("movie"),
                self._effective_preferred_art_source("tvshow"),
                self._effective_preferred_art_source("tvshow", "anime_series"),
                g.get_int_setting("artwork.preferredsize", 0),
                self.tmdb_api.meta_hash,
                self.tvdb_api.meta_hash,
                self.simkl_api.meta_hash,
                self.fanarttv_api.meta_hash,
                self.fanarttv_api.fanart_support,
                self._provider_enabled("tmdb"),
                self._provider_enabled("tvdb"),
                self._provider_enabled("fanart"),
                self._provider_enabled("mdblist"),
            ]
        )

    @cached_property
    def simkl_api(self):
        from resources.lib.indexers.simkl import SimklAPI

        return SimklAPI()

    @cached_property
    def tmdb_api(self):
        from resources.lib.indexers.tmdb import TMDBAPI

        return TMDBAPI()

    @cached_property
    def tvdb_api(self):
        from resources.lib.indexers.tvdb import TVDBAPI

        return TVDBAPI()

    @cached_property
    def fanarttv_api(self):
        from resources.lib.indexers.fanarttv import FanartTv

        return FanartTv()

    # region format art
    def format_db_object(self, db_object):
        return [self.format_meta(i) for i in db_object]

    def format_meta(self, db_object):
        simkl_data = self._coalesce_simkl_object(db_object, db_object.get("simkl_object"))
        tmdb_object = db_object.get("tmdb_object")
        tvdb_object = db_object.get("tvdb_object")
        fanart_object = db_object.get("fanart_object")
        show_info = db_object.get("show_info")
        season_info = db_object.get("season_info")
        show_art = db_object.get("show_art")
        season_art = db_object.get("season_art")
        show_cast = db_object.get("show_cast")
        season_cast = db_object.get("season_cast")

        result = {"info": {}, "art": {}, "cast": []}

        from resources.lib.modules.artwork_profile import artwork_profile_for_row

        simkl_info = tools.safe_dict_get(simkl_data, "info") or {}
        default_media = simkl_info.get("mediatype") or "tvshow"
        profile_info = dict(simkl_info)
        for parent in (show_info, season_info):
            if isinstance(parent, dict) and parent.get("catalog") and not profile_info.get("catalog"):
                profile_info["catalog"] = parent["catalog"]
        art_profile = db_object.get("_art_profile") or artwork_profile_for_row(
            {"info": profile_info, "simkl_id": db_object.get("simkl_id")},
            default_media,
        )

        result.update(
            self._apply_best_fit_meta_data(
                simkl_data, tmdb_object, tvdb_object, fanart_object, art_profile=art_profile
            )
        )

        self._show_season_art_fallback(result, season_art, show_art)
        self._add_season_show_info(result, season_info, show_info)
        self._add_season_show_art(result, season_art, show_art)
        self._add_season_show_cast(result, season_cast, show_cast)
        if result["info"].get("mediatype") == "tvshow" and result["info"].get("simkl_id"):
            from resources.lib.simkl.ids import attach_show_identity, slug_from_info

            attach_show_identity(result["info"], int(result["info"]["simkl_id"]), slug_from_info(result["info"]))
        self._apply_simkl_episode_thumb(result, simkl_data)
        self._restore_simkl_child_info(result, simkl_data)
        self._restore_simkl_primary_art(result, simkl_data)
        from resources.lib.simkl.images import rescale_simkl_art

        result["art"] = rescale_simkl_art(result.get("art"))
        if result["info"].get("thumb"):
            from resources.lib.simkl.images import episode_thumb_url

            thumb = episode_thumb_url(
                result["info"].get("simkl_img") or result["info"].get("thumb"),
            )
            if thumb:
                result["info"]["thumb"] = thumb
                result.setdefault("art", {})["thumb"] = thumb
        from resources.lib.simkl.field_map import finalize_playback_info
        from resources.lib.simkl.ids import canonicalize_info_identity

        canonicalize_info_identity(result["info"])
        finalize_playback_info(result["info"])
        if result["info"].get("mediatype") == "season":
            MetadataHandler._title_fallback(result)
        from resources.lib.modules.meta_storage import slim_formatted_item

        return slim_formatted_item(result)

    @staticmethod
    def _restore_simkl_primary_art(result, simkl_data):
        """Simkl poster/fanart/thumb wins over TMDB/TVDB/Fanart gap-fill."""
        simkl_art = tools.safe_dict_get(simkl_data, "art") or {}
        if not simkl_art:
            return
        art = result.setdefault("art", {})
        for key in ("poster", "fanart", "thumb", "icon"):
            if simkl_art.get(key):
                art[key] = simkl_art[key]

    @staticmethod
    def _restore_simkl_child_info(result, simkl_data):
        """Simkl is authoritative for season/episode metadata (structure + text fields)."""
        simkl_info = tools.safe_dict_get(simkl_data, "info")
        if not simkl_info:
            return
        mediatype = result["info"].get("mediatype")
        if mediatype not in ("episode", "season"):
            return

        from resources.lib.simkl.field_map import merge_simkl_child_supplemental_info

        merged = dict(simkl_info)
        merge_simkl_child_supplemental_info(merged, result["info"])
        result["info"] = merged

        if mediatype == "season":
            from resources.lib.simkl.field_map import ensure_season_title

            ensure_season_title(result["info"])

        simkl_art = tools.safe_dict_get(simkl_data, "art") or {}
        if simkl_art:
            art = result.setdefault("art", {})
            for key, value in simkl_art.items():
                if value and (key not in art or key in ("thumb", "icon", "poster")):
                    art[key] = value

    @staticmethod
    def _simkl_episode_lookup(db_object):
        from resources.lib.simkl.ids import episode_num_from_info

        info = tools.safe_dict_get(db_object, "simkl_object", "info") or {}
        return info.get("season"), episode_num_from_info(info)

    @staticmethod
    def _apply_simkl_episode_thumb(result, simkl_data):
        """Simkl GET /tv/episodes/{id} `img` → episode list thumb (Otaku / apib wsrv pattern)."""
        if tools.safe_dict_get(result, "info", "mediatype") != "episode":
            return
        from resources.lib.simkl.images import episode_thumb_url

        thumb = tools.safe_dict_get(simkl_data, "art", "thumb")
        if not thumb:
            thumb = tools.safe_dict_get(result, "info", "thumb")
        if not thumb:
            img = tools.safe_dict_get(simkl_data, "info", "simkl_img") or tools.safe_dict_get(
                simkl_data, "info", "img"
            )
            thumb = episode_thumb_url(img)
        if not thumb:
            return
        result.setdefault("art", {})["thumb"] = thumb
        result["info"]["thumb"] = thumb

    @staticmethod
    def _add_season_show_info(result, season_info, show_info):
        from resources.lib.simkl.ids import attach_tv_context, slug_from_info

        if season_info:
            result["info"]["simkl_season_id"] = season_info["simkl_id"]
            if not result["info"].get("mpaa") and (mpaa := season_info.get("mpaa")):
                result["info"]["mpaa"] = mpaa
        if show_info:
            show_id = show_info.get("simkl_id")
            if show_id is not None:
                attach_tv_context(
                    result["info"],
                    int(show_id),
                    season_row_id=season_info.get("simkl_id") if season_info else None,
                    show_info=show_info,
                    slug=slug_from_info(show_info),
                )
            if not result["info"].get("tvshowtitle"):
                result["info"]["tvshowtitle"] = show_info.get("title")
            if not result["info"].get("tmdb_show_id"):
                result["info"]["tmdb_show_id"] = show_info.get("tmdb_id")
            if not result["info"].get("tvdb_show_id"):
                result["info"]["tvdb_show_id"] = show_info.get("tvdb_id")
            if not result["info"].get("year"):
                result["info"]["year"] = show_info.get("year")
            if not result["info"].get("tvshow.year"):
                result["info"]["tvshow.year"] = show_info.get("year")
            if not result["info"].get("studio"):
                result["info"]["studio"] = show_info.get("studio")
            if not result["info"].get("country_origin"):
                result["info"]["country_origin"] = show_info.get("country_origin")
            if not result["info"].get("aliases") and show_info.get("aliases"):
                result["info"]["aliases"] = show_info.get("aliases")
            if not result["info"].get("mpaa") and (mpaa := show_info.get("mpaa")):
                result["info"]["mpaa"] = mpaa
            if not result["info"].get("runtime") and show_info.get("runtime") is not None:
                result["info"]["runtime"] = show_info.get("runtime")
            from resources.lib.simkl.field_map import inherit_show_fields

            inherit_show_fields(result["info"], show_info)
            result["info"].update({f"tvshow.{key}": value for key, value in show_info.items() if key.endswith("_id")})

    @staticmethod
    def _add_season_show_cast(result, season_cast, show_cast):
        if season_cast and len(result.get("cast", [])) == 0:
            result["cast"] = season_cast
        if show_cast and len(result.get("cast", [])) == 0:
            result["cast"] = show_cast

    @staticmethod
    def _add_season_show_art(result, season_art, show_art):
        if show_art:
            result["art"].update({f"tvshow.{key}": value for key, value in show_art.items()})
        if season_art:
            result["art"].update(
                {f"season.{key}": value for key, value in season_art.items() if not key.startswith("tvshow.")}
            )

    @staticmethod
    def _show_season_art_fallback(data, season_art, show_art):
        show_season_art_mixin = {}

        if season_art:
            show_season_art_mixin = tools.smart_merge_dictionary(
                show_season_art_mixin,
                tools.filter_dictionary(season_art, "poster", "fanart", "clearlogo"),
                True,
            )

        if show_art:
            show_season_art_mixin = tools.smart_merge_dictionary(
                show_season_art_mixin,
                tools.filter_dictionary(show_art, "poster", "fanart", "clearlogo"),
                True,
            )

        data["art"] = tools.smart_merge_dictionary(data["art"], show_season_art_mixin, True)

    @staticmethod
    def _coalesce_simkl_object(db_object, simkl_data):
        """Ensure format/update paths always have a Simkl object (sync can mill before meta is cached)."""
        info = tools.safe_dict_get(simkl_data, "info") or {}
        simkl_id = info.get("simkl_id") or db_object.get("simkl_id")
        if simkl_id is None:
            return simkl_data or {}

        info.setdefault("simkl_id", simkl_id)
        if db_object.get("simkl_show_id") is not None:
            info.setdefault("simkl_show_id", db_object["simkl_show_id"])
        if db_object.get("simkl_season_id") is not None:
            info.setdefault("simkl_season_id", db_object["simkl_season_id"])
        if db_object.get("season") is not None:
            info.setdefault("season", db_object["season"])
        if db_object.get("episode") is not None:
            info.setdefault("episode", db_object["episode"])
            info.setdefault("number", db_object["episode"])
        if not info.get("mediatype"):
            if db_object.get("_entity") == "movie":
                info["mediatype"] = "movie"
            elif db_object.get("episode") is not None:
                info["mediatype"] = "episode"
            elif db_object.get("season") is not None or db_object.get("simkl_season_id") is not None:
                info["mediatype"] = "season"
            else:
                info["mediatype"] = "tvshow"

        coalesced = {
            "info": info,
            "art": tools.safe_dict_get(simkl_data, "art") or {},
            "cast": tools.safe_dict_get(simkl_data, "cast") or [],
        }
        return coalesced

    def _apply_best_fit_meta_data(self, simkl_data, tmdb_data, tvdb_data, fanart_object, art_profile=None):
        simkl_data = simkl_data or {}
        simkl_info = tools.safe_dict_get(simkl_data, "info") or {}
        media_type = simkl_info.get("mediatype") or "episode"
        if art_profile is None:
            from resources.lib.modules.artwork_profile import artwork_profile_for_row

            art_profile = artwork_profile_for_row(
                {"info": simkl_info, "simkl_id": simkl_info.get("simkl_id")},
                media_type if media_type in ("movie", "tvshow") else "tvshow",
            )
        result = {}

        self._apply_best_fit_info(result, simkl_data, tmdb_data, tvdb_data)
        self._apply_best_fit_cast(result, tmdb_data, tvdb_data)
        result["art"] = dict(tools.safe_dict_get(simkl_data, "art") or {})
        self._apply_best_fit_art(result, tmdb_data, tvdb_data, fanart_object, media_type, art_profile=art_profile)

        return result

    def _apply_best_fit_art(self, result, tmdb_object, tvdb_object, fanart_object, media_type, art_profile=None):
        """Simkl art is seeded on result before this runs; external sources gap-fill only."""
        if tmdb_object:
            result["art"] = tools.smart_merge_dictionary(
                result.get("art", {}), tmdb_object.get("art", {}), keep_original=True, extend_array=False
            )

        if tvdb_object:
            result["art"] = tools.smart_merge_dictionary(
                result.get("art", {}), tvdb_object.get("art", {}), keep_original=True, extend_array=False
            )

        if fanart_object:
            result["art"] = tools.smart_merge_dictionary(
                result.get("art", {}),
                fanart_object.get("art", {}),
                keep_original=not self._is_fanart_artwork_selected(media_type, art_profile=art_profile),
                extend_array=False,
            )

        result["art"] = self._handle_art(media_type, result.get("art", {}), art_profile=art_profile)

    def _apply_best_fit_info(
        self,
        result,
        simkl_data,
        tmdb_data,
        tvdb_data,
    ):
        # Simkl info is the base layer; external providers only fill missing keys.
        result.update({"info": tools.safe_dict_get(simkl_data, "info") or {}})
        mediatype = result["info"].get("mediatype")

        if mediatype in ("episode", "season"):
            self._apply_simkl_child_supplemental_info(result, tmdb_data, tvdb_data)
        else:
            if tmdb_data:
                result["info"] = tools.smart_merge_dictionary(
                    result["info"],
                    tools.safe_dict_get(tmdb_data, "info"),
                    keep_original=True,
                    extend_array=False,
                )

            if tvdb_data:
                result["info"] = tools.smart_merge_dictionary(
                    result["info"],
                    tools.safe_dict_get(tvdb_data, "info"),
                    keep_original=True,
                    extend_array=False,
                )

        self._apply_best_fit_release(result)
        self._use_simkl_air_date(simkl_data, result)
        self._normalize_genres(result)
        if mediatype not in ("episode", "season") and not result["info"].get("plot") and result["info"].get("overview"):
            result["info"]["plot"] = result["info"]["overview"]
        self._title_fallback(result)

    @staticmethod
    def _apply_simkl_child_supplemental_info(result, tmdb_data, tvdb_data):
        """Seasons/episodes: Simkl owns metadata; external APIs only gap-fill ids/ratings."""
        from resources.lib.simkl.field_map import merge_simkl_child_supplemental_info

        for source in (tmdb_data, tvdb_data):
            merge_simkl_child_supplemental_info(result["info"], tools.safe_dict_get(source, "info"))

    def _apply_best_fit_release(self, result):
        releases = tools.safe_dict_get(result, "info", "releases")
        if not releases:
            return

        us_release = self._get_best_release(releases.get("US"))
        country_release = self._get_best_release(releases.get(self.lang_region_code))

        if (
            self.lang_based_movie_releases
            and tools.parse_datetime(country_release.get("release_date", "9999-12-31T00:00:00"), date_only=False)
            > datetime.datetime.utcnow()
        ):
            lang_releases = [
                self._get_best_release(releases[c])
                for c in set(releases.keys())
                & get_country_set_for_language(self.lang_code) - {"US", self.lang_region_code}
            ]
            lang_releases.append(country_release)
            release = self._get_best_release(lang_releases, convert_to_utc=False)
        else:
            release = country_release

        if release_date := release.get("release_date", us_release.get("release_date")):
            result['info']["premiered"] = release_date
            result['info']["aired"] = release_date
        if mpaa := country_release.get("mpaa", us_release.get("mpaa")):
            result['info']['mpaa'] = mpaa

    @staticmethod
    def _get_best_release(releases, convert_to_utc=True):
        best_release = {}
        if releases:
            for release in releases:
                if (
                    release
                    and release.get("release_type", "unknown") not in {"premiere", "limited"}
                    and (
                        (not best_release and release.get("release_date"))
                        or release.get("release_date")
                        and release['release_date'] < best_release['release_date']
                    )
                ):
                    best_release = release
            if convert_to_utc and best_release:
                best_release['release_date'] = g.local_to_utc_by_country(
                    best_release['release_date'], best_release['country']
                )
        return best_release

    @staticmethod
    def _use_simkl_air_date(simkl_data, result):
        if result['info']['mediatype'] == g.MEDIA_MOVIE:
            return
        if simkl_premiered_date := tools.safe_dict_get(simkl_data, "info", "premiered"):
            result['info']['premiered'] = simkl_premiered_date

        if simkl_aired_date := tools.safe_dict_get(simkl_data, "info", "aired"):
            result['info']['aired'] = simkl_aired_date

    def _normalize_genres(self, meta):
        meta["info"]["genre"] = sorted(
            OrderedDict.fromkeys(
                [self.genres.get(i.lower().replace(" ", "-"), i) for i in meta["info"].get("genre", [])]
            )
        )

    @staticmethod
    def _title_fallback(meta):
        if not meta["info"].get('title'):
            media_type = meta["info"]["mediatype"]
            title = None
            if media_type == "episode":
                title = g.get_language_string(30529).format(meta["info"]["episode"])
            elif media_type == "season":
                if meta["info"]["season"] == 0:
                    title = "Specials"
                else:
                    title = g.get_language_string(30528).format(meta["info"]["season"])
            if title:
                meta["info"]["sorttitle"] = title
                meta["info"]["title"] = title

    def _apply_best_fit_cast(self, result, tmdb_data, tvdb_data):
        if tools.safe_dict_get(result, "info", "mediatype") in ("episode", "season"):
            return
        if tmdb_data is not None and tmdb_data.get("cast", []):
            result["cast"] = tmdb_data.get("cast", [])
        elif tvdb_data is not None and tvdb_data.get("cast", []):
            result["cast"] = tvdb_data.get("cast", [])

    def _effective_preferred_art_source(self, media_type: str, art_profile: str | None = None) -> int:
        from resources.lib.modules.artwork_profile import PROFILE_ANIME_MOVIE, PROFILE_ANIME_SERIES
        from resources.lib.modules.metadata_providers import effective_preferred_art_source

        if art_profile in (PROFILE_ANIME_MOVIE, PROFILE_ANIME_SERIES):
            raw = g.get_int_setting("anime.preferedsource", 1)
        elif media_type == "movie":
            raw = g.get_int_setting("movies.preferedsource", 1)
        else:
            raw = g.get_int_setting("tvshows.preferedsource", 1)
        return effective_preferred_art_source(raw)

    def _is_fanart_artwork_selected(self, media_type, art_profile=None):
        from resources.lib.modules.metadata_providers import ART_FANART

        return self._effective_preferred_art_source(media_type, art_profile=art_profile) == ART_FANART

    def _is_tmdb_artwork_selected(self, media_type, art_profile=None):
        from resources.lib.modules.metadata_providers import ART_TMDB

        return self._effective_preferred_art_source(media_type, art_profile=art_profile) == ART_TMDB

    def _is_tvdb_artwork_selected(self, media_type, art_profile=None):
        from resources.lib.modules.metadata_providers import ART_TVDB

        return self._effective_preferred_art_source(media_type, art_profile=art_profile) == ART_TVDB

    def _handle_art(self, media_type, art_data, art_profile=None):
        if art_data is None:
            return {}
        [
            art_data.update({k: self._sort_art(self._filter_art(v))})
            for k, v in art_data.items()
            if isinstance(v, (list, set))
        ]

        self._fallback_art_before_handling(art_data)

        from resources.lib.modules.artwork_profile import PROFILE_ANIME_MOVIE, PROFILE_ANIME_SERIES

        profile = art_profile or media_type
        if profile == PROFILE_ANIME_MOVIE:
            return self._handle_anime_movie_art(art_data)
        if profile == PROFILE_ANIME_SERIES:
            return self._handle_anime_series_art(art_data)
        if media_type == "movie":
            return self._handle_movie_art(art_data)
        elif media_type == "tvshow":
            return self._handle_show_art(art_data)
        elif media_type == "season":
            return self._handle_season_art(art_data, art_profile=art_profile)
        elif media_type == "episode":
            return self._handle_episode_art(art_data, art_profile=art_profile)

    @staticmethod
    def _sort_art(art):
        art.sort(key=lambda i: i.get("url", ""))
        art.sort(key=lambda i: i.get("rating", 0), reverse=True)
        art.sort(key=lambda i: i.get("size", 0), reverse=True)
        return art

    def _filter_art(self, art):
        return [
            i
            for i in art
            if isinstance(i, dict) and i.get("language") in self.allowed_artwork_languages
        ]

    @staticmethod
    def _fallback_art_before_handling(art):
        if len(art.get("poster", [])) == 0 and len(art.get("keyart", [])) > 0:
            art.update({"poster": art.pop("keyart")})

    @staticmethod
    def _handle_artwork_multis(limit, art_type, art_data):
        if limit <= 0:
            return {}
        data = {}
        raw = art_data.get(art_type)
        if raw is None:
            return data
        if isinstance(raw, list):
            images = raw
        elif isinstance(raw, dict):
            images = [raw]
        elif isinstance(raw, str):
            images = [raw]
        else:
            return data
        for idx in range(limit):
            name = art_type if idx == 0 else f"{art_type}{idx}"
            if idx >= len(images):
                break
            image = images[idx]
            if isinstance(image, dict):
                data[name] = image["url"]
            else:
                data[name] = image
        return data

    def _handle_show_art(self, data):
        from resources.lib.modules.metadata_providers import art_limit, art_option_enabled

        result = {}

        result.update(self._handle_artwork_multis(art_limit("tvshows.poster_limit", "tvshow"), "poster", data))
        result.update(self._handle_artwork_multis(art_limit("tvshows.fanart_limit", "tvshow"), "fanart", data))
        result.update(self._handle_artwork_multis(art_limit("tvshows.characterart_limit", "tvshow"), "characterart", data))
        result.update(self._handle_artwork_multis(art_limit("tvshows.keyart_limit", "tvshow"), "keyart", data))
        if art_option_enabled("tvshows.clearlogo", "tvshow"):
            result.update(self._handle_artwork_multis(1, "clearlogo", data))
        result.update(self._handle_artwork_multis(1, "thumb", data))
        result.update(self._handle_artwork_multis(1, "icon", data))

        if art_option_enabled("tvshows.banner", "tvshow"):
            result.update(self._handle_artwork_multis(1, "banner", data))
        if art_option_enabled("tvshows.landscape", "tvshow"):
            result.update(self._handle_artwork_multis(1, "landscape", data))
        if art_option_enabled("tvshows.clearart", "tvshow"):
            result.update(self._handle_artwork_multis(1, "clearart", data))

        return result

    def _handle_movie_art(self, data):
        from resources.lib.modules.metadata_providers import art_limit, art_option_enabled

        result = {}

        result.update(self._handle_artwork_multis(art_limit("movies.poster_limit", "movie"), "poster", data))
        result.update(self._handle_artwork_multis(art_limit("movies.fanart_limit", "movie"), "fanart", data))
        result.update(self._handle_artwork_multis(art_limit("movies.characterart_limit", "movie"), "characterart", data))
        result.update(self._handle_artwork_multis(art_limit("movies.keyart_limit", "movie"), "keyart", data))
        if art_option_enabled("movies.clearlogo", "movie"):
            result.update(self._handle_artwork_multis(1, "clearlogo", data))
        result.update(self._handle_artwork_multis(1, "thumb", data))
        result.update(self._handle_artwork_multis(1, "icon", data))

        if art_option_enabled("movies.banner", "movie"):
            result.update(self._handle_artwork_multis(1, "banner", data))
        if art_option_enabled("movies.landscape", "movie"):
            result.update(self._handle_artwork_multis(1, "landscape", data))
        if art_option_enabled("movies.discart", "movie"):
            result.update(self._handle_artwork_multis(1, "discart", data))
        if art_option_enabled("movies.clearart", "movie"):
            result.update(self._handle_artwork_multis(1, "clearart", data))

        return result

    def _handle_anime_series_art(self, data):
        from resources.lib.modules.metadata_providers import art_limit, art_option_enabled

        result = {}

        result.update(self._handle_artwork_multis(art_limit("anime.poster_limit", "anime"), "poster", data))
        result.update(self._handle_artwork_multis(art_limit("anime.fanart_limit", "anime"), "fanart", data))
        result.update(self._handle_artwork_multis(art_limit("anime.characterart_limit", "anime"), "characterart", data))
        result.update(self._handle_artwork_multis(art_limit("anime.keyart_limit", "anime"), "keyart", data))
        if art_option_enabled("anime.clearlogo", "anime_series"):
            result.update(self._handle_artwork_multis(1, "clearlogo", data))
        result.update(self._handle_artwork_multis(1, "thumb", data))
        result.update(self._handle_artwork_multis(1, "icon", data))

        if art_option_enabled("anime.banner", "anime_series"):
            result.update(self._handle_artwork_multis(1, "banner", data))
        if art_option_enabled("anime.landscape", "anime_series"):
            result.update(self._handle_artwork_multis(1, "landscape", data))
        if art_option_enabled("anime.clearart", "anime_series"):
            result.update(self._handle_artwork_multis(1, "clearart", data))

        return result

    def _handle_anime_movie_art(self, data):
        from resources.lib.modules.metadata_providers import art_option_enabled

        result = self._handle_anime_series_art(data)
        if art_option_enabled("anime.discart", "anime_movie"):
            result.update(self._handle_artwork_multis(1, "discart", data))
        return result

    def _handle_season_art(self, data, art_profile=None):
        from resources.lib.modules.artwork_profile import PROFILE_ANIME_MOVIE, PROFILE_ANIME_SERIES
        from resources.lib.modules.metadata_providers import art_limit, art_option_enabled

        is_anime = art_profile in (PROFILE_ANIME_SERIES, PROFILE_ANIME_MOVIE)
        result = {}
        result.update(self._handle_artwork_multis(1, "thumb", data))
        result.update(self._handle_artwork_multis(1, "icon", data))
        if is_anime:
            if art_option_enabled("anime.season.poster", "anime_series"):
                result.update(self._handle_artwork_multis(art_limit("anime.poster_limit", "anime"), "poster", data))
            if art_option_enabled("anime.season.fanart", "anime_series"):
                result.update(self._handle_artwork_multis(art_limit("anime.fanart_limit", "anime"), "fanart", data))
            if art_option_enabled("anime.season.banner", "anime_series"):
                result.update(self._handle_artwork_multis(1, "banner", data))
            if art_option_enabled("anime.season.landscape", "anime_series"):
                result.update(self._handle_artwork_multis(1, "landscape", data))
        else:
            if g.get_bool_setting("season.poster", True):
                result.update(self._handle_artwork_multis(art_limit("tvshows.poster_limit", "tvshow"), "poster", data))
            if g.get_bool_setting("season.fanart", True):
                result.update(self._handle_artwork_multis(art_limit("tvshows.fanart_limit", "tvshow"), "fanart", data))
            if g.get_bool_setting("season.banner", True):
                result.update(self._handle_artwork_multis(1, "banner", data))
            if g.get_bool_setting("season.landscape", True):
                result.update(self._handle_artwork_multis(1, "landscape", data))
        return result

    def _handle_episode_art(self, data, art_profile=None):
        from resources.lib.modules.artwork_profile import PROFILE_ANIME_MOVIE, PROFILE_ANIME_SERIES
        from resources.lib.modules.metadata_providers import art_limit, art_option_enabled

        is_anime = art_profile in (PROFILE_ANIME_SERIES, PROFILE_ANIME_MOVIE)
        result = {}
        result.update(self._handle_artwork_multis(1, "thumb", data))
        if is_anime:
            if art_option_enabled("anime.episode.fanart", "anime_series"):
                result.update(self._handle_artwork_multis(art_limit("anime.fanart_limit", "anime"), "fanart", data))
        elif g.get_bool_setting("episode.fanart", True):
            result.update(self._handle_artwork_multis(art_limit("tvshows.fanart_limit", "tvshow"), "fanart", data))
        return result

    # endregion

    # region update meta
    def update(self, db_object):
        """Checks and updates the requested db_object with the full set of meta data.

        :param db_object:dictionary with the ids and meta from the db.
        :type db_object:dict
        :return:list with the updated db_object
        :rtype:list[dict]
        """
        media_type = MetadataHandler.get_simkl_info(db_object, "mediatype")

        if media_type == "movie":
            self._update_movie(db_object)
        if media_type == "tvshow":
            self._update_tvshow(db_object)
        if media_type == "season":
            self._update_season(db_object)
        if media_type == "episode":
            self._update_episode(db_object)

        self._write_log(db_object, media_type)

        return [db_object]

    def _write_log(self, db_object, media_type):
        if (media_type == "movie" and not db_object.get("tmdb_object") and not db_object.get("tvdb_object")) or (
            media_type in ["tvshow", "season", "episode"]
            and not db_object.get("tmdb_object")
            and not db_object.get("tvdb_object")
        ):
            g.log(f"Unable to lookup some meta for {db_object.get('simkl_id')}", "debug")
        if self.fanarttv_api.fanart_support and media_type != "episode" and not db_object.get("fanart_object"):
            g.log(f"Unable to lookup fanart meta for {db_object.get('simkl_id')}", "debug")

    # region movie
    def _update_movie(self, db_object):
        self._update_movie_simkl(db_object)
        self._update_movie_tmdb(db_object)
        self._update_movie_tvdb(db_object)
        self._update_movie_fanart(db_object)
        self._update_movie_fallback(db_object)
        self._update_movie_ratings(db_object)
        self._update_movie_cast(db_object)

    def _update_movie_simkl(self, db_object):
        return  # Prism: Simkl API removed — metadata from Simkl/MDBList/TMDB/TVDB

    def _update_movie_tmdb(self, db_object):
        if not self._provider_enabled("tmdb"):
            return
        if not self._tmdb_id_valid(db_object):
            return
        if not (self._tmdb_needs_update(db_object) or self._force_update(db_object)):
            return
        tools.smart_merge_dictionary(db_object, self.tmdb_api.get_movie(db_object["tmdb_id"]))

    def _update_movie_tvdb(self, db_object):
        if not self._provider_enabled("tvdb"):
            return
        if not self._tvdb_id_valid(db_object):
            return
        if not (self._tvdb_needs_update(db_object) or self._force_update(db_object)):
            return
        tools.smart_merge_dictionary(db_object, self.tvdb_api.get_movie(db_object["tvdb_id"]))

    def _update_movie_fanart(self, db_object):
        if not self._provider_enabled("fanart"):
            return
        if self.fanarttv_api.fanart_support and (self._fanart_needs_update(db_object) or self._force_update(db_object)):
            if self._tmdb_id_valid(db_object):
                tools.smart_merge_dictionary(db_object, self.fanarttv_api.get_movie(db_object.get("tmdb_id")))
            if self._imdb_id_valid(db_object) and self._fanart_needs_update(db_object):
                tools.smart_merge_dictionary(db_object, self.fanarttv_api.get_movie(db_object.get("imdb_id")))

    def _update_movie_fallback(self, db_object):
        if self._provider_enabled("tmdb") and self._tmdb_id_valid(db_object) and not self._tmdb_art_meta_up_to_par("movie", db_object):
            tools.smart_merge_dictionary(db_object, self.tmdb_api.get_movie_art(db_object["tmdb_id"]))
        if self._provider_enabled("tvdb") and self._tvdb_id_valid(db_object) and not self._tvdb_art_meta_up_to_par("movie", db_object):
            tools.smart_merge_dictionary(db_object, self.tvdb_api.get_movie_art(db_object["tvdb_id"]))

    def _update_movie_ratings(self, db_object):
        if self._provider_enabled("tmdb") and self._tmdb_id_valid(db_object):
            tools.smart_merge_dictionary(db_object, self.tmdb_api.get_movie_rating(db_object["tmdb_id"]))

    def _update_movie_cast(self, db_object):
        if self._provider_enabled("tmdb") and self._tmdb_id_valid(db_object):
            tools.smart_merge_dictionary(db_object, self.tmdb_api.get_movie_cast(db_object["tmdb_id"]))

    # endregion

    # region tvshow
    def _update_tvshow(self, db_object):
        self._update_tvshow_simkl(db_object)
        self._update_tvshow_tmdb(db_object)
        self._update_tvshow_tvdb(db_object)
        self._update_tvshow_fanart(db_object)
        self._update_tvshow_fallback(db_object)
        # self._update_tvshow_rating(db_object)  # Commenting for now to reduce tvdb calls
        self._update_tvshow_cast(db_object)

    def _update_tvshow_simkl(self, db_object):
        return  # Prism: Simkl API removed — metadata from Simkl/MDBList/TMDB/TVDB

    def _update_tvshow_tmdb(self, db_object):
        if not self._provider_enabled("tmdb"):
            return
        if not self._tmdb_id_valid(db_object):
            return
        if not (self._tmdb_needs_update(db_object) or self._force_update(db_object)):
            return
        tools.smart_merge_dictionary(db_object, self.tmdb_api.get_show(db_object["tmdb_id"]))

    def _update_tvshow_tvdb(self, db_object):
        if not self._provider_enabled("tvdb"):
            return
        if not self._tvdb_id_valid(db_object):
            return
        if not (self._tvdb_needs_update(db_object) or self._force_update(db_object)):
            return
        tools.smart_merge_dictionary(db_object, self.tvdb_api.get_show(db_object["tvdb_id"]))

    def _update_tvshow_fanart(self, db_object):
        if not self._provider_enabled("fanart"):
            return
        if (
            self.fanarttv_api.fanart_support
            and (self._fanart_needs_update(db_object) or self._force_update(db_object))
            and self._tvdb_id_valid(db_object)
        ):
            tools.smart_merge_dictionary(db_object, self.fanarttv_api.get_show(db_object.get("tvdb_id")))

    def _update_tvshow_fallback(self, db_object):
        if self._provider_enabled("tmdb") and self._tmdb_id_valid(db_object) and not self._tmdb_art_meta_up_to_par("tvshow", db_object):
            tools.smart_merge_dictionary(db_object, self.tmdb_api.get_show_art(db_object["tmdb_id"]))
        if self._provider_enabled("tvdb") and self._tvdb_id_valid(db_object) and not self._tvdb_art_meta_up_to_par("tvshow", db_object):
            tools.smart_merge_dictionary(db_object, self.tvdb_api.get_show_art(db_object["tvdb_id"]))

    def _update_tvshow_rating(self, db_object):
        if self._provider_enabled("tmdb") and not tools.safe_dict_get(db_object, "tmdb_object", "info") and self._tmdb_id_valid(db_object):
            tools.smart_merge_dictionary(db_object, self.tmdb_api.get_show_rating(db_object["tmdb_id"]))
        if self._provider_enabled("tvdb") and not tools.safe_dict_get(db_object, "tvdb_object", "info") and self._tvdb_id_valid(db_object):
            tools.smart_merge_dictionary(db_object, self.tvdb_api.get_show_rating(db_object["tvdb_id"]))

    def _update_tvshow_cast(self, db_object):
        if self._provider_enabled("tmdb") and not tools.safe_dict_get(db_object, "tmdb_object", "cast") and self._tmdb_id_valid(db_object):
            tools.smart_merge_dictionary(db_object, self.tmdb_api.get_show_cast(db_object["tmdb_id"]))
        if (
            self._provider_enabled("tvdb")
            and not tools.safe_dict_get(db_object, "tvdb_object", "cast")
            and not tools.safe_dict_get(db_object, "tmdb_object", "cast")
            and self._tvdb_id_valid(db_object)
        ):
            tools.smart_merge_dictionary(db_object, self.tvdb_api.get_show_cast(db_object["tvdb_id"]))

    # endregion

    # region season
    def _merge_season_external(self, db_object, external):
        from resources.lib.simkl.field_map import season_external_patch

        patch = season_external_patch(external)
        if patch:
            tools.smart_merge_dictionary(db_object, patch)

    def _simkl_season_lookup(self, db_object):
        return tools.safe_dict_get(db_object, "simkl_object", "info", "season")

    def _update_season(self, db_object):
        """Simkl owns season metadata — external APIs only supply artwork."""
        self._update_season_tmdb(db_object)
        self._update_season_tvdb(db_object)
        self._update_season_fanart(db_object)
        self._update_season_fallback(db_object)

    def _update_season_tmdb(self, db_object):
        if not self._provider_enabled("tmdb"):
            return
        if not self._tmdb_show_id_valid(db_object):
            return
        season_num = self._simkl_season_lookup(db_object)
        if season_num is None:
            return
        needs_refresh = self._tmdb_needs_update(db_object) or self._force_update(db_object)
        if needs_refresh or not self._tmdb_art_meta_up_to_par("season", db_object):
            self._merge_season_external(
                db_object,
                self.tmdb_api.get_season_art(db_object["tmdb_show_id"], season_num),
            )

    def _update_season_tvdb(self, db_object):
        if not self._provider_enabled("tvdb"):
            return
        if not self._tvdb_show_id_valid(db_object):
            return
        season_num = self._simkl_season_lookup(db_object)
        if season_num is None:
            return
        needs_refresh = self._tvdb_needs_update(db_object) or self._force_update(db_object)
        if needs_refresh or not self._tvdb_art_meta_up_to_par("season", db_object):
            self._merge_season_external(
                db_object,
                self.tvdb_api.get_season_art(db_object["tvdb_show_id"], season_num),
            )

    def _update_season_fanart(self, db_object):
        if not self._provider_enabled("fanart"):
            return
        if (
            self.fanarttv_api.fanart_support
            and (self._fanart_needs_update(db_object) or self._force_update(db_object))
            and self._tvdb_show_id_valid(db_object)
        ):
            tools.smart_merge_dictionary(
                db_object,
                self.fanarttv_api.get_season(
                    db_object.get("tvdb_show_id"),
                    tools.safe_dict_get(db_object, "simkl_object", "info", "season"),
                ),
            )

    def _update_season_fallback(self, db_object):
        season_num = self._simkl_season_lookup(db_object)
        if season_num is None:
            return
        if (
            self._provider_enabled("tmdb")
            and self._tmdb_show_id_valid(db_object)
            and not self._tmdb_art_meta_up_to_par("season", db_object)
            and g.get_int_setting("tvshows.preferedsource", 1) != ART_TMDB
        ):
            self._merge_season_external(
                db_object,
                self.tmdb_api.get_season_art(db_object["tmdb_show_id"], season_num),
            )
        if (
            self._provider_enabled("tvdb")
            and self._tvdb_show_id_valid(db_object)
            and not self._tvdb_art_meta_up_to_par("season", db_object)
            and g.get_int_setting("tvshows.preferedsource", 1) != ART_TVDB
        ):
            self._merge_season_external(
                db_object,
                self.tvdb_api.get_season_art(db_object["tvdb_show_id"], season_num),
            )

    # endregion

    # region episode
    def _merge_episode_external(self, db_object, external):
        from resources.lib.simkl.field_map import episode_external_patch

        patch = episode_external_patch(external)
        if patch:
            tools.smart_merge_dictionary(db_object, patch)

    def _update_episode(self, db_object):
        """Simkl owns episode metadata — external APIs only supply art and supplemental ids."""
        self._update_episode_tmdb(db_object)
        self._update_episode_tvdb(db_object)
        self._update_episode_fallback(db_object)

    def _update_episode_tmdb(self, db_object):
        if not self._provider_enabled("tmdb"):
            return
        if not self._tmdb_show_id_valid(db_object):
            return
        season_num, episode_num = self._simkl_episode_lookup(db_object)
        if episode_num is None:
            return
        needs_refresh = self._tmdb_needs_update(db_object) or self._force_update(db_object)
        if needs_refresh or not self._tmdb_art_meta_up_to_par("episode", db_object):
            self._merge_episode_external(
                db_object,
                self.tmdb_api.get_episode_art(db_object["tmdb_show_id"], season_num, episode_num),
            )
        if needs_refresh:
            self._merge_episode_external(
                db_object,
                self.tmdb_api.get_episode_rating(db_object["tmdb_show_id"], season_num, episode_num),
            )

    def _update_episode_tvdb(self, db_object):
        if not self._provider_enabled("tvdb"):
            return
        if not self._tvdb_show_id_valid(db_object):
            return
        season_num, episode_num = self._simkl_episode_lookup(db_object)
        if episode_num is None:
            return
        needs_refresh = self._tvdb_needs_update(db_object) or self._force_update(db_object)
        if needs_refresh:
            self._merge_episode_external(
                db_object,
                self.tvdb_api.get_episode_rating(db_object["tvdb_show_id"], season_num, episode_num),
            )
        if needs_refresh or not self._tvdb_art_meta_up_to_par("episode", db_object):
            self._merge_episode_external(
                db_object,
                self.tvdb_api.get_episode(db_object["tvdb_show_id"], season_num, episode_num),
            )

    def _update_episode_fallback(self, db_object):
        season_num, episode_num = self._simkl_episode_lookup(db_object)
        if episode_num is None:
            return
        if (
            self._provider_enabled("tmdb")
            and self._tmdb_show_id_valid(db_object)
            and not self._tmdb_art_meta_up_to_par("episode", db_object)
            and g.get_int_setting("tvshows.preferedsource", 1) != ART_TMDB
        ):
            self._merge_episode_external(
                db_object,
                self.tmdb_api.get_episode_art(db_object["tmdb_show_id"], season_num, episode_num),
            )
        if (
            self._provider_enabled("tvdb")
            and self._tvdb_show_id_valid(db_object)
            and not self._tvdb_art_meta_up_to_par("episode", db_object)
            and g.get_int_setting("tvshows.preferedsource", 1) != ART_TVDB
        ):
            self._merge_episode_external(
                db_object,
                self.tvdb_api.get_episode(db_object["tvdb_show_id"], season_num, episode_num),
            )

    def _update_episode_rating(self, db_object):
        season_num, episode_num = self._simkl_episode_lookup(db_object)
        if episode_num is None:
            return
        if self._provider_enabled("tmdb") and self._tmdb_show_id_valid(db_object):
            self._merge_episode_external(
                db_object,
                self.tmdb_api.get_episode_rating(db_object["tmdb_show_id"], season_num, episode_num),
            )
        if self._provider_enabled("tvdb") and self._tvdb_show_id_valid(db_object):
            self._merge_episode_external(
                db_object,
                self.tvdb_api.get_episode_rating(db_object["tvdb_show_id"], season_num, episode_num),
            )

    # endregion

    # endregion

    # region needs_update
    def _tmdb_needs_update(self, db_object):
        return not db_object.get("tmdb_object") or (
            db_object.get("tmdb_meta_hash") and db_object.get("tmdb_meta_hash") != self.tmdb_api.meta_hash
        )

    def _tvdb_needs_update(self, db_object):
        return not db_object.get("tvdb_object") or (
            db_object.get("tvdb_meta_hash") and db_object.get("tvdb_meta_hash") != self.tvdb_api.meta_hash
        )

    def _fanart_needs_update(self, db_object):
        return not db_object.get("fanart_object") or (
            db_object.get("fanart_meta_hash") and db_object.get("fanart_meta_hash") != self.fanarttv_api.meta_hash
        )

    # endregion

    # region is_valid

    @staticmethod
    def _tvdb_id_valid(db_object):
        return db_object.get("tvdb_id") is not None

    def _tvdb_show_id_valid(self, db_object):
        return db_object.get("tvdb_show_id") is not None and self._tvdb_id_valid(db_object)

    @staticmethod
    def _tmdb_id_valid(db_object):
        return db_object.get("tmdb_id") is not None

    def _tmdb_show_id_valid(self, db_object):
        return db_object.get("tmdb_show_id") is not None and self._tmdb_id_valid(db_object)

    @staticmethod
    def _imdb_id_valid(db_object):
        return db_object.get("imdb_id") is not None

    # region fast-menu meta merge (cache-first, online gap-fill)
    @staticmethod
    def _art_key_present(art: dict, art_key: str) -> bool:
        if art.get(art_key):
            return True
        prefix = f"{art_key}"
        return any(key.startswith(prefix) and art.get(key) for key in art)

    def _db_object_for_row(self, row: dict, media_type: str) -> dict:
        from resources.lib.modules.metadata_providers import external_ids_from_row
        from resources.lib.simkl.ids import canonicalize_info_identity

        info = dict(row.get("info") or {})
        canonicalize_info_identity(info)
        ids = external_ids_from_row(row)
        for key, value in ids.items():
            if value is not None and info.get(key) is None:
                info[key] = value
        simkl_id = row.get("simkl_id") or info.get("simkl_id")
        db_object = {
            "simkl_id": simkl_id,
            "info": info,
            "tmdb_id": ids.get("tmdb_id"),
            "tvdb_id": ids.get("tvdb_id"),
            "imdb_id": ids.get("imdb_id"),
            "cast": row.get("cast") or [],
            "simkl_object": {
                "info": info,
                "art": dict(row.get("art") or {}),
                "cast": row.get("cast") or [],
            },
        }
        if media_type == "movie":
            info.setdefault("mediatype", "movie")
        else:
            info.setdefault("mediatype", "tvshow")
        return db_object

    @staticmethod
    def _can_fetch_provider_meta(row: dict) -> bool:
        from resources.lib.modules.metadata_providers import gapfill_provider_available_for_row

        return gapfill_provider_available_for_row(row)

    @staticmethod
    def _provider_enabled(provider: str) -> bool:
        from resources.lib.modules.metadata_providers import provider_enabled

        return provider_enabled(provider)

    @staticmethod
    def _cast_has_photos(cast: list) -> bool:
        for member in cast:
            if not isinstance(member, dict):
                continue
            if (
                member.get("thumbnail")
                or member.get("thumb")
                or member.get("profile")
                or member.get("profile_path")
            ):
                return True
        return False

    @staticmethod
    def _row_needs_refresh(row: dict, media_type: str) -> bool:
        from resources.lib.database.sync_meta_cache import row_needs_refresh

        normalized = "movie" if media_type == "movie" else "show"
        return row_needs_refresh(normalized, row)

    def _row_meta_gaps(self, row: dict, media_type: str, art_profile: str | None = None) -> list[str]:
        from resources.lib.modules.artwork_profile import (
            PROFILE_ANIME_MOVIE,
            PROFILE_ANIME_SERIES,
            PROFILE_MOVIE,
            artwork_profile_for_row,
        )
        from resources.lib.modules.metadata_providers import art_gapfill_available, art_option_enabled, cast_gapfill_available

        if art_profile is None:
            art_profile = artwork_profile_for_row(row, default_media_type=media_type)
        provider_type = "movie" if art_profile in (PROFILE_ANIME_MOVIE, PROFILE_MOVIE) else "tvshow"

        gaps: list[str] = []
        cast = row.get("cast")
        if cast_gapfill_available(row, provider_type) and (
            not cast
            or not isinstance(cast, list)
            or len(cast) == 0
            or not self._cast_has_photos(cast)
        ):
            gaps.append("cast")
        art = row.get("art") if isinstance(row.get("art"), dict) else {}
        online_art_keys = []
        if art_profile == PROFILE_ANIME_MOVIE:
            if art_option_enabled("anime.clearlogo", "anime_movie"):
                online_art_keys.append("clearlogo")
            if art_option_enabled("anime.clearart", "anime_movie"):
                online_art_keys.append("clearart")
            if art_option_enabled("anime.discart", "anime_movie"):
                online_art_keys.append("discart")
            if art_option_enabled("anime.banner", "anime_movie"):
                online_art_keys.append("banner")
            if art_option_enabled("anime.landscape", "anime_movie"):
                online_art_keys.append("landscape")
        elif art_profile == PROFILE_ANIME_SERIES:
            if art_option_enabled("anime.clearlogo", "anime_series"):
                online_art_keys.append("clearlogo")
            if art_option_enabled("anime.clearart", "anime_series"):
                online_art_keys.append("clearart")
            if art_option_enabled("anime.banner", "anime_series"):
                online_art_keys.append("banner")
            if art_option_enabled("anime.landscape", "anime_series"):
                online_art_keys.append("landscape")
        elif media_type == "movie":
            if art_option_enabled("movies.clearlogo", "movie"):
                online_art_keys.append("clearlogo")
            if art_option_enabled("movies.clearart", "movie"):
                online_art_keys.append("clearart")
            if art_option_enabled("movies.discart", "movie"):
                online_art_keys.append("discart")
            if art_option_enabled("movies.banner", "movie"):
                online_art_keys.append("banner")
            if art_option_enabled("movies.landscape", "movie"):
                online_art_keys.append("landscape")
        elif media_type in ("tvshow", "show"):
            if art_option_enabled("tvshows.clearlogo", "tvshow"):
                online_art_keys.append("clearlogo")
            if art_option_enabled("tvshows.clearart", "tvshow"):
                online_art_keys.append("clearart")
            if art_option_enabled("tvshows.banner", "tvshow"):
                online_art_keys.append("banner")
            if art_option_enabled("tvshows.landscape", "tvshow"):
                online_art_keys.append("landscape")
        for art_key in online_art_keys:
            if art_gapfill_available(row) and not self._art_key_present(art, art_key):
                gaps.append(art_key)
        return gaps

    def merge_row_from_cache(
        self,
        row: dict,
        media_type: str,
        *,
        db=None,
        art_profile: str | None = None,
        provider_cache: dict | None = None,
    ) -> dict:
        """Merge full art, cast, and info from cached provider meta — no API calls."""
        if not isinstance(row, dict):
            return row

        from resources.lib.modules.artwork_profile import artwork_profile_for_row, provider_media_type
        from resources.lib.simkl.ids import canonicalize_info_identity, entity_simkl_id

        info = row.get("info") or {}
        if isinstance(info, dict):
            canonicalize_info_identity(info)

        if art_profile is None:
            art_profile = artwork_profile_for_row(row, default_media_type=media_type)
        provider_type = provider_media_type(art_profile)

        simkl_id = entity_simkl_id({"info": info, "simkl_id": row.get("simkl_id")}) or row.get("simkl_id") or info.get("simkl_id")
        if not simkl_id:
            return row

        if db is None:
            from resources.lib.database.simkl_sync.database import SimklSyncDatabase

            db = SimklSyncDatabase()

        table = "movies" if provider_type == "movie" else "shows"
        db_object = self._db_object_for_row(row, provider_type)
        db_object["_art_profile"] = art_profile
        cached_meta = (provider_cache or {}).get(int(simkl_id))
        if cached_meta is None:
            cached_meta = db.load_cached_provider_meta(table, int(simkl_id), info)
        db_object.update(cached_meta)
        if not any(
            db_object.get(f"{provider}_object")
            for provider in ("simkl", "tmdb", "tvdb", "fanart")
        ):
            return row

        formatted = self.format_meta(db_object)
        merged = dict(row)
        merged["info"] = tools.smart_merge_dictionary(
            dict(info),
            formatted.get("info") or {},
            keep_original=True,
            extend_array=False,
        )
        merged["art"] = tools.smart_merge_dictionary(
            dict(row.get("art") or {}),
            formatted.get("art") or {},
            keep_original=True,
            extend_array=False,
        )
        if formatted.get("cast"):
            merged["cast"] = formatted["cast"]
        return merged

    def _collect_enrichment_ref(
        self,
        row: dict,
        media_type: str,
        *,
        meta_cache,
        art_profile: str | None = None,
    ) -> dict | None:
        from resources.lib.modules.artwork_profile import artwork_profile_for_row, provider_media_type
        from resources.lib.simkl.ids import entity_simkl_id

        if art_profile is None:
            art_profile = artwork_profile_for_row(row, default_media_type=media_type)
        provider_type = provider_media_type(art_profile)
        cache_media_type = "movie" if provider_type == "movie" else "show"
        gaps = self._row_meta_gaps(row, provider_type, art_profile=art_profile)
        stale = self._row_needs_refresh(row, provider_type)
        simkl_id = entity_simkl_id(row) or row.get("simkl_id")
        if simkl_id is None:
            return None
        if stale:
            meta_cache.delete_row(cache_media_type, int(simkl_id))
        actionable_gaps = [
            gap
            for gap in gaps
            if not meta_cache.is_gap_miss(cache_media_type, int(simkl_id), gap)
        ]
        if not ((actionable_gaps or stale) and self._can_fetch_provider_meta(row)):
            return None
        return {
            "simkl_id": int(simkl_id),
            "needs_update": True,
            "_gapfill_gaps": list(actionable_gaps),
            "_provider_type": provider_type,
        }

    def merge_list_meta_local(self, rows, media_type: str, *, db=None) -> tuple[list, list[dict]]:
        """Merge cached provider meta for list paint — no HTTP, no DB writes."""
        import time

        if not rows:
            return rows, []

        if db is None:
            from resources.lib.database.simkl_sync.database import SimklSyncDatabase

            db = SimklSyncDatabase()

        start = time.time()
        merged: list = []
        enrichment_refs: list[dict] = []
        from resources.lib.database.sync_meta_cache import SyncMetaCache
        from resources.lib.modules.artwork_profile import artwork_profile_for_row, provider_media_type

        meta_cache = SyncMetaCache()
        movie_rows: list[dict] = []
        show_rows: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            profile = artwork_profile_for_row(row, default_media_type=media_type)
            if provider_media_type(profile) == "movie":
                movie_rows.append(row)
            else:
                show_rows.append(row)

        provider_cache: dict[int, dict] = {}
        if movie_rows:
            provider_cache.update(db.load_cached_provider_meta_batch("movies", movie_rows))
        if show_rows:
            provider_cache.update(db.load_cached_provider_meta_batch("shows", show_rows))

        for row in rows:
            if not isinstance(row, dict):
                merged.append(row)
                continue
            info = row.get("info")
            if isinstance(info, dict):
                from resources.lib.simkl.ids import canonicalize_info_identity

                canonicalize_info_identity(info)
            profile = artwork_profile_for_row(row, default_media_type=media_type)
            provider_type = provider_media_type(profile)
            updated = self.merge_row_from_cache(
                row,
                provider_type,
                db=db,
                art_profile=profile,
                provider_cache=provider_cache,
            )
            ref = self._collect_enrichment_ref(updated, provider_type, meta_cache=meta_cache, art_profile=profile)
            if ref:
                enrichment_refs.append(ref)
            merged.append(updated)

        g.log(
            f"local_merge_ms={(time.time() - start) * 1000:.0f} rows={len(rows)} enrich_refs={len(enrichment_refs)}",
            "debug",
        )
        return merged, enrichment_refs

    def enrich_list_meta_online(
        self,
        refs: list[dict],
        media_type: str,
        *,
        db=None,
        persist: bool = True,
    ) -> list:
        """Fetch missing provider meta online and optionally persist merged rows."""
        if not refs:
            return []

        if db is None:
            from resources.lib.database.simkl_sync.database import SimklSyncDatabase

            db = SimklSyncDatabase()

        from resources.lib.database.sync_meta_cache import SyncMetaCache
        from resources.lib.modules.artwork_profile import artwork_profile_for_row, provider_media_type

        meta_cache = SyncMetaCache()
        need_online_refs = [dict(ref) for ref in refs if ref.get("simkl_id") is not None]
        online_ids: set[int] = set()
        movie_refs = [ref for ref in need_online_refs if ref.get("_provider_type") == "movie"]
        tvshow_refs = [ref for ref in need_online_refs if ref.get("_provider_type") != "movie"]
        if movie_refs:
            online_ids |= self._online_update_refs(movie_refs, "movie", db)
        if tvshow_refs:
            online_ids |= self._online_update_refs(tvshow_refs, "tvshow", db)

        merged_by_id: dict[int, dict] = {}
        if online_ids:
            movie_ids = {
                int(ref["simkl_id"])
                for ref in movie_refs
                if ref.get("simkl_id") is not None and int(ref["simkl_id"]) in online_ids
            }
            tvshow_ids = {
                int(ref["simkl_id"])
                for ref in tvshow_refs
                if ref.get("simkl_id") is not None and int(ref["simkl_id"]) in online_ids
            }
            if movie_ids:
                merged_by_id.update(self._reload_rows_by_id(db, "movie", movie_ids))
            if tvshow_ids:
                merged_by_id.update(self._reload_rows_by_id(db, "tvshow", tvshow_ids))

        ref_by_id = {
            int(ref["simkl_id"]): ref
            for ref in need_online_refs
            if ref.get("simkl_id") is not None
        }
        merged = list(merged_by_id.values())
        for row in merged:
            if not isinstance(row, dict):
                continue
            simkl_id = row.get("simkl_id")
            if simkl_id is None:
                continue
            sid = int(simkl_id)
            ref = ref_by_id.get(sid)
            if not ref:
                continue
            provider_type = ref.get("_provider_type") or media_type
            cache_media_type = "movie" if provider_type == "movie" else "show"
            profile = artwork_profile_for_row(row, default_media_type=provider_type)
            remaining_gaps = self._row_meta_gaps(row, provider_type, art_profile=profile)
            if remaining_gaps and self._can_fetch_provider_meta(row):
                for gap in remaining_gaps:
                    meta_cache.mark_gap_miss(cache_media_type, sid, gap)
            else:
                meta_cache.clear_provider_miss(cache_media_type, sid)
                meta_cache.set_row(cache_media_type, row)

        if persist and merged:
            movie_rows = [
                row
                for row in merged
                if isinstance(row, dict) and provider_media_type(artwork_profile_for_row(row, media_type)) == "movie"
            ]
            tvshow_rows = [
                row
                for row in merged
                if isinstance(row, dict) and provider_media_type(artwork_profile_for_row(row, media_type)) != "movie"
            ]
            if movie_rows:
                self._persist_list_rows(movie_rows, "movie", db=db, skip_ids=online_ids)
            if tvshow_rows:
                self._persist_list_rows(tvshow_rows, "tvshow", db=db, skip_ids=online_ids)
        return merged

    def _online_update_refs(self, refs: list[dict], media_type: str, db) -> set[int]:
        if not refs:
            return set()
        if media_type == "movie":
            updater = db if hasattr(db, "_update_movies") else None
            if updater is None:
                from resources.lib.database.simkl_sync.movies import SimklSyncDatabase as MoviesDB

                updater = MoviesDB()
            updater._update_movies(refs)
        else:
            updater = db if hasattr(db, "_update_mill_format_shows") else None
            if updater is None:
                from resources.lib.database.simkl_sync.shows import SimklSyncDatabase as ShowsDB

                updater = ShowsDB()
            updater._update_mill_format_shows(refs, False, skip_mill=True)
        return {int(ref["simkl_id"]) for ref in refs if ref.get("simkl_id") is not None}

    @staticmethod
    def _reload_rows_by_id(db, media_type: str, simkl_ids: set[int]) -> dict[int, dict]:
        if not simkl_ids:
            return {}
        ids_sql = ",".join(str(int(simkl_id)) for simkl_id in simkl_ids)
        if media_type == "movie":
            query = f"""
                SELECT m.simkl_id,
                       m.info,
                       m.art,
                       m.cast,
                       m.args,
                       b.resume_time,
                       b.percent_played,
                       m.watched AS play_count,
                       m.user_rating
                FROM movies AS m
                         LEFT JOIN bookmarks AS b
                                   ON m.simkl_id = b.simkl_id
                WHERE m.simkl_id IN ({ids_sql})
            """
        else:
            query = f"""
                SELECT s.simkl_id,
                       s.info,
                       s.cast,
                       s.art,
                       s.args,
                       s.watched_episodes,
                       s.unwatched_episodes,
                       s.episode_count,
                       s.season_count,
                       s.air_date,
                       s.user_rating
                FROM shows AS s
                WHERE s.simkl_id IN ({ids_sql})
            """
        return {
            int(row["simkl_id"]): row
            for row in (db.fetchall(query) or [])
            if isinstance(row, dict) and row.get("simkl_id") is not None
        }

    def _persist_list_rows(self, rows, media_type: str, *, db, skip_ids: set[int] | None = None) -> None:
        table = "movies" if media_type == "movie" else "shows"
        skip_ids = skip_ids or set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            simkl_id = row.get("simkl_id")
            if simkl_id is None or int(simkl_id) in skip_ids:
                continue
            info = row.get("info")
            art = row.get("art")
            cast = row.get("cast")
            if not isinstance(info, dict) or not isinstance(art, dict):
                continue
            from resources.lib.modules.meta_storage import slim_db_row

            slim = slim_db_row({"info": info, "art": art, "cast": cast})
            db.execute_sql(
                f"UPDATE {table} SET info=?, art=?, cast=?, meta_hash=?, last_updated=? WHERE simkl_id=?",
                (
                    slim["info"],
                    slim["art"],
                    slim.get("cast") if isinstance(slim.get("cast"), list) else [],
                    self.meta_hash,
                    str(datetime.datetime.now().isoformat()),
                    int(simkl_id),
                ),
            )
            from resources.lib.database.sync_meta_cache import SyncMetaCache

            SyncMetaCache().set_row(
                media_type,
                {
                    "simkl_id": int(simkl_id),
                    "info": slim["info"],
                    "art": slim["art"],
                    "cast": slim.get("cast") if isinstance(slim.get("cast"), list) else [],
                },
            )

    def gapfill_list_meta(self, rows, media_type: str, *, db=None, persist: bool = False) -> list:
        """Merge cached provider meta for fast menus; fetch online only for remaining gaps."""
        if not rows:
            return rows

        if db is None:
            from resources.lib.database.simkl_sync.database import SimklSyncDatabase

            db = SimklSyncDatabase()

        merged, enrichment_refs = self.merge_list_meta_local(rows, media_type, db=db)
        if enrichment_refs:
            self.enrich_list_meta_online(enrichment_refs, media_type, db=db, persist=persist)
            movie_ids = {int(ref["simkl_id"]) for ref in enrichment_refs if ref.get("_provider_type") == "movie"}
            tvshow_ids = {
                int(ref["simkl_id"]) for ref in enrichment_refs if ref.get("_provider_type") != "movie"
            }
            reloaded: dict[int, dict] = {}
            if movie_ids:
                reloaded.update(self._reload_rows_by_id(db, "movie", movie_ids))
            if tvshow_ids:
                reloaded.update(self._reload_rows_by_id(db, "tvshow", tvshow_ids))
            merged = [
                reloaded.get(int(row["simkl_id"]), row) if isinstance(row, dict) and row.get("simkl_id") else row
                for row in merged
            ]
        return merged

    def gapfill_list_clearlogo(self, rows, media_type: str, *, db=None, persist: bool = False) -> list:
        """Backward-compatible alias for fast-menu metadata merge."""
        return self.gapfill_list_meta(rows, media_type, db=db, persist=persist)

    # endregion

    # endregion

    @staticmethod
    def _force_update(db_object):
        return db_object.get("needs_update", False) in ["true", "True", True, 1]

    def _tmdb_art_meta_up_to_par(self, media_type, item):
        return self.art_meta_up_to_par(media_type, MetadataHandler.tmdb_object(item))

    def _tvdb_art_meta_up_to_par(self, media_type, item):
        return self.art_meta_up_to_par(media_type, MetadataHandler.tvdb_object(item))

    def _fanart_art_meta_up_to_par(self, media_type, item):
        return self.art_meta_up_to_par(media_type, MetadataHandler.fanart_object(item))

    @staticmethod
    def art_meta_up_to_par(media_type, item):
        try:
            if not item:
                return False
            if (
                media_type in ["tvshow", "season", "movie"]
                and not tools.safe_dict_get(item, "art", "poster")
                and not tools.safe_dict_get(item, "art", "keyart")
            ):
                return False
            if media_type in ["tvshow", "movie"] and not tools.safe_dict_get(item, "art", "fanart"):
                return False
            return bool(media_type != "episode" or tools.safe_dict_get(item, "art", "thumb"))

        except KeyError:
            return False

    @staticmethod
    def _info_meta_up_to_par(item):
        return tools.safe_dict_get(item, "info", "title") and tools.safe_dict_get(item, "info", "plot")

    def _tmdb_info_meta_up_to_par(self, item):
        return self._info_meta_up_to_par(MetadataHandler.tmdb_object(item))

    def _tvdb_info_meta_up_to_par(self, item):
        return self._info_meta_up_to_par(MetadataHandler.tvdb_object(item))

    @staticmethod
    def full_meta_up_to_par(media_type, item):
        if MetadataHandler._info_meta_up_to_par(item):
            return True
        elif MetadataHandler.art_meta_up_to_par(media_type, item):
            return True
        return False

    @staticmethod
    def simkl_meta_savable(media_type, item):
        """Simkl is authoritative for sync rows — persist minimal episode/season identity without TMDB plot/art."""
        if not item:
            return False
        info = tools.safe_dict_get(item, "info") or {}
        if not info.get("simkl_id"):
            return False
        singular = media_type.rstrip("s") if media_type.endswith("s") else media_type
        if singular == "episode":
            season = info.get("season")
            episode = info.get("episode", info.get("number"))
            return season is not None and episode is not None
        if singular == "season":
            return info.get("season") is not None or info.get("mediatype") == "season"
        if singular in ("movie", "show"):
            return bool(info.get("title"))
        return MetadataHandler.full_meta_up_to_par(singular, item)

    @staticmethod
    def info(data):
        return data.get("info", {})

    @staticmethod
    def art(data):
        return data.get("art", {})

    @staticmethod
    def cast(data):
        return data.get("cast", {})

    @staticmethod
    def simkl_object(data):
        return data.get("simkl_object", {})

    @staticmethod
    def tmdb_object(data):
        return data.get("tmdb_object", {})

    @staticmethod
    def tvdb_object(data):
        return data.get("tvdb_object", {})

    @staticmethod
    def fanart_object(data):
        return data.get("fanart_object", {})

    @staticmethod
    def simkl_info(data):
        return MetadataHandler.info(MetadataHandler.simkl_object(data))

    @staticmethod
    def tmdb_info(data):
        return MetadataHandler.info(MetadataHandler.tmdb_object(data))

    @staticmethod
    def tvdb_info(data):
        return MetadataHandler.info(MetadataHandler.tvdb_object(data))

    @staticmethod
    def fanart_info(data):
        return MetadataHandler.info(MetadataHandler.fanart_object(data))

    @staticmethod
    def get_simkl_info(data, key, default=None):
        try:
            return MetadataHandler.simkl_info(data).get(key, default)
        except Exception:
            return default

    @staticmethod
    def get_tmdb_info(data, key, default=None):
        try:
            return MetadataHandler.tmdb_info(data).get(key, default)
        except Exception:
            return default

    @staticmethod
    def get_tvdb_info(data, key, default=None):
        try:
            return MetadataHandler.tvdb_info(data).get(key, default)
        except Exception:
            return default

    @staticmethod
    def get_fanart_info(data, key, default=None):
        try:
            return MetadataHandler.fanart_info(data).get(key, default)
        except Exception:
            return default

    @staticmethod
    def pop_simkl_info(data, key, default=None):
        try:
            return MetadataHandler.simkl_info(data).pop(key, default)
        except Exception:
            return default

    @staticmethod
    def pop_tmdb_info(data, key, default=None):
        try:
            return MetadataHandler.tmdb_info(data).pop(key, default)
        except Exception:
            return default

    @staticmethod
    def pop_tvdb_info(data, key, default=None):
        try:
            return MetadataHandler.tvdb_info(data).pop(key, default)
        except Exception:
            return default

    @staticmethod
    def pop_fanart_info(data, key, default=None):
        try:
            return MetadataHandler.fanart_info(data).pop(key, default)
        except Exception:
            return default

    @staticmethod
    def sort_list_items(db_list, media_list):
        db_list_dict = {}
        for row in db_list:
            simkl_id = tools.safe_dict_get(row, "info", "simkl_id") or row.get("simkl_id")
            if simkl_id is not None:
                db_list_dict[simkl_id] = row
        return [db_list_dict.get(o.get("simkl_id")) for o in media_list]
