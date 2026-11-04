"""A scripted fake psycopg connection for unit-testing the Repository's SQL paths.

Each test gives ``FakeConnection`` a ``results`` mapping from a SQL substring to the row(s)
that substring's query should return, and afterwards inspects ``statements`` to assert the
calls were parameterized. Available to tests through the ``make_connection`` fixture.
"""

from __future__ import annotations

import pytest


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeCursor:
    def __init__(self, connection: FakeConnection):
        self._conn = connection
        self._result = None

    def execute(self, sql, params=()):
        self._conn.statements.append((sql, params))
        self._result = self._conn.script(sql)

    def fetchone(self):
        result = self._result
        if result is None:
            return None
        if isinstance(result, list):
            return result[0] if result else None
        return result

    def fetchall(self):
        result = self._result
        if result is None:
            return []
        if isinstance(result, list):
            return result
        return [result]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, results=None):
        self.results = results or {}
        self.statements = []

    def cursor(self):
        return FakeCursor(self)

    def transaction(self):
        return _NullContext()

    def script(self, sql):
        for key, value in self.results.items():
            if key in sql:
                return value
        return None


@pytest.fixture
def make_connection():
    return FakeConnection
