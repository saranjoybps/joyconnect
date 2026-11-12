"""RLS checks against the real Supabase database (opt-in: RUN_DB_TESTS=1).

Everything runs inside one transaction that is rolled back.
"""

import json
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("RUN_DB_TESTS") != "1", reason="set RUN_DB_TESTS=1")


@pytest.fixture
def conn():
    import psycopg

    from scripts.apply_migrations import load_db_url

    with psycopg.connect(load_db_url(), connect_timeout=15) as c:
        yield c
        c.rollback()


def _as_user(cur, user_id):
    cur.execute("set local role authenticated")
    cur.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps({"sub": user_id, "role": "authenticated"}),))


def test_user_a_cannot_read_user_b(conn):
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    cur = conn.cursor()
    for uid in (a, b):
        cur.execute("insert into auth.users (id, email, aud, role) values (%s, %s, 'authenticated', 'authenticated')",
                    (uid, f"{uid}@rls.test"))
        cur.execute("insert into public.connections (user_id, provider, account_label, secret_id) "
                    "values (%s, 'slack', 'ws', 'sec')", (uid,))
        cur.execute("insert into public.conversations (user_id, title) values (%s, 't') returning id", (uid,))
        conv = cur.fetchone()[0]
        cur.execute("insert into public.messages (conversation_id, user_id, role, content) values (%s, %s, 'user', 'hi')",
                    (conv, uid))
        cur.execute("insert into public.secrets (user_id, nonce, ciphertext) values (%s, 'n', 'c')", (uid,))

    cur.execute("savepoint s")
    _as_user(cur, a)
    for table in ("connections_public", "conversations", "messages"):
        cur.execute(f"select distinct user_id::text from public.{table} where user_id in (%s, %s)", (a, b))
        assert [r[0] for r in cur.fetchall()] == [a], table

    # Writes are not allowed from clients.
    import psycopg

    for sql in ("insert into public.conversations (user_id) values (auth.uid())",
                "select secret_id from public.connections",
                "select * from public.secrets",
                "select * from public.oauth_states"):
        cur.execute("savepoint t")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(sql)
        cur.execute("rollback to savepoint t")

    # Non-secret columns of the base table are readable, own rows only.
    cur.execute("select count(*) from public.connections where user_id = %s", (b,))
    assert cur.fetchone()[0] == 0


def test_provider_apps_isolated_and_secret_columns_hidden(conn):
    import psycopg

    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    cur = conn.cursor()
    for uid in (a, b):
        cur.execute("insert into auth.users (id, email, aud, role) values (%s, %s, 'authenticated', 'authenticated')",
                    (uid, f"{uid}@rls.test"))
        cur.execute("insert into public.provider_apps (user_id, provider, client_id, secret_id) "
                    "values (%s, 'github', 'Iv-client', 'secret-pointer')", (uid,))
    _as_user(cur, a)
    cur.execute("select user_id::text from public.provider_apps where user_id in (%s, %s)", (a, b))
    assert [r[0] for r in cur.fetchall()] == [a]
    for sql in ("select client_id from public.provider_apps",
                "select secret_id from public.provider_apps",
                "select extra from public.provider_apps",
                "select redirect_uri from public.provider_apps",
                "insert into public.provider_apps (user_id, provider) values (auth.uid(), 'x')",
                "delete from public.provider_apps"):
        cur.execute("savepoint t")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(sql)
        cur.execute("rollback to savepoint t")


def test_memory_tables_are_private_and_read_only_for_clients(conn):
    """Migration 0008: memories, user_settings and llm_usage show a user only their own rows and cannot be written
    from the client."""
    import psycopg

    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    cur = conn.cursor()
    for uid in (a, b):
        cur.execute("insert into auth.users (id, email, aud, role) values (%s, %s, 'authenticated', 'authenticated')",
                    (uid, f"{uid}@rls.test"))
        cur.execute("insert into public.memories (user_id, content) values (%s, 'likes short answers')", (uid,))
        cur.execute("insert into public.user_settings (user_id) values (%s)", (uid,))
        cur.execute("insert into public.llm_usage (user_id, prompt_tokens) values (%s, 10)", (uid,))
    cur.execute("savepoint s")
    _as_user(cur, a)
    for table in ("memories", "user_settings", "llm_usage"):
        cur.execute(f"select distinct user_id::text from public.{table} where user_id in (%s, %s)", (a, b))
        assert [r[0] for r in cur.fetchall()] == [a], table
    for sql in ("insert into public.memories (user_id, content) values (auth.uid(), 'x')",
                "update public.memories set content = 'y'",
                "delete from public.memories",
                "update public.user_settings set memory_enabled = false",
                "insert into public.llm_usage (user_id) values (auth.uid())"):
        cur.execute("savepoint t")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(sql)
        cur.execute("rollback to savepoint t")
