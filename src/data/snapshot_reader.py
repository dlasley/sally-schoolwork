"""Local filesystem reader for the cloned table-mutation-data repo."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from data.models import Assignment, ClassMetadata, RollingIndex

logger = logging.getLogger("snapshot_reader")


class SnapshotReader:
    """Reads snapshot data from a local clone of the data repo.

    The data repo is expected to be cloned to `repo_path` with the structure:
        snapshots/{date}/{time}/{slug}/assignments.json
        snapshots/{date}/{time}/metadata.json
        index/rolling_index.json
    """

    def __init__(self, repo_path: str | Path, prefix: str = "") -> None:
        self.repo_path = Path(repo_path)
        self.prefix = prefix
        self._rolling_index: RollingIndex | None = None

    @property
    def _snapshots_dir(self) -> Path:
        if self.prefix:
            return self.repo_path / "snapshots" / self.prefix
        return self.repo_path / "snapshots"

    @property
    def _index_dir(self) -> Path:
        if self.prefix:
            return self.repo_path / "index" / self.prefix
        return self.repo_path / "index"

    def refresh(self) -> None:
        """Pull latest changes from the data repo."""
        if not (self.repo_path / ".git").exists():
            logger.warning("No .git directory at %s, skipping refresh", self.repo_path)
            return
        try:
            subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=self.repo_path,
                capture_output=True,
                check=True,
                timeout=30,
            )
            self._rolling_index = None  # invalidate cache
            logger.info("Data repo refreshed at %s", self.repo_path)
        except subprocess.CalledProcessError as e:
            logger.error("git pull failed: %s", e.stderr.decode())
        except subprocess.TimeoutExpired:
            logger.error("git pull timed out")

    def get_rolling_index(self) -> RollingIndex:
        """Load and cache the rolling index."""
        if self._rolling_index is not None:
            return self._rolling_index
        index_path = self._index_dir / "rolling_index.json"
        if not index_path.exists():
            logger.warning("Rolling index not found at %s", index_path)
            self._rolling_index = RollingIndex()
            return self._rolling_index
        with open(index_path) as f:
            self._rolling_index = RollingIndex.from_dict(json.load(f))
        return self._rolling_index

    def list_snapshot_dates(self) -> list[str]:
        """List available snapshot dates, sorted chronologically."""
        snapshots_dir = self._snapshots_dir
        if not snapshots_dir.exists():
            return []
        dates = [
            d.name
            for d in sorted(snapshots_dir.iterdir())
            if d.is_dir() and d.name[0].isdigit()  # excludes "synthetic" etc.
        ]
        return dates

    def list_snapshot_times(self, date: str) -> list[str]:
        """List available snapshot times for a given date."""
        date_dir = self._snapshots_dir / date
        if not date_dir.exists():
            return []
        return [
            t.name
            for t in sorted(date_dir.iterdir())
            if t.is_dir() and t.name[0].isdigit()
        ]

    def list_classes(self, date: str, time: str) -> list[str]:
        """List class slugs available in a snapshot."""
        snapshot_dir = self._snapshots_dir / date / time
        if not snapshot_dir.exists():
            return []
        return [d.name for d in sorted(snapshot_dir.iterdir()) if d.is_dir()]

    def read_assignments(self, date: str, time: str, slug: str) -> list[Assignment]:
        """Load assignments for a class from a snapshot."""
        path = self._snapshots_dir / date / time / slug / "assignments.json"
        if not path.exists():
            return []
        with open(path) as f:
            return [Assignment.from_dict(a) for a in json.load(f)]

    def read_assignments_raw(self, date: str, time: str, slug: str) -> list[dict]:
        """Load raw assignment dicts for diffing."""
        path = self._snapshots_dir / date / time / slug / "assignments.json"
        if not path.exists():
            return []
        with open(path) as f:
            return json.load(f)

    def read_metadata(self, date: str, time: str) -> dict:
        """Load snapshot metadata."""
        path = self._snapshots_dir / date / time / "metadata.json"
        if not path.exists():
            return {}
        with open(path) as f:
            return json.load(f)

    def read_class_metadata(
        self, date: str, time: str, slug: str
    ) -> ClassMetadata | None:
        """Load metadata for a specific class from a snapshot."""
        metadata = self.read_metadata(date, time)
        cls_data = metadata.get("classes", {}).get(slug)
        if cls_data is None:
            return None
        return ClassMetadata.from_dict(cls_data)

    def latest_snapshot_coords(self) -> tuple[str, str] | None:
        """Get (date, time) of the most recent snapshot."""
        index = self.get_rolling_index()
        latest = index.latest_snapshot()
        if latest:
            return (latest.date, latest.time)
        # Fallback: scan filesystem
        dates = self.list_snapshot_dates()
        if not dates:
            return None
        latest_date = dates[-1]
        times = self.list_snapshot_times(latest_date)
        if not times:
            return None
        return (latest_date, times[-1])

    def resolve_slug(self, class_name: str) -> str | None:
        """Fuzzy-match a user-provided class name to a known slug.

        Matches against slugs and course names from the latest snapshot.
        Case-insensitive, supports partial matches.
        """
        index = self.get_rolling_index()
        latest = index.latest_snapshot()
        if not latest:
            return None

        class_name_lower = class_name.lower().strip()

        # Exact slug match
        if class_name_lower in latest.classes:
            return class_name_lower

        # Exact course name match
        for slug, cls in latest.classes.items():
            if cls.course.lower() == class_name_lower:
                return slug

        # Partial match on slug or course name
        for slug, cls in latest.classes.items():
            if class_name_lower in slug or class_name_lower in cls.course.lower():
                return slug

        return None
