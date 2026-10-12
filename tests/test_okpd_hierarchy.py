from database_work.database_id_fetcher import DatabaseIDFetcher


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.executions = []

    def execute(self, query, params=None):
        self.executions.append((query, params))

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.cursor_instance = FakeCursor(rows)

    def cursor(self):
        return self.cursor_instance


class FakeManager:
    def __init__(self, rows):
        self.connection = FakeConnection(rows)


def fetcher(rows):
    return DatabaseIDFetcher(FakeManager(rows))


def test_exact_match_wins():
    resolver = fetcher([(1, "43.99"), (2, "43.99.90")])
    assert resolver.resolve_allowed_okpd("43.99") == (1, "43.99", "EXACT")


def test_longest_segment_aligned_parent_wins():
    resolver = fetcher([(1, "43"), (2, "43.99")])
    assert resolver.resolve_allowed_okpd("43.99.90.190") == (2, "43.99", "PARENT")


def test_parent_match_does_not_cross_segment_boundary():
    resolver = fetcher([(1, "43.9")])
    assert resolver.resolve_allowed_okpd("43.90") is None


def test_non_whitelisted_and_malformed_codes_are_rejected():
    resolver = fetcher([(1, "43.99")])
    assert resolver.resolve_allowed_okpd("74.90.20.149") is None
    assert resolver.resolve_allowed_okpd("43.99.x") is None
    assert resolver.resolve_allowed_okpd("") is None


def test_whitelist_is_loaded_once():
    resolver = fetcher([(1, "43.99")])
    resolver.resolve_allowed_okpd("43.99.1")
    resolver.resolve_allowed_okpd("43.99.2")
    assert len(resolver.db_manager.connection.cursor_instance.executions) == 1
