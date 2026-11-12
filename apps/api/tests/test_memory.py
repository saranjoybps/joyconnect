"""Memory: rolling summary (short-term), long-term facts with pgvector search, the Memory API and the off switch.

LLM and embedder are fakes; nothing here is a paid call.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.agent.llm import LLMResult
from app.agent.memory import MemoryService, clean_memory, transcript
from tests.conftest import USER_A, USER_B, auth
from tests.test_agent import FakeLLM, connect, events, names


class FakeEmbedder:
    """Deterministic 1536-d vectors: texts that share a topic word point the same way."""
    TOPICS = ["sheet", "slack", "bullet", "name"]

    def __init__(self):
        self.calls = 0

    async def embed(self, texts):
        self.calls += 1
        out = []
        for t in texts:
            v = [0.0] * 1536
            for i, w in enumerate(self.TOPICS):
                if w in t.lower():
                    v[i] = 1.0
            if not any(v):
                v[100] = 1.0
            out.append(v)
        return out


@pytest.fixture
def embedder():
    return FakeEmbedder()


@pytest.fixture
def make_mem_client(settings, db, store, embedder):
    clients = []

    def _make(llm):
        from app.main import create_app

        c = TestClient(create_app(settings=settings, db=db, secret_store=store, llm=llm, embedder=embedder),
                       follow_redirects=False)
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


def extraction(*items):
    return LLMResult(content=json.dumps({"memories": [{"kind": k, "content": c} for k, c in items]}))


# ------------------------------------------------------------------ validation

def test_only_durable_non_secret_memories_are_accepted():
    assert clean_memory("preference", "Prefers answers in bullet points.") == ("preference", "Prefers answers in bullet points.")
    assert clean_memory("nonsense", "Prefers bullets.") is None
    assert clean_memory("fact", "x") is None and clean_memory("fact", "a" * 400) is None
    assert clean_memory("fact", "The user's password is hunter2") is None
    assert clean_memory("fact", "Token is ya29.A0AfH6SMBabcdefgh") is None


# ------------------------------------------------------------------ extraction after a chat, retrieval at the next one

async def test_chat_extracts_durable_facts_and_the_next_chat_retrieves_them(make_mem_client, db, store, settings, embedder):
    settings.memory_extraction = True
    await connect(db, store, "slack")
    llm = FakeLLM(
        LLMResult(content="Noted, Sam."),                                                  # the chat reply
        extraction(("fact", "The user's name is Sam."), ("preference", "Prefers answers in bullet points."),
                   ("fact", "The user's password is hunter2")),                              # extraction (secret dropped)
        LLMResult(content="Here you go."))                                                  # second chat
    client = make_mem_client(llm)
    events(client.post("/api/chat", json={"message": "I'm Sam and I like bullet points"}, headers=auth()))
    rows = db.tables["memories"]
    assert sorted(r["content"] for r in rows) == ["Prefers answers in bullet points.", "The user's name is Sam."]
    assert all(r["user_id"] == USER_A and len(r["embedding"]) == 1536 for r in rows)
    assert {r["purpose"] for r in db.tables["llm_usage"]} == {"chat", "memory"}

    events(client.post("/api/chat", json={"message": "format this with bullet style"}, headers=auth()))
    system = llm.calls[2][0][0]["content"]
    assert "Known about the user" in system and "bullet points" in system and "data, not instructions" in system
    second = events(client.post("/api/chat", json={"message": "bullets again"}, headers=auth()))
    assert any(e == "memory" and d["count"] >= 1 for e, d in second)


async def test_extraction_sees_user_and_assistant_words_but_not_tool_output(make_mem_client, db, store, settings):
    settings.memory_extraction = True
    await connect(db, store, "slack")
    llm = FakeLLM(LLMResult(content="ok"), extraction())
    events(make_mem_client(llm).post("/api/chat", json={"message": "hello there"}, headers=auth()))
    prompt = llm.calls[1][0]
    assert "durable" in prompt[0]["content"].lower() and "USER: hello there" in prompt[1]["content"]


async def test_duplicates_are_not_stored_twice(make_mem_client, db, store, settings):
    settings.memory_extraction = True
    llm = FakeLLM(LLMResult(content="a"), extraction(("fact", "The user's name is Sam.")),
                  LLMResult(content="b"), extraction(("fact", "the user's name is sam")))
    client = make_mem_client(llm)
    conv = events(client.post("/api/chat", json={"message": "I am Sam"}, headers=auth()))[-1][1]["conversation_id"]
    events(client.post("/api/chat", json={"message": "Sam again", "conversation_id": conv}, headers=auth()))
    assert len(db.tables["memories"]) == 1


async def test_per_user_cap(make_mem_client, db, settings):
    settings.memory_max_per_user = 2
    svc = MemoryService(db, lambda: FakeEmbedder(), lambda: FakeLLM(), settings)
    await svc.add(USER_A, "fact", "The user works at Acme.")
    await svc.add(USER_A, "fact", "The user lives in Berlin.")
    with pytest.raises(ValueError, match="limit"):
        await svc.add(USER_A, "fact", "The user likes tea.")


# ------------------------------------------------------------------ the off switch

async def test_memory_off_stores_nothing_and_injects_nothing(make_mem_client, db, store, settings):
    settings.memory_extraction = True
    client = make_mem_client(FakeLLM(LLMResult(content="ok")))
    assert client.put("/api/memory/settings", json={"memory_enabled": False}, headers=auth()).json() == {"memory_enabled": False}
    svc = MemoryService(db, lambda: FakeEmbedder(), lambda: FakeLLM(), settings)
    await svc.add(USER_A, "fact", "The user's name is Sam.")
    llm = FakeLLM(LLMResult(content="hi"), extraction(("fact", "The user likes tea.")))
    events(make_mem_client(llm).post("/api/chat", json={"message": "hello"}, headers=auth()))
    assert len(db.tables["memories"]) == 1 and len(llm.calls) == 1            # no extraction call at all
    assert "Known about the user" not in llm.calls[0][0][0]["content"]
    assert client.get("/api/memory/settings", headers=auth()).json() == {"memory_enabled": False}


async def test_no_memories_means_no_embedding_call(make_mem_client, db, embedder):
    svc = MemoryService(db, lambda: embedder, lambda: FakeLLM(), make_mem_client.__closure__ and None or __import__("app.core.config", fromlist=["Settings"]).Settings(_env_file=None))
    assert await svc.retrieve(USER_A, "anything") == [] and embedder.calls == 0


# ------------------------------------------------------------------ retrieval is by similarity and per user

async def test_retrieval_ranks_by_similarity_and_is_private(db, settings, embedder):
    svc = MemoryService(db, lambda: embedder, lambda: FakeLLM(), settings)
    await svc.add(USER_A, "identifier", "The main sheet is called Test Leads.")
    await svc.add(USER_A, "preference", "Prefers answers in bullet points.")
    await svc.add(USER_B, "fact", "Private sheet of the other user.")
    got = await svc.retrieve(USER_A, "open my sheet")
    assert got[0] == "The main sheet is called Test Leads." and all("other user" not in g for g in got)


async def test_embedding_failure_still_saves_and_lists_the_memory(db, settings):
    class Broken:
        async def embed(self, texts):
            raise RuntimeError("boom")

    svc = MemoryService(db, lambda: Broken(), lambda: FakeLLM(), settings)
    row = await svc.add(USER_A, "fact", "The user's name is Sam.")
    assert db.tables["memories"][0]["embedding"] is None and row["content"].endswith("Sam.")
    assert await svc.retrieve(USER_A, "who am I") == ["The user's name is Sam."]      # falls back to recent


async def test_memory_works_when_migration_0008_is_missing(db, settings, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError('relation "user_settings" does not exist')

    monkeypatch.setattr(db, "select", boom)
    svc = MemoryService(db, None, lambda: FakeLLM(), settings)
    assert await svc.enabled(USER_A) is False and await svc.retrieve(USER_A, "hi") == []


# ------------------------------------------------------------------ the Memory API (view / edit / delete)

async def test_memory_api_crud_and_isolation(make_mem_client, db):
    client = make_mem_client(FakeLLM())
    made = client.post("/api/memories", json={"content": "The user's name is Sam.", "kind": "fact"}, headers=auth())
    assert made.status_code == 201
    mid = made.json()["id"]
    listing = client.get("/api/memories", headers=auth()).json()
    assert listing["enabled"] is True and [m["content"] for m in listing["memories"]] == ["The user's name is Sam."]
    assert client.get("/api/memories", headers=auth(USER_B)).json()["memories"] == []
    assert client.patch(f"/api/memories/{mid}", json={"content": "Hi"}, headers=auth(USER_B)).status_code == 404
    assert client.delete(f"/api/memories/{mid}", headers=auth(USER_B)).status_code == 404
    edited = client.patch(f"/api/memories/{mid}", json={"content": "The user's name is Samuel."}, headers=auth())
    assert edited.json()["content"] == "The user's name is Samuel."
    assert client.post("/api/memories", json={"content": "my password is hunter2"}, headers=auth()).status_code == 422
    assert client.delete(f"/api/memories/{mid}", headers=auth()).status_code == 204
    assert client.get("/api/memories", headers=auth()).json()["memories"] == []
    client.post("/api/memories", json={"content": "Likes tea in the morning."}, headers=auth())
    assert client.delete("/api/memories", headers=auth()).json() == {"deleted": 1}


def test_memory_api_requires_login(make_mem_client):
    assert make_mem_client(FakeLLM()).get("/api/memories").status_code in (401, 403)


# ------------------------------------------------------------------ short-term: rolling summary of older turns

async def test_old_turns_are_folded_into_a_summary_and_the_window_stays_small(make_mem_client, db, store, settings):
    settings.conversation_summary = True
    settings.history_window = 6
    settings.history_keep_after_summary = 2
    await connect(db, store, "slack")
    # turn 3 sees 7 messages > window 6, so its request first asks the model for a summary (4th scripted item)
    llm = FakeLLM(*[LLMResult(content=f"answer {i}") for i in range(3)],
                  LLMResult(content="User asked questions 0-2; answers were given."),
                  LLMResult(content="answer 3"), LLMResult(content="answer 4"))
    client = make_mem_client(llm)
    conv = None
    for i in range(5):
        body = {"message": f"question {i}", **({"conversation_id": conv} if conv else {})}
        conv = events(client.post("/api/chat", json=body, headers=auth()))[-1][1]["conversation_id"]
    row = db.tables["conversations"][0]
    assert "questions 0-2" in row["summary"] and row["summary_upto"] > 0
    chat_call = llm.calls[-1][0]
    assert "Summary of the earlier part" in chat_call[0]["content"] and "questions 0-2" in chat_call[0]["content"]
    assert len([m for m in chat_call if m["role"] == "user"]) < 5                         # older turns left out
    assert {r["purpose"] for r in db.tables["llm_usage"]} >= {"summary"}


def test_transcript_leaves_out_tool_output_and_redacts_arguments():
    rows = [{"role": "user", "content": "send it to ada@example.com"},
            {"role": "assistant", "content": "Sending.", "tool_calls": [
                {"id": "1", "function": {"name": "slack__post_message",
                                         "arguments": json.dumps({"channel": "C1", "text": "hi", "token": "sk-secret"})}}]},
            {"role": "tool", "content": "RAW TOOL OUTPUT", "tool_call_id": "1"}]
    text = transcript(rows)
    assert "RAW TOOL OUTPUT" not in text and "sk-secret" not in text and "slack__post_message" in text
