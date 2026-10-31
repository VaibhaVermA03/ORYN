"""Test harness: real PostgreSQL (needed for full-text search), mocked external providers.

Set TEST_DATABASE_URL to an empty PostgreSQL database dedicated to tests. The schema is
created by running the real Alembic migrations once per test session, so migrations are
exercised on every run.
"""

from __future__ import annotations

import os
import uuid

import pytest

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://oryn:oryn@localhost:5432/oryn_test")

os.environ.update(
    {
        "APP_ENV": "test",
        "APP_SECRET": "test-secret-test-secret-test-secret-0123456789",
        "DATABASE_URL": TEST_DB_URL,
        "FRONTEND_ORIGINS": "http://localhost:5173",
        "OPENAI_API_KEY": "",
        "PINECONE_API_KEY": "",
        "COHERE_API_KEY": "",
        "GOOGLE_CLIENT_ID": "test-client-id.apps.googleusercontent.com",
        "GOOGLE_CLIENT_SECRET": "test-client-secret",
        "RATE_LIMIT_AUTH_PER_MINUTE": "1000",
        "INGESTION_WORKER_MODE": "off",
        "EMBEDDING_DIMENSIONS": "64",
        "STORAGE_DIR": "./.test_storage",
        "TEMP_DIR": "./.test_tmp",
    }
)

from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from alembic import command  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.rate_limit import limiter  # noqa: E402
from app.db.session import get_engine, reset_engine, session_factory  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    get_settings.cache_clear()
    reset_engine()
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.upgrade(cfg, "head")
    yield
    reset_engine()


@pytest.fixture(autouse=True)
def _clean_db(_schema):
    engine = get_engine()
    with engine.begin() as conn:
        tables = conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'")
        ).scalars().all()
        if tables:
            conn.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE"))
    limiter.reset()
    yield


@pytest.fixture
def db():
    s = session_factory()()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def client():
    from app.main import create_app

    app = create_app()
    with TestClient(app, base_url="http://testserver") as c:
        yield c


CSRF = {"X-Requested-By": "oryn-web", "Origin": "http://localhost:5173"}


def signup(client: TestClient, email: str | None = None, name: str = "Test User", password: str = "correct-horse-9"):
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/api/v1/auth/signup", json={"email": email, "password": password, "display_name": name})
    assert r.status_code == 201, r.text
    body = r.json()
    return email, body["access_token"], body


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def make_user(client):
    """Creates an independent user with its own cookie-less access token."""
    from app.main import create_app

    def _make(name: str = "User"):
        # Use a separate client per user so cookies do not mix.
        with TestClient(create_app(), base_url="http://testserver") as c:
            email, token, body = signup(c, name=name)
        return {"email": email, "token": token, "id": body["user"]["id"], "headers": auth(token)}

    return _make


# ------------------------------------------------------------------ provider fixtures
from types import SimpleNamespace  # noqa: E402


@pytest.fixture
def providers(tmp_path, monkeypatch):
    """Install in-memory fakes for embeddings, vector storage and file storage."""
    from app.services.embedding_service import set_embedder
    from app.services.llm_service import set_llm
    from app.services.reranking_service import set_reranker
    from app.services.storage_service import LocalStorage, set_storage
    from app.services.vector_service import set_vector_store
    from tests.fakes import FakeEmbedder, FakeLLM, FakeReranker, FakeVectorStore

    embedder, store = FakeEmbedder(), FakeVectorStore()
    reranker, llm = FakeReranker(), FakeLLM()
    storage = LocalStorage(str(tmp_path / "storage"), str(tmp_path / "tmp"))
    set_embedder(embedder)
    set_vector_store(store)
    set_storage(storage)
    set_reranker(reranker)
    set_llm(llm)
    yield SimpleNamespace(embedder=embedder, store=store, storage=storage, root=tmp_path / "storage",
                          reranker=reranker, llm=llm)
    set_reranker(None)
    set_llm(None)
    set_embedder(None)
    set_vector_store(None)
    set_storage(None)


def run_worker(max_docs: int = 20) -> list[str]:
    """Drain the ingestion queue synchronously (what the background worker does in production)."""
    from app.services.ingestion_service import claim_next_document, process_document

    outcomes = []
    for _ in range(max_docs):
        doc_id = claim_next_document()
        if doc_id is None:
            break
        outcomes.append(process_document(doc_id))
    return outcomes


def personal_workspace(client, headers) -> str:
    return client.get("/api/v1/workspaces", headers=headers).json()[0]["id"]
