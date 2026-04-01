"""Unit tests for UserStore — Supabase profile and session persistence.

Uses a mock Supabase client to test all UserStore methods without
network access or a real database.
"""

from unittest.mock import MagicMock, patch

from data.user_store import UserStore, get_supabase_client

# --- Mock helpers ---


def _mock_client():
    """Create a mock Supabase client with chainable table methods.

    Returns (client, tables) where tables is a dict of table name -> mock.
    The same mock is returned for repeated calls to client.table(name).
    """
    client = MagicMock()
    tables = {}

    def _table(name):
        if name not in tables:
            table = MagicMock()
            table.select.return_value = table
            table.eq.return_value = table
            table.order.return_value = table
            table.limit.return_value = table
            table.insert.return_value = table
            table.upsert.return_value = table
            table.execute.return_value = MagicMock(data=[])
            tables[name] = table
        return tables[name]

    client.table = MagicMock(side_effect=_table)
    # Pre-populate so tests can configure before UserStore calls
    for name in ("user_profiles", "session_history", "session_messages"):
        _table(name)
    return client, tables


# --- get_supabase_client ---


class TestGetSupabaseClient:
    def test_returns_none_without_env(self):
        with patch.dict("os.environ", {}, clear=True):
            assert get_supabase_client() is None

    def test_returns_none_with_partial_env(self):
        with patch.dict(
            "os.environ", {"SUPABASE_URL": "https://example.com"}, clear=True
        ):
            assert get_supabase_client() is None


# --- Profile methods ---


class TestGetProfile:
    def test_returns_profile_when_found(self):
        client, tables = _mock_client()
        profile_data = {
            "device_id": "test-device",
            "name": "Alice",
            "relation_to_student": "parent",
        }
        # Configure after first access so the mock is the same instance
        store = UserStore(client)
        tables["user_profiles"].execute.return_value = MagicMock(data=[profile_data])
        result = store.get_profile("test-device")

        assert result == profile_data

    def test_returns_none_when_not_found(self):
        client, _ = _mock_client()
        store = UserStore(client)
        result = store.get_profile("nonexistent")
        assert result is None


class TestSaveProfile:
    def test_saves_full_profile(self):
        client, tables = _mock_client()
        tables["user_profiles"].execute.return_value = MagicMock(
            data=[{"device_id": "d1", "name": "Bob"}]
        )

        store = UserStore(client)
        result = store.save_profile(
            device_id="d1",
            name="Bob",
            gender="male",
            relation_to_student="parent",
            priorities=["grades", "missing"],
            communication_preferences="brief",
        )

        assert result["name"] == "Bob"
        call_args = tables["user_profiles"].upsert.call_args[0][0]
        assert call_args["device_id"] == "d1"
        assert call_args["name"] == "Bob"
        assert call_args["gender"] == "male"
        assert call_args["priorities"] == ["grades", "missing"]

    def test_saves_partial_profile(self):
        client, tables = _mock_client()
        tables["user_profiles"].execute.return_value = MagicMock(
            data=[{"device_id": "d1", "name": "Alice"}]
        )

        store = UserStore(client)
        store.save_profile(device_id="d1", name="Alice")

        call_args = tables["user_profiles"].upsert.call_args[0][0]
        assert call_args["device_id"] == "d1"
        assert call_args["name"] == "Alice"
        assert "gender" not in call_args
        assert "priorities" not in call_args

    def test_skips_none_values(self):
        client, tables = _mock_client()
        tables["user_profiles"].execute.return_value = MagicMock(
            data=[{"device_id": "d1"}]
        )

        store = UserStore(client)
        store.save_profile(device_id="d1", name=None, gender=None)

        call_args = tables["user_profiles"].upsert.call_args[0][0]
        assert "name" not in call_args
        assert "gender" not in call_args


# --- Session history ---


class TestSessionHistory:
    def test_get_recent_sessions_returns_reversed(self):
        client, tables = _mock_client()
        tables["session_history"].execute.return_value = MagicMock(
            data=[
                {"session_date": "2026-03-29", "summary": "Newer"},
                {"session_date": "2026-03-28", "summary": "Older"},
            ]
        )

        store = UserStore(client)
        result = store.get_recent_sessions("d1", limit=5)

        assert result[0]["summary"] == "Older"
        assert result[1]["summary"] == "Newer"

    def test_get_recent_sessions_empty(self):
        client, _ = _mock_client()
        store = UserStore(client)
        result = store.get_recent_sessions("d1")
        assert result == []

    def test_save_session_with_topics(self):
        client, tables = _mock_client()

        store = UserStore(client)
        store.save_session(
            device_id="d1",
            summary="Discussed geometry grades",
            topics_discussed=["grades", "geometry"],
            classes_mentioned=["geometry"],
        )

        call_args = tables["session_history"].insert.call_args[0][0]
        assert call_args["device_id"] == "d1"
        assert call_args["summary"] == "Discussed geometry grades"
        assert call_args["topics_discussed"] == ["grades", "geometry"]
        assert call_args["classes_mentioned"] == ["geometry"]

    def test_save_session_minimal(self):
        client, tables = _mock_client()

        store = UserStore(client)
        store.save_session(device_id="d1", summary="Short chat")

        call_args = tables["session_history"].insert.call_args[0][0]
        assert call_args["device_id"] == "d1"
        assert call_args["summary"] == "Short chat"
        assert "topics_discussed" not in call_args


# --- Session messages ---


class TestSessionMessages:
    def test_save_message(self):
        client, tables = _mock_client()

        store = UserStore(client)
        store.save_message("d1", "session-123", "user", "Hello")

        call_args = tables["session_messages"].insert.call_args[0][0]
        assert call_args["device_id"] == "d1"
        assert call_args["session_id"] == "session-123"
        assert call_args["role"] == "user"
        assert call_args["content"] == "Hello"

    def test_get_session_messages(self):
        client, tables = _mock_client()
        tables["session_messages"].execute.return_value = MagicMock(
            data=[
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello!"},
            ]
        )

        store = UserStore(client)
        result = store.get_session_messages("session-123")

        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"

    def test_get_session_messages_empty(self):
        client, _ = _mock_client()
        store = UserStore(client)
        result = store.get_session_messages("nonexistent")
        assert result == []


# --- Format methods ---


class TestFormatMethods:
    def test_format_profile_context_full(self):
        store = UserStore(MagicMock())
        result = store.format_profile_context(
            {
                "name": "Dave",
                "relation_to_student": "parent",
                "communication_preferences": "brief",
                "priorities": ["missing assignments", "grade trends"],
            }
        )
        assert "Dave" in result
        assert "parent" in result
        assert "brief" in result
        assert "missing assignments" in result

    def test_format_profile_context_empty(self):
        store = UserStore(MagicMock())
        result = store.format_profile_context({})
        assert result == ""

    def test_format_profile_context_partial(self):
        store = UserStore(MagicMock())
        result = store.format_profile_context({"name": "Alice"})
        assert "Alice" in result
        assert "parent" not in result

    def test_format_session_context(self):
        store = UserStore(MagicMock())
        result = store.format_session_context(
            [
                {"session_date": "2026-03-28T10:00:00", "summary": "Talked about math"},
                {
                    "session_date": "2026-03-29T14:00:00",
                    "summary": "Checked English",
                },
            ]
        )
        assert "Previous conversations" in result
        assert "2026-03-28" in result
        assert "Talked about math" in result
        assert "Checked English" in result

    def test_format_session_context_empty(self):
        store = UserStore(MagicMock())
        result = store.format_session_context([])
        assert result == ""
