"""Unit tests for the data layer: models, snapshot_reader, and analysis.

These tests use a temporary directory with synthetic snapshot data
to avoid depending on the real data repo or network access.
"""

import json
import tempfile
from pathlib import Path

import pytest

from data.analysis import (
    _is_unscored,
    diff_assignments,
    find_assignment,
    get_category_breakdown,
    get_comprehensive_summary,
    get_deleted_assignments,
    get_grade_trend,
    get_modified_assignments,
    list_flagged_assignments,
    summarize_all_classes,
    summarize_changes,
    summarize_class,
)
from data.models import Assignment, ClassMetadata, RollingIndex
from data.snapshot_reader import SnapshotReader

# --- Fixtures ---


@pytest.fixture
def data_dir():
    """Create a temporary data repo with two snapshots."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        # Snapshot 1: 2026-03-08/210000
        s1_dir = root / "snapshots" / "2026-03-08" / "210000"
        s1_geo = s1_dir / "geometry"
        s1_geo.mkdir(parents=True)

        assignments_v1 = [
            {
                "name": "Medians and Altitudes",
                "due_date": "2026-03-06",
                "category": "Homework",
                "flags": {"missing": False, "late": False},
                "score_raw": "18/22",
                "points_earned": 18,
                "points_possible": 22,
                "percent": 82,
                "grade": "B-",
                "has_comments": False,
            },
            {
                "name": "Circumcenter Quiz",
                "due_date": "2026-03-05",
                "category": "Quizzes",
                "flags": {"missing": False, "late": False},
                "score_raw": "20/25",
                "points_earned": 20,
                "points_possible": 25,
                "percent": 80,
                "grade": "B-",
                "has_comments": False,
            },
        ]
        (s1_geo / "assignments.json").write_text(json.dumps(assignments_v1))

        metadata_v1 = {
            "date": "2026-03-08",
            "time": "210000",
            "scrape_timestamp": "2026-03-08T21:00:00+00:00",
            "classes": {
                "geometry": {
                    "course": "Geometry",
                    "teacher": "Smith, John",
                    "teacher_email": "john.smith@test.org",
                    "expression": "1(A)",
                    "term": "S2",
                    "final_grade": "B-",
                    "final_percent": 80,
                    "assignment_count": 2,
                    "last_updated": "3/6/2026",
                },
                "english_10_honors": {
                    "course": "English 10 (Honors)",
                    "teacher": "Jones, Sarah",
                    "teacher_email": "sarah.jones@test.org",
                    "expression": "2(A)",
                    "term": "S2",
                    "final_grade": "D-",
                    "final_percent": 63,
                    "assignment_count": 12,
                    "last_updated": "3/5/2026",
                },
            },
        }
        (s1_dir / "metadata.json").write_text(json.dumps(metadata_v1))

        # Snapshot 2: 2026-03-10/150000 — score changed, assignment added
        s2_dir = root / "snapshots" / "2026-03-10" / "150000"
        s2_geo = s2_dir / "geometry"
        s2_geo.mkdir(parents=True)

        assignments_v2 = [
            {
                "name": "Medians and Altitudes",
                "due_date": "2026-03-06",
                "category": "Homework",
                "flags": {"missing": False, "late": True},
                "score_raw": "20/22",
                "points_earned": 20,
                "points_possible": 22,
                "percent": 91,
                "grade": "A-",
                "has_comments": False,
            },
            {
                "name": "Circumcenter Quiz",
                "due_date": "2026-03-05",
                "category": "Quizzes",
                "flags": {"missing": False, "late": False},
                "score_raw": "20/25",
                "points_earned": 20,
                "points_possible": 25,
                "percent": 80,
                "grade": "B-",
                "has_comments": False,
            },
            {
                "name": "IXL M7Q to 80",
                "due_date": "2026-03-10",
                "category": "Homework",
                "flags": {"missing": True, "late": False},
                "score_raw": "--/20",
                "points_earned": None,
                "points_possible": 20,
                "percent": None,
                "grade": None,
                "has_comments": False,
            },
        ]
        (s2_geo / "assignments.json").write_text(json.dumps(assignments_v2))

        metadata_v2 = {
            "date": "2026-03-10",
            "time": "150000",
            "scrape_timestamp": "2026-03-10T15:00:00+00:00",
            "classes": {
                "geometry": {
                    "course": "Geometry",
                    "teacher": "Smith, John",
                    "teacher_email": "john.smith@test.org",
                    "expression": "1(A)",
                    "term": "S2",
                    "final_grade": "B",
                    "final_percent": 83,
                    "assignment_count": 3,
                    "last_updated": "3/10/2026",
                },
                "english_10_honors": {
                    "course": "English 10 (Honors)",
                    "teacher": "Jones, Sarah",
                    "teacher_email": "sarah.jones@test.org",
                    "expression": "2(A)",
                    "term": "S2",
                    "final_grade": "D-",
                    "final_percent": 63,
                    "assignment_count": 12,
                    "last_updated": "3/5/2026",
                },
            },
        }
        (s2_dir / "metadata.json").write_text(json.dumps(metadata_v2))

        # Synthetic directory (should be excluded)
        synthetic_dir = root / "snapshots" / "synthetic"
        synthetic_dir.mkdir(parents=True)
        (synthetic_dir / "dummy.txt").write_text("should be ignored")

        # Rolling index
        index_dir = root / "index"
        index_dir.mkdir(parents=True)
        rolling_index = {
            "snapshots": [
                {
                    "date": "2026-03-08",
                    "time": "210000",
                    "scrape_timestamp": "2026-03-08T21:00:00+00:00",
                    "previous_snapshot": None,
                    "changes": {
                        "class_level": 0,
                        "added": 0,
                        "modified": 0,
                        "deleted": 0,
                        "total": 0,
                    },
                    "classes": {
                        "geometry": {
                            "course": "Geometry",
                            "final_grade": "B-",
                            "final_percent": 80,
                            "assignment_count": 2,
                        },
                        "english_10_honors": {
                            "course": "English 10 (Honors)",
                            "final_grade": "D-",
                            "final_percent": 63,
                            "assignment_count": 12,
                        },
                    },
                },
                {
                    "date": "2026-03-10",
                    "time": "150000",
                    "scrape_timestamp": "2026-03-10T15:00:00+00:00",
                    "previous_snapshot": "2026-03-08/210000",
                    "changes": {
                        "class_level": 1,
                        "added": 1,
                        "modified": 1,
                        "deleted": 0,
                        "total": 2,
                    },
                    "classes": {
                        "geometry": {
                            "course": "Geometry",
                            "final_grade": "B",
                            "final_percent": 83,
                            "assignment_count": 3,
                        },
                        "english_10_honors": {
                            "course": "English 10 (Honors)",
                            "final_grade": "D-",
                            "final_percent": 63,
                            "assignment_count": 12,
                        },
                    },
                },
            ]
        }
        (index_dir / "rolling_index.json").write_text(json.dumps(rolling_index))

        yield root


@pytest.fixture
def reader(data_dir):
    return SnapshotReader(data_dir)


# --- Model tests ---


class TestModels:
    def test_assignment_from_dict(self):
        data = {
            "name": "Test Assignment",
            "due_date": "2026-03-10",
            "category": "Homework",
            "flags": {"missing": True},
            "score_raw": "15/20",
            "points_earned": 15,
            "points_possible": 20,
            "percent": 75,
            "grade": "C",
            "has_comments": True,
        }
        a = Assignment.from_dict(data)
        assert a.name == "Test Assignment"
        assert a.identity_key == ("Test Assignment", "2026-03-10")
        assert a.flags["missing"] is True
        assert a.percent == 75

    def test_class_metadata_from_dict(self):
        data = {
            "course": "Geometry",
            "teacher": "Mr. Smith",
            "final_grade": "B",
            "final_percent": 83,
            "assignment_count": 10,
        }
        meta = ClassMetadata.from_dict(data)
        assert meta.course == "Geometry"
        assert meta.final_percent == 83

    def test_rolling_index_from_dict(self):
        data = {
            "snapshots": [
                {
                    "date": "2026-03-08",
                    "time": "210000",
                    "scrape_timestamp": "2026-03-08T21:00:00+00:00",
                    "previous_snapshot": None,
                    "changes": {
                        "class_level": 0,
                        "added": 0,
                        "modified": 0,
                        "deleted": 0,
                        "total": 0,
                    },
                    "classes": {
                        "geometry": {
                            "course": "Geometry",
                            "final_grade": "B",
                            "final_percent": 83,
                            "assignment_count": 10,
                        }
                    },
                }
            ]
        }
        index = RollingIndex.from_dict(data)
        assert len(index.snapshots) == 1
        assert index.latest_snapshot().date == "2026-03-08"
        assert index.latest_snapshot().classes["geometry"].final_grade == "B"


# --- SnapshotReader tests ---


class TestSnapshotReader:
    def test_list_snapshot_dates(self, reader):
        dates = reader.list_snapshot_dates()
        assert dates == ["2026-03-08", "2026-03-10"]
        assert "synthetic" not in dates

    def test_list_snapshot_times(self, reader):
        times = reader.list_snapshot_times("2026-03-10")
        assert times == ["150000"]

    def test_list_classes(self, reader):
        classes = reader.list_classes("2026-03-10", "150000")
        assert "geometry" in classes

    def test_read_assignments(self, reader):
        assignments = reader.read_assignments("2026-03-10", "150000", "geometry")
        assert len(assignments) == 3
        assert assignments[0].name == "Medians and Altitudes"

    def test_read_metadata(self, reader):
        meta = reader.read_metadata("2026-03-10", "150000")
        assert "geometry" in meta["classes"]
        assert meta["classes"]["geometry"]["final_grade"] == "B"

    def test_read_class_metadata(self, reader):
        meta = reader.read_class_metadata("2026-03-10", "150000", "geometry")
        assert meta is not None
        assert meta.course == "Geometry"
        assert meta.final_percent == 83

    def test_rolling_index(self, reader):
        index = reader.get_rolling_index()
        assert len(index.snapshots) == 2
        assert index.latest_snapshot().date == "2026-03-10"

    def test_latest_snapshot_coords(self, reader):
        coords = reader.latest_snapshot_coords()
        assert coords == ("2026-03-10", "150000")

    def test_resolve_slug_exact(self, reader):
        assert reader.resolve_slug("geometry") == "geometry"

    def test_resolve_slug_course_name(self, reader):
        assert reader.resolve_slug("Geometry") == "geometry"

    def test_resolve_slug_partial(self, reader):
        assert reader.resolve_slug("geo") == "geometry"

    def test_resolve_slug_english(self, reader):
        assert reader.resolve_slug("english") == "english_10_honors"

    def test_resolve_slug_not_found(self, reader):
        assert reader.resolve_slug("chemistry") is None

    def test_synthetic_excluded(self, reader):
        dates = reader.list_snapshot_dates()
        assert "synthetic" not in dates


# --- Diff tests ---


class TestDiffAssignments:
    def test_no_changes(self):
        a = [
            {"name": "HW1", "due_date": "2026-03-10", "score_raw": "10/10", "flags": {}}
        ]
        changes = diff_assignments("geo", a, a)
        assert changes == []

    def test_added_assignment(self):
        prev = [{"name": "HW1", "due_date": "2026-03-10", "flags": {}}]
        curr = [*prev, {"name": "HW2", "due_date": "2026-03-11", "flags": {}}]
        changes = diff_assignments("geo", curr, prev)
        assert len(changes) == 1
        assert changes[0]["type"] == "added"
        assert changes[0]["assignment"] == "HW2"

    def test_deleted_assignment(self):
        prev = [
            {"name": "HW1", "due_date": "2026-03-10", "flags": {}},
            {"name": "HW2", "due_date": "2026-03-11", "flags": {}},
        ]
        curr = [{"name": "HW1", "due_date": "2026-03-10", "flags": {}}]
        changes = diff_assignments("geo", curr, prev)
        assert len(changes) == 1
        assert changes[0]["type"] == "deleted"
        assert changes[0]["assignment"] == "HW2"

    def test_modified_score(self):
        prev = [
            {
                "name": "HW1",
                "due_date": "2026-03-10",
                "score_raw": "8/10",
                "percent": 80,
                "grade": "B-",
                "category": "Homework",
                "flags": {},
            }
        ]
        curr = [
            {
                "name": "HW1",
                "due_date": "2026-03-10",
                "score_raw": "10/10",
                "percent": 100,
                "grade": "A",
                "category": "Homework",
                "flags": {},
            }
        ]
        changes = diff_assignments("geo", curr, prev)
        assert len(changes) == 1
        assert changes[0]["type"] == "modified"
        field_names = [c["field"] for c in changes[0]["changes"]]
        assert "score_raw" in field_names
        assert "percent" in field_names
        assert "grade" in field_names

    def test_modified_flags(self):
        prev = [{"name": "HW1", "due_date": "2026-03-10", "flags": {"late": False}}]
        curr = [{"name": "HW1", "due_date": "2026-03-10", "flags": {"late": True}}]
        changes = diff_assignments("geo", curr, prev)
        assert len(changes) == 1
        assert changes[0]["type"] == "modified"
        assert changes[0]["changes"][0]["field"] == "flags"


# --- Analysis function tests ---


class TestAnalysis:
    def test_summarize_class(self, reader):
        result = summarize_class(reader, "geometry")
        assert "Geometry" in result
        assert "83" in result
        assert "B" in result

    def test_summarize_all_classes(self, reader):
        result = summarize_all_classes(reader)
        assert "Geometry" in result
        assert "English 10" in result

    def test_summarize_changes(self, reader):
        # Use a large window to capture our test data
        result = summarize_changes(reader, days=365)
        assert (
            "added" in result
            or "modified" in result
            or "No assignment changes" in result
        )

    def test_diff_snapshots(self, reader):
        result = reader.read_assignments_raw("2026-03-08", "210000", "geometry")
        assert len(result) == 2
        from data.analysis import diff_snapshots

        result = diff_snapshots(
            reader,
            "geometry",
            "2026-03-08",
            "210000",
            "2026-03-10",
            "150000",
        )
        assert "Added" in result or "Modified" in result

    def test_find_assignment_exact(self, reader):
        result = find_assignment(reader, "geometry", "Circumcenter Quiz")
        assert "Circumcenter Quiz" in result
        assert "80" in result

    def test_find_assignment_fuzzy(self, reader):
        result = find_assignment(reader, "geometry", "circumcenter")
        assert "Circumcenter Quiz" in result

    def test_find_assignment_not_found(self, reader):
        result = find_assignment(reader, "geometry", "nonexistent")
        assert "No assignment matching" in result

    def test_list_flagged_missing(self, reader):
        result = list_flagged_assignments(reader, slug="geometry", flag="missing")
        assert "IXL M7Q" in result

    def test_list_flagged_late(self, reader):
        result = list_flagged_assignments(reader, slug="geometry", flag="late")
        assert "Medians and Altitudes" in result

    def test_list_flagged_none(self, reader):
        result = list_flagged_assignments(reader, slug="geometry", flag="exempt")
        assert "No assignments found" in result

    def test_category_breakdown(self, reader):
        result = get_category_breakdown(reader, "geometry")
        assert "Homework" in result
        assert "Quizzes" in result

    def test_grade_trend(self, reader):
        result = get_grade_trend(reader, "geometry", days=365)
        assert "2026-03-08" in result
        assert "2026-03-10" in result

    def test_comprehensive_summary(self, reader):
        result = get_comprehensive_summary(reader, days=365)
        assert "CURRENT GRADES" in result
        assert "Geometry" in result
        assert "English 10" in result

    def test_comprehensive_summary_no_data(self):
        """Comprehensive summary with empty reader returns snapshot unavailable messages."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            empty_reader = SnapshotReader(tmpdir)
            result = get_comprehensive_summary(empty_reader)
            assert "No snapshot data available" in result

    def test_deleted_assignments(self, reader):
        # Snapshot 2 has no deletions vs snapshot 1 (it only adds/modifies)
        result = get_deleted_assignments(reader, days=365)
        assert "No deleted" in result

    def test_deleted_assignments_with_deletion(self, data_dir):
        """Create a scenario where an assignment is deleted between snapshots."""
        # Add a third snapshot that removes the Circumcenter Quiz
        s3_dir = data_dir / "snapshots" / "2026-03-12" / "160000"
        s3_geo = s3_dir / "geometry"
        s3_geo.mkdir(parents=True)

        assignments_v3 = [
            {
                "name": "Medians and Altitudes",
                "due_date": "2026-03-06",
                "category": "Homework",
                "flags": {"missing": False, "late": True},
                "score_raw": "20/22",
                "points_earned": 20,
                "points_possible": 22,
                "percent": 91,
                "grade": "A-",
                "has_comments": False,
            },
            {
                "name": "IXL M7Q to 80",
                "due_date": "2026-03-10",
                "category": "Homework",
                "flags": {"missing": True, "late": False},
                "score_raw": "--/20",
                "points_earned": None,
                "points_possible": 20,
                "percent": None,
                "grade": None,
                "has_comments": False,
            },
        ]
        (s3_geo / "assignments.json").write_text(json.dumps(assignments_v3))

        metadata_v3 = {
            "date": "2026-03-12",
            "time": "160000",
            "scrape_timestamp": "2026-03-12T16:00:00+00:00",
            "classes": {
                "geometry": {
                    "course": "Geometry",
                    "teacher": "Smith, John",
                    "final_grade": "B",
                    "final_percent": 83,
                    "assignment_count": 2,
                },
                "english_10_honors": {
                    "course": "English 10 (Honors)",
                    "teacher": "Jones, Sarah",
                    "final_grade": "D-",
                    "final_percent": 63,
                    "assignment_count": 12,
                },
            },
        }
        (s3_dir / "metadata.json").write_text(json.dumps(metadata_v3))

        # Update rolling index to include third snapshot
        index_path = data_dir / "index" / "rolling_index.json"
        index_data = json.loads(index_path.read_text())
        index_data["snapshots"].append(
            {
                "date": "2026-03-12",
                "time": "160000",
                "scrape_timestamp": "2026-03-12T16:00:00+00:00",
                "previous_snapshot": "2026-03-10/150000",
                "changes": {
                    "class_level": 0,
                    "added": 0,
                    "modified": 0,
                    "deleted": 1,
                    "total": 1,
                },
                "classes": {
                    "geometry": {
                        "course": "Geometry",
                        "final_grade": "B",
                        "final_percent": 83,
                        "assignment_count": 2,
                    },
                    "english_10_honors": {
                        "course": "English 10 (Honors)",
                        "final_grade": "D-",
                        "final_percent": 63,
                        "assignment_count": 12,
                    },
                },
            }
        )
        index_path.write_text(json.dumps(index_data))

        reader = SnapshotReader(data_dir)
        result = get_deleted_assignments(reader, days=365)
        assert "Circumcenter Quiz" in result
        assert "deleted" in result

    def test_modified_assignments_retroactive(self, reader):
        # Between snapshot 1 and 2, Medians and Altitudes score changed 18/22 → 20/22
        # Both are real scores, so this should be detected as retroactive
        result = get_modified_assignments(reader, days=365)
        assert "Medians and Altitudes" in result
        assert "score_raw" in result or "percent" in result or "grade" in result

    def test_modified_assignments_filters_initial_grading(self, reader):
        # IXL M7Q was --/20 in snapshot 2 (unscored) — no prior version
        # It was added, not modified, so it shouldn't appear
        result = get_modified_assignments(reader, slug="geometry", days=365)
        assert "IXL M7Q" not in result

    def test_modified_assignments_class_filter(self, reader):
        result = get_modified_assignments(reader, slug="english_10_honors", days=365)
        assert "No retroactive" in result


# --- _is_unscored tests ---


class TestIsUnscored:
    def test_none_is_unscored(self):
        assert _is_unscored(None) is True

    def test_dashes_is_unscored(self):
        assert _is_unscored("--") is True

    def test_dash_score_is_unscored(self):
        assert _is_unscored("--/20") is True

    def test_zero_is_unscored(self):
        assert _is_unscored("0") is True

    def test_empty_is_unscored(self):
        assert _is_unscored("") is True

    def test_real_score_is_not_unscored(self):
        assert _is_unscored("18/22") is False

    def test_numeric_percent_is_not_unscored(self):
        assert _is_unscored(82) is False

    def test_grade_letter_is_not_unscored(self):
        assert _is_unscored("B+") is False

    def test_zero_score_with_denominator_is_not_unscored(self):
        assert _is_unscored("0/10") is False
