"""Data models for snapshot data.

Ported from table-mutation-tracker/src/scraper/base.py (Assignment, ClassMetadata)
and table-mutation-tracker/frontend/lib/types.ts (rolling index schema).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Assignment:
    due_date: str  # YYYY-MM-DD
    category: str
    name: str
    flags: dict[str, bool] = field(default_factory=dict)
    score_raw: str = ""
    points_earned: float | None = None
    points_possible: float | None = None
    percent: float | None = None
    grade: str | None = None
    has_comments: bool = False

    @property
    def identity_key(self) -> tuple[str, str]:
        return (self.name, self.due_date)

    @classmethod
    def from_dict(cls, data: dict) -> Assignment:
        return cls(
            due_date=data.get("due_date", ""),
            category=data.get("category", ""),
            name=data.get("name", ""),
            flags=data.get("flags", {}),
            score_raw=data.get("score_raw", ""),
            points_earned=data.get("points_earned"),
            points_possible=data.get("points_possible"),
            percent=data.get("percent"),
            grade=data.get("grade"),
            has_comments=data.get("has_comments", False),
        )


@dataclass
class ClassMetadata:
    course: str
    teacher: str = ""
    teacher_email: str = ""
    expression: str = ""
    term: str = ""
    final_grade: str | None = None
    final_percent: float | None = None
    assignment_count: int = 0
    last_updated: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> ClassMetadata:
        return cls(
            course=data.get("course", ""),
            teacher=data.get("teacher", ""),
            teacher_email=data.get("teacher_email", ""),
            expression=data.get("expression", ""),
            term=data.get("term", ""),
            final_grade=data.get("final_grade"),
            final_percent=data.get("final_percent"),
            assignment_count=data.get("assignment_count", 0),
            last_updated=data.get("last_updated"),
        )


@dataclass
class ChangeSummary:
    class_level: int = 0
    added: int = 0
    modified: int = 0
    deleted: int = 0
    total: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> ChangeSummary:
        return cls(
            class_level=data.get("class_level", 0),
            added=data.get("added", 0),
            modified=data.get("modified", 0),
            deleted=data.get("deleted", 0),
            total=data.get("total", 0),
        )


@dataclass
class ClassSummary:
    course: str
    final_grade: str | None = None
    final_percent: float | None = None
    assignment_count: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> ClassSummary:
        return cls(
            course=data.get("course", ""),
            final_grade=data.get("final_grade"),
            final_percent=data.get("final_percent"),
            assignment_count=data.get("assignment_count", 0),
        )


@dataclass
class SnapshotEntry:
    date: str
    time: str
    scrape_timestamp: str = ""
    previous_snapshot: str | None = None
    changes: ChangeSummary = field(default_factory=ChangeSummary)
    classes: dict[str, ClassSummary] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> SnapshotEntry:
        return cls(
            date=data.get("date", ""),
            time=data.get("time", ""),
            scrape_timestamp=data.get("scrape_timestamp", ""),
            previous_snapshot=data.get("previous_snapshot"),
            changes=ChangeSummary.from_dict(data.get("changes", {})),
            classes={
                slug: ClassSummary.from_dict(cls_data)
                for slug, cls_data in data.get("classes", {}).items()
            },
        )


@dataclass
class RollingIndex:
    snapshots: list[SnapshotEntry] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> RollingIndex:
        return cls(
            snapshots=[SnapshotEntry.from_dict(s) for s in data.get("snapshots", [])]
        )

    def latest_snapshot(self) -> SnapshotEntry | None:
        return self.snapshots[-1] if self.snapshots else None
