"""Deterministic analysis functions for snapshot data.

All functions return human-readable strings for the LLM to narrate.
Diff logic ported from table-mutation-tracker/src/lib/snapshot_store.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from data.models import Assignment
from data.snapshot_reader import SnapshotReader

DIFF_FIELDS = ("score_raw", "percent", "grade", "category")


def diff_assignments(
    slug: str, current: list[dict], previous: list[dict]
) -> list[dict]:
    """Diff two assignment lists for a single class.

    Ported from table-mutation-tracker snapshot_store.py::_diff_assignments.
    Returns list of change dicts with type: added/deleted/modified.
    """
    prev_by_key = {(a["name"], a["due_date"]): a for a in previous}
    cur_by_key = {(a["name"], a["due_date"]): a for a in current}

    changes = []

    for key in cur_by_key.keys() - prev_by_key.keys():
        a = cur_by_key[key]
        changes.append(
            {
                "class": slug,
                "assignment": a["name"],
                "due_date": a["due_date"],
                "type": "added",
            }
        )

    for key in prev_by_key.keys() - cur_by_key.keys():
        a = prev_by_key[key]
        changes.append(
            {
                "class": slug,
                "assignment": a["name"],
                "due_date": a["due_date"],
                "type": "deleted",
            }
        )

    for key in cur_by_key.keys() & prev_by_key.keys():
        cur_a = cur_by_key[key]
        prev_a = prev_by_key[key]

        field_changes = []
        for field_name in DIFF_FIELDS:
            if cur_a.get(field_name) != prev_a.get(field_name):
                field_changes.append(
                    {
                        "field": field_name,
                        "old": prev_a.get(field_name),
                        "new": cur_a.get(field_name),
                    }
                )

        cur_flags = cur_a.get("flags", {})
        prev_flags = prev_a.get("flags", {})
        if cur_flags != prev_flags:
            field_changes.append(
                {
                    "field": "flags",
                    "old": prev_flags,
                    "new": cur_flags,
                }
            )

        if field_changes:
            changes.append(
                {
                    "class": slug,
                    "assignment": cur_a["name"],
                    "due_date": cur_a["due_date"],
                    "type": "modified",
                    "changes": field_changes,
                }
            )

    return changes


def summarize_class(reader: SnapshotReader, slug: str) -> str:
    """Summarize current state of a class: grade, assignment count, teacher."""
    coords = reader.latest_snapshot_coords()
    if not coords:
        return "No snapshot data available."

    meta = reader.read_class_metadata(*coords, slug)
    if not meta:
        return f"No data found for class '{slug}'."

    parts = [f"{meta.course}"]
    if meta.final_grade and meta.final_percent is not None:
        parts.append(f"Current grade: {meta.final_grade} ({meta.final_percent}%)")
    elif meta.final_grade:
        parts.append(f"Current grade: {meta.final_grade}")
    else:
        parts.append("No grade posted yet")
    parts.append(f"{meta.assignment_count} assignments")
    if meta.teacher:
        parts.append(f"Teacher: {meta.teacher}")
    if meta.last_updated:
        parts.append(f"Last updated: {meta.last_updated}")

    return ". ".join(parts) + "."


def summarize_all_classes(reader: SnapshotReader) -> str:
    """List all classes with current grades."""
    index = reader.get_rolling_index()
    latest = index.latest_snapshot()
    if not latest:
        return "No snapshot data available."

    lines = []
    for _slug, cls in latest.classes.items():
        grade_str = (
            f"{cls.final_grade} ({cls.final_percent}%)"
            if cls.final_grade and cls.final_percent is not None
            else cls.final_grade or "No grade"
        )
        lines.append(f"{cls.course}: {grade_str} ({cls.assignment_count} assignments)")

    return "\n".join(lines)


def summarize_changes(
    reader: SnapshotReader, slug: str | None = None, days: int = 7
) -> str:
    """Summarize recent changes from the rolling index."""
    index = reader.get_rolling_index()
    if not index.snapshots:
        return "No snapshot data available."

    cutoff = datetime.now() - timedelta(days=days)
    recent = [
        s
        for s in index.snapshots
        if s.scrape_timestamp and _parse_timestamp(s.scrape_timestamp) >= cutoff
    ]

    if not recent:
        return f"No snapshots found in the last {days} days."

    total_added = 0
    total_modified = 0
    total_deleted = 0
    class_level = 0

    for snap in recent:
        if snap.changes.total > 0:
            total_added += snap.changes.added
            total_modified += snap.changes.modified
            total_deleted += snap.changes.deleted
            class_level += snap.changes.class_level

    if total_added + total_modified + total_deleted == 0:
        return f"No assignment changes detected in the last {days} days across {len(recent)} snapshots."

    parts = [f"In the last {days} days ({len(recent)} snapshots):"]
    if total_added:
        parts.append(f"{total_added} assignments added")
    if total_modified:
        parts.append(f"{total_modified} assignments modified")
    if total_deleted:
        parts.append(f"{total_deleted} assignments deleted")
    if class_level:
        parts.append(f"{class_level} class-level grade changes")

    return ". ".join(parts) + "."


def diff_snapshots(
    reader: SnapshotReader,
    slug: str,
    date1: str,
    time1: str,
    date2: str,
    time2: str,
) -> str:
    """Diff assignments between two specific snapshots for a class."""
    current = reader.read_assignments_raw(date2, time2, slug)
    previous = reader.read_assignments_raw(date1, time1, slug)

    if not current and not previous:
        return f"No assignment data found for '{slug}' on either date."
    if not previous:
        return f"No previous data for '{slug}' on {date1}. Current snapshot has {len(current)} assignments."
    if not current:
        return f"No current data for '{slug}' on {date2}. Previous snapshot had {len(previous)} assignments."

    changes = diff_assignments(slug, current, previous)
    if not changes:
        return f"No changes found for '{slug}' between {date1} and {date2}."

    return _format_changes(changes)


def find_assignment(reader: SnapshotReader, slug: str, assignment_name: str) -> str:
    """Look up a specific assignment by name (fuzzy match)."""
    coords = reader.latest_snapshot_coords()
    if not coords:
        return "No snapshot data available."

    assignments = reader.read_assignments(*coords, slug)
    if not assignments:
        return f"No assignments found for class '{slug}'."

    name_lower = assignment_name.lower().strip()
    matches = [a for a in assignments if name_lower in a.name.lower()]

    if not matches:
        return f"No assignment matching '{assignment_name}' found in '{slug}'."

    lines = []
    for a in matches:
        lines.append(_format_assignment(a))
    return "\n\n".join(lines)


def list_flagged_assignments(
    reader: SnapshotReader,
    slug: str | None = None,
    flag: str | None = None,
) -> str:
    """List assignments with specific flags (missing, late, etc.)."""
    coords = reader.latest_snapshot_coords()
    if not coords:
        return "No snapshot data available."

    index = reader.get_rolling_index()
    latest = index.latest_snapshot()
    if not latest:
        return "No snapshot data available."

    slugs = [slug] if slug else list(latest.classes.keys())
    results = []

    for s in slugs:
        assignments = reader.read_assignments(*coords, s)
        course_name = latest.classes.get(s, None)
        course_label = course_name.course if course_name else s

        for a in assignments:
            if flag:
                if a.flags.get(flag, False):
                    results.append(
                        f"{course_label}: {a.name} (due {a.due_date}) — {flag}"
                    )
            else:
                active_flags = [f for f, v in a.flags.items() if v]
                if active_flags:
                    results.append(
                        f"{course_label}: {a.name} (due {a.due_date}) — {', '.join(active_flags)}"
                    )

    if not results:
        flag_desc = f" flagged as '{flag}'" if flag else " with any flags"
        return f"No assignments found{flag_desc}."

    return "\n".join(results)


def get_category_breakdown(reader: SnapshotReader, slug: str) -> str:
    """Break down performance by assignment category for a class."""
    coords = reader.latest_snapshot_coords()
    if not coords:
        return "No snapshot data available."

    assignments = reader.read_assignments(*coords, slug)
    if not assignments:
        return f"No assignments found for class '{slug}'."

    categories: dict[str, list[Assignment]] = {}
    for a in assignments:
        categories.setdefault(a.category, []).append(a)

    lines = []
    for cat, cat_assignments in sorted(categories.items()):
        scored = [a for a in cat_assignments if a.percent is not None]
        total = len(cat_assignments)
        if scored:
            avg_pct = sum(a.percent for a in scored) / len(scored)
            lines.append(f"{cat}: {len(scored)}/{total} scored, average {avg_pct:.0f}%")
        else:
            lines.append(f"{cat}: {total} assignments, none scored yet")

    return "\n".join(lines)


def get_grade_trend(reader: SnapshotReader, slug: str, days: int = 30) -> str:
    """Track how a class's final grade has changed over time."""
    index = reader.get_rolling_index()
    if not index.snapshots:
        return "No snapshot data available."

    cutoff = datetime.now() - timedelta(days=days)
    data_points: list[tuple[str, str | None, float | None]] = []

    for snap in index.snapshots:
        if snap.scrape_timestamp and _parse_timestamp(snap.scrape_timestamp) < cutoff:
            continue
        cls = snap.classes.get(slug)
        if cls:
            data_points.append((snap.date, cls.final_grade, cls.final_percent))

    if not data_points:
        return f"No grade data found for '{slug}' in the last {days} days."

    # Deduplicate by date (keep last snapshot per day)
    by_date: dict[str, tuple[str | None, float | None]] = {}
    for date, grade, pct in data_points:
        by_date[date] = (grade, pct)

    lines = []
    for date in sorted(by_date.keys()):
        grade, pct = by_date[date]
        if grade and pct is not None:
            lines.append(f"{date}: {grade} ({pct}%)")
        elif grade:
            lines.append(f"{date}: {grade}")
        else:
            lines.append(f"{date}: No grade")

    first_pct = data_points[0][2]
    last_pct = data_points[-1][2]
    if first_pct is not None and last_pct is not None:
        diff = last_pct - first_pct
        direction = "up" if diff > 0 else "down" if diff < 0 else "unchanged"
        lines.append(f"Trend: {direction} {abs(diff):.0f}% over this period")

    return "\n".join(lines)


def get_comprehensive_summary(reader: SnapshotReader, days: int = 14) -> str:
    """Generate a holistic summary across all classes.

    Aggregates: current grades, recent changes, flagged assignments,
    deleted assignments, and grade trends. Gives the LLM enough
    context to answer abstract questions like "what should I worry about?"
    """
    sections = []

    # Current grades
    grades = summarize_all_classes(reader)
    if grades:
        sections.append(f"CURRENT GRADES:\n{grades}")

    # Recent changes
    changes = summarize_changes(reader, days=days)
    if changes and "No" not in changes:
        sections.append(f"RECENT CHANGES ({days} days):\n{changes}")

    # Flagged assignments across all classes
    flagged = list_flagged_assignments(reader)
    if flagged and "No assignments found" not in flagged:
        sections.append(f"FLAGGED ASSIGNMENTS:\n{flagged}")

    # Deleted assignments across all classes
    deleted = get_deleted_assignments(reader, days=days)
    if deleted and "No deleted" not in deleted:
        sections.append(f"DELETED ASSIGNMENTS ({days} days):\n{deleted}")

    # Modified assignments (score changes) across all classes
    modified = get_modified_assignments(reader, days=days)
    if modified and "No modified" not in modified:
        sections.append(f"SCORE CHANGES ({days} days):\n{modified}")

    # Grade trends per class
    index = reader.get_rolling_index()
    latest = index.latest_snapshot()
    if latest:
        trend_lines = []
        for slug in latest.classes:
            trend = get_grade_trend(reader, slug, days=days)
            if "Trend:" in trend:
                trend_line = next(
                    line for line in trend.split("\n") if line.startswith("Trend:")
                )
                course = latest.classes[slug].course
                trend_lines.append(f"{course}: {trend_line}")
        if trend_lines:
            sections.append(f"GRADE TRENDS ({days} days):\n" + "\n".join(trend_lines))

    if not sections:
        return "No data available for summary."

    return "\n\n".join(sections)


def get_deleted_assignments(
    reader: SnapshotReader,
    slug: str | None = None,
    days: int = 14,
) -> str:
    """Find assignments that were deleted (present in earlier snapshot, absent in later)."""
    index = reader.get_rolling_index()
    if not index.snapshots:
        return "No snapshot data available."

    cutoff = datetime.now() - timedelta(days=days)
    latest = index.latest_snapshot()
    if not latest:
        return "No snapshot data available."

    slugs = [slug] if slug else list(latest.classes.keys())
    all_deleted = []

    # Compare consecutive snapshots within the date range
    for i in range(1, len(index.snapshots)):
        snap = index.snapshots[i]
        prev = index.snapshots[i - 1]
        if snap.scrape_timestamp and _parse_timestamp(snap.scrape_timestamp) < cutoff:
            continue

        for s in slugs:
            if s not in snap.classes and s not in prev.classes:
                continue
            current = reader.read_assignments_raw(snap.date, snap.time, s)
            previous = reader.read_assignments_raw(prev.date, prev.time, s)
            changes = diff_assignments(s, current, previous)
            for c in changes:
                if c["type"] == "deleted":
                    course = latest.classes.get(s)
                    label = course.course if course else s
                    all_deleted.append(
                        f"{label}: {c['assignment']} (due {c['due_date']}) — deleted on {snap.date}"
                    )

    if not all_deleted:
        scope = f" in '{slug}'" if slug else ""
        return f"No deleted assignments found{scope} in the last {days} days."

    return "\n".join(all_deleted)


def _is_unscored(value) -> bool:
    """Check if a score value represents an unscored/pending state."""
    if value is None:
        return True
    s = str(value).strip()
    return s in ("", "--", "0") or s.startswith("--/")


def get_modified_assignments(
    reader: SnapshotReader,
    slug: str | None = None,
    days: int = 14,
) -> str:
    """Find assignments with retroactive score/grade modifications.

    Only surfaces changes where both the old and new values are actual scores —
    initial grading (unscored → scored) is filtered out as normal workflow.
    """
    index = reader.get_rolling_index()
    if not index.snapshots:
        return "No snapshot data available."

    cutoff = datetime.now() - timedelta(days=days)
    latest = index.latest_snapshot()
    if not latest:
        return "No snapshot data available."

    slugs = [slug] if slug else list(latest.classes.keys())
    all_modified = []

    for i in range(1, len(index.snapshots)):
        snap = index.snapshots[i]
        prev = index.snapshots[i - 1]
        if snap.scrape_timestamp and _parse_timestamp(snap.scrape_timestamp) < cutoff:
            continue

        for s in slugs:
            if s not in snap.classes and s not in prev.classes:
                continue
            current = reader.read_assignments_raw(snap.date, snap.time, s)
            previous = reader.read_assignments_raw(prev.date, prev.time, s)
            changes = diff_assignments(s, current, previous)
            for c in changes:
                if c["type"] == "modified":
                    # Filter to only retroactive changes (both old and new are real scores)
                    score_changes = [
                        fc
                        for fc in c.get("changes", [])
                        if fc["field"] in ("score_raw", "percent", "grade")
                        and not _is_unscored(fc["old"])
                        and not _is_unscored(fc["new"])
                    ]
                    if not score_changes:
                        continue

                    course = latest.classes.get(s)
                    label = course.course if course else s
                    field_parts = [
                        f"{fc['field']}: {fc['old']} → {fc['new']}"
                        for fc in score_changes
                    ]
                    all_modified.append(
                        f"{label}: {c['assignment']} (due {c['due_date']}) on {snap.date} — {', '.join(field_parts)}"
                    )

    if not all_modified:
        scope = f" in '{slug}'" if slug else ""
        return f"No retroactive score changes found{scope} in the last {days} days."

    return "\n".join(all_modified)


def _format_assignment(a: Assignment) -> str:
    """Format a single assignment as a readable string."""
    parts = [a.name]
    if a.due_date:
        parts.append(f"Due: {a.due_date}")
    parts.append(f"Category: {a.category}")
    if a.score_raw:
        parts.append(f"Score: {a.score_raw}")
    if a.grade:
        parts.append(f"Grade: {a.grade}")
    if a.percent is not None:
        parts.append(f"Percent: {a.percent}%")
    active_flags = [f for f, v in a.flags.items() if v]
    if active_flags:
        parts.append(f"Flags: {', '.join(active_flags)}")
    return ". ".join(parts) + "."


def _format_changes(changes: list[dict]) -> str:
    """Format a list of assignment changes as readable text."""
    lines = []
    for c in changes:
        if c["type"] == "added":
            lines.append(f"Added: {c['assignment']} (due {c['due_date']})")
        elif c["type"] == "deleted":
            lines.append(f"Deleted: {c['assignment']} (due {c['due_date']})")
        elif c["type"] == "modified":
            field_parts = []
            for fc in c.get("changes", []):
                field_parts.append(f"{fc['field']}: {fc['old']} -> {fc['new']}")
            lines.append(
                f"Modified: {c['assignment']} (due {c['due_date']}): "
                + ", ".join(field_parts)
            )
    return "\n".join(lines)


def _parse_timestamp(ts: str) -> datetime:
    """Parse an ISO timestamp, handling timezone info."""
    # Strip timezone for simplicity — all timestamps are UTC
    if "+" in ts:
        ts = ts[: ts.index("+")]
    elif ts.endswith("Z"):
        ts = ts[:-1]
    return datetime.fromisoformat(ts)
