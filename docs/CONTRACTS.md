# Cross-Repo Contracts

Implicit data contracts between repos. Changes to either side must maintain these schemas or both sides must be updated together.

## 1. RPC Navigation Protocol

**Producer:** `assistant.py` → `_navigate_browser()`
**Consumer:** `table-mutation-tracker/frontend/components/AgentWidget.tsx` → `NavigationHandler`
**Transport:** LiveKit RPC method `navigateTo`

### Payload schema

```json
{
  "view": "day" | "calendar",
  "date": "YYYY-MM-DD" | "",
  "className": "<slug>" | "help" | "deleted" | "",
  "compareDate": "YYYY-MM-DD/HHMMSS" | undefined
}
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `view` | `"day"` or `"calendar"` | Yes | `"day"` when `date` is non-empty, `"calendar"` otherwise |
| `date` | string | Yes | ISO date (`2026-04-03`) or empty string for calendar view |
| `className` | string | Yes | Class slug (`geometry`), special route (`help`, `deleted`), or empty string |
| `compareDate` | string | No | `"YYYY-MM-DD/HHMMSS"` format (date + snapshot time). Only present for comparison views. |

### Routing rules (frontend)

| Condition | Route |
|-----------|-------|
| `className === "help"` | `/help` |
| `className === "deleted"` | `/deleted` |
| `view === "calendar"` | `/` |
| `date` is set | `/day/{date}?class={className}&compare={compareDate}` |

### Special className values

| Value | Meaning | Added |
|-------|---------|-------|
| `"help"` | Navigate to capabilities/help page | Phase 7 |
| `"deleted"` | Navigate to deleted assignments page | 2026-04-06 |

### Response

```json
{ "ok": true }
```

Always returns success. Navigation failures are silent on the frontend (the page may not exist, params may be invalid). The agent does not check the response.

### Who calls it

| Tool | className | date | compareDate |
|------|-----------|------|-------------|
| `list_assignments` | slug | latest | - |
| `get_class_summary` | slug | resolved or latest | - |
| `get_assignment_detail` | slug | latest | - |
| `compare_dates` | slug | date2 | date1/time1 |
| `get_flagged_assignments` | slug or "" | latest | - |
| `get_category_breakdown` | slug | latest | - |
| `get_deleted_assignments_list` | "deleted" | "" | - |
| `show_capabilities` | "help" | "" | - |
| `show_in_browser` | slug or "" | resolved or latest | - |

Non-navigating tools (`list_classes`, `get_recent_changes`, `get_grade_trend`, `get_overall_summary`, `get_score_changes`, `get_ungraded_assignments`, `save_user_profile`) do not call `_navigate_browser`.

---

## 2. Snapshot JSON Schema

**Producer:** `table-mutation-tracker` scraper → n8n → committed to `table-mutation-data`
**Consumer:** `sally-schoolwork` → `SnapshotReader` → `analysis.py`

### Directory structure

```
table-mutation-data/
  snapshots/
    {YYYY-MM-DD}/
      {HHMMSS}/
        metadata.json
        {class_slug}/
          assignments.json
  index/
    rolling_index.json
```

### assignments.json

Array of assignment objects. One file per class per snapshot.

```json
[
  {
    "name": "Medians and Altitudes",
    "due_date": "2026-03-06",
    "category": "Homework",
    "flags": { "missing": false, "late": false },
    "score_raw": "18/22",
    "points_earned": 18,
    "points_possible": 22,
    "percent": 82,
    "grade": "B-",
    "has_comments": false
  }
]
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Assignment name as displayed in SIS portal |
| `due_date` | string | Yes | `YYYY-MM-DD` format |
| `category` | string | Yes | Assignment category (Homework, Quizzes, Tests, etc.) |
| `flags` | object | Yes | Boolean flags: `missing`, `late`, `incomplete`, `exempt`, `absent` |
| `score_raw` | string | No | Raw score as displayed (`"18/22"`, `"--/20"`, `""`) |
| `points_earned` | float or null | No | Numeric points earned, null if unscored |
| `points_possible` | float or null | No | Numeric points possible |
| `percent` | float or null | No | Percentage score, null if unscored |
| `grade` | string or null | No | Letter grade, null if unscored |
| `has_comments` | boolean | No | Whether the assignment has teacher comments |

**Unscored detection:** An assignment is considered unscored if `score_raw` is null, empty, `"--"`, `"--/{N}"`, or `"0"` (standalone zero with no denominator). See `_is_unscored()` in `analysis.py`.

### metadata.json

One file per snapshot (shared across all classes).

```json
{
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
      "last_updated": "3/6/2026"
    }
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `date` | string | Snapshot date `YYYY-MM-DD` |
| `time` | string | Snapshot time `HHMMSS` |
| `scrape_timestamp` | string | ISO 8601 timestamp of when the scrape ran |
| `classes.{slug}` | object | Per-class metadata, keyed by slug |
| `classes.{slug}.course` | string | Display name ("Geometry", "English 10 (Honors)") |
| `classes.{slug}.teacher` | string | Teacher name ("Last, First") |
| `classes.{slug}.teacher_email` | string | Teacher email |
| `classes.{slug}.expression` | string | Class period/section |
| `classes.{slug}.term` | string | Academic term ("S2", "Q4") |
| `classes.{slug}.final_grade` | string or null | Current letter grade |
| `classes.{slug}.final_percent` | float or null | Current percentage |
| `classes.{slug}.assignment_count` | int | Number of assignments |
| `classes.{slug}.last_updated` | string or null | Last update date (M/D/YYYY format from SIS) |

### rolling_index.json

Pre-computed change counts across all snapshots.

```json
{
  "snapshots": [
    {
      "date": "2026-03-08",
      "time": "210000",
      "scrape_timestamp": "2026-03-08T21:00:00+00:00",
      "previous_snapshot": null,
      "changes": {
        "class_level": 0,
        "added": 0,
        "modified": 0,
        "deleted": 0,
        "total": 0
      },
      "classes": {
        "geometry": {
          "course": "Geometry",
          "final_grade": "B-",
          "final_percent": 80,
          "assignment_count": 2
        }
      }
    }
  ]
}
```

### Class slug conventions

Slugs are lowercase, underscore-separated, derived from the course name by the scraper. Examples:
- `geometry` ← "Geometry"
- `english_10_honors` ← "English 10 (Honors)"
- `ap_world_history` ← "AP World History"

The agent's `resolve_slug()` performs fuzzy matching: exact slug, exact course name, or partial match on either.
