"""Menu-open timing and paint completeness logging (kodi.log)."""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator

from resources.lib.modules.globals import g


def paint_complete_stats(
    rows: list[dict[str, Any]] | None,
    *,
    profile: str = "browse",
) -> tuple[int, int]:
    """Return (complete_count, total) for page rows."""
    from resources.lib.meta.paint_complete import partition_paint_rows

    if not rows:
        return 0, 0
    movies = [row for row in rows if isinstance(row, dict) and row.get("catalog") == "movie"]
    tv_rows = [row for row in rows if isinstance(row, dict) and row.get("catalog") == "tv"]
    anime_rows = [row for row in rows if isinstance(row, dict) and row.get("catalog") == "anime"]
    total = len([row for row in rows if isinstance(row, dict)])
    complete = 0
    if movies:
        done, _inc = partition_paint_rows(movies, "movie", profile=profile)
        complete += len(done)
    if tv_rows:
        done, _inc = partition_paint_rows(tv_rows, "tvshow", profile=profile)
        complete += len(done)
    if anime_rows:
        done, _inc = partition_paint_rows(anime_rows, "anime", profile=profile)
        complete += len(done)
    return complete, total


@contextmanager
def trace_menu_open(
    action: str,
    *,
    catalog: str = "",
    path: str = "open",
) -> Iterator[dict[str, Any]]:
    """Log Seren-speed menu metrics: action, ms, path, row_count, paint_complete_pct."""
    from resources.lib.net.http_ledger import menu_http_scope
    from resources.lib.net.request_policy import get_request_policy

    get_request_policy().reset_menu_budget()
    ctx: dict[str, Any] = {"path": path, "row_count": 0, "complete": 0, "total": 0}
    started = time.time()
    with menu_http_scope(action, path) as ledger:
        try:
            yield ctx
        finally:
            http_snap = ledger.snapshot()
            ctx.update(http_snap)
            ledger.path = str(ctx.get("path") or path)
        elapsed_ms = (time.time() - started) * 1000.0
        total = int(ctx.get("total") or 0)
        complete = int(ctx.get("complete") or 0)
        row_count = int(ctx.get("row_count") or total)
        pct = (100.0 * complete / total) if total else 100.0
        cat = catalog or str(ctx.get("catalog") or "")
        path_name = str(ctx.get("path") or path)
        sync_db_ms = ctx.get("sync_db_ms")
        finalize_ms = ctx.get("finalize_ms")
        builder_ms = ctx.get("builder_ms")
        phase_bits = []
        if sync_db_ms is not None:
            phase_bits.append(f"sync_db_ms={float(sync_db_ms):.0f}")
        if finalize_ms is not None:
            phase_bits.append(f"finalize_ms={float(finalize_ms):.0f}")
        if builder_ms is not None:
            phase_bits.append(f"builder_ms={float(builder_ms):.0f}")
        http_count = ctx.get("http_count")
        http_ms = ctx.get("http_ms")
        json_bytes = ctx.get("json_bytes")
        if http_count is not None:
            phase_bits.append(f"http_count={int(http_count)}")
        if http_ms is not None:
            phase_bits.append(f"http_ms={float(http_ms):.0f}")
        if json_bytes is not None and int(json_bytes) > 0:
            phase_bits.append(f"json_bytes={int(json_bytes)}")
        http_by_kind = ctx.get("http_by_kind")
        if isinstance(http_by_kind, dict) and http_by_kind:
            kind_bits = ",".join(f"{k}={v}" for k, v in sorted(http_by_kind.items()))
            phase_bits.append(f"http_by_kind={kind_bits}")
        phase_suffix = (" " + " ".join(phase_bits)) if phase_bits else ""
        g.log(
            "Menu perf: action=%s catalog=%s ms=%.0f path=%s rows=%d complete=%d/%d (%.0f%%)%s"
            % (action, cat, elapsed_ms, path_name, row_count, complete, total, pct, phase_suffix),
            "info",
        )


def note_phase_ms(ctx: dict[str, Any], key: str, started: float) -> None:
    if not isinstance(ctx, dict):
        return
    ctx[key] = round((time.time() - started) * 1000.0, 1)


def note_paint_rows(ctx: dict[str, Any], rows: list[dict] | None, *, profile: str = "browse") -> None:
    if not isinstance(ctx, dict):
        return
    complete, total = paint_complete_stats(rows, profile=profile)
    ctx["complete"] = complete
    ctx["total"] = total
    ctx["row_count"] = total
