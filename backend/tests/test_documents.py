from __future__ import annotations

import io
from datetime import timedelta

import pymupdf
import pytest
from docx import Document as DocxDocument
from sqlalchemy import select

from app.core.config import get_settings
from app.core.exceptions import ProviderError
from app.db.base import utcnow
from app.db.models import Chunk, Document, DocumentStatus
from app.services.ingestion_service import recover_stale_documents
from app.services.storage_service import sanitize_filename
from tests.conftest import personal_workspace, run_worker


def make_pdf(pages: list[str]) -> bytes:
    pdf = pymupdf.open()
    for text in pages:
        page = pdf.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 550, 780), text, fontsize=11)
    data = pdf.tobytes()
    pdf.close()
    return data


def make_docx(paragraphs: list[str], table: list[list[str]] | None = None) -> bytes:
    d = DocxDocument()
    for p in paragraphs:
        d.add_paragraph(p)
    if table:
        t = d.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, val in enumerate(row):
                t.cell(r, c).text = val
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def upload(client, headers, ws, name, data, content_type="application/octet-stream"):
    return client.post(
        f"/api/v1/workspaces/{ws}/documents", headers=headers, files=[("files", (name, io.BytesIO(data), content_type))]
    )


@pytest.fixture
def user_ws(client, make_user, providers):
    u = make_user("Docs User")
    return u, personal_workspace(client, u["headers"])


def test_txt_upload_is_processed_to_ready_with_vectors(client, user_ws, providers, db):
    u, ws = user_ws
    r = upload(client, u["headers"], ws, "policy.txt", b"Refunds are issued within 14 days of purchase.\n\nShipping is free over $50.")
    assert r.status_code == 200
    res = r.json()["results"][0]
    assert res["accepted"] and res["document"]["status"] == "uploaded" and res["document"]["file_type"] == "txt"
    assert run_worker() == ["ready"]
    detail = client.get(f"/api/v1/workspaces/{ws}/documents/{res['document']['id']}", headers=u["headers"]).json()
    assert detail["status"] == "ready" and detail["chunk_count"] >= 1 and detail["indexed_at"]
    ns = get_settings().namespace_for(ws)
    assert providers.store.count(ns) == detail["chunk_count"]
    meta = next(iter(providers.store.namespaces[ns].values())).metadata
    assert meta["workspace_id"] == ws and meta["document_id"] == res["document"]["id"]
    assert {"chunk_id", "filename", "chunk_index", "page_number", "content_hash", "ingestion_version"} <= set(meta)
    chunk = db.execute(select(Chunk)).scalars().first()
    assert chunk.vector_id.startswith(res["document"]["id"]) and chunk.ingestion_version == 1


def test_pdf_pages_are_preserved_in_chunk_metadata(client, user_ws, providers, db):
    u, ws = user_ws
    pdf = make_pdf(["Page one discusses onboarding and laptops.", "Page two discusses expense reimbursement."])
    upload(client, u["headers"], ws, "handbook.pdf", pdf, "application/pdf")
    assert run_worker() == ["ready"]
    chunks = db.execute(select(Chunk).order_by(Chunk.chunk_index)).scalars().all()
    assert [c.page_number for c in chunks] == [1, 2]
    assert "onboarding" in chunks[0].text and "expense" in chunks[1].text
    doc = db.execute(select(Document)).scalar_one()
    assert doc.page_count == 2


def test_docx_text_and_tables_are_extracted(client, user_ws, providers, db):
    u, ws = user_ws
    data = make_docx(["Security policy overview."], table=[["Role", "Access"], ["Admin", "Full"]])
    upload(client, u["headers"], ws, "sec.docx", data)
    assert run_worker() == ["ready"]
    text = " ".join(c.text for c in db.execute(select(Chunk)).scalars())
    assert "Security policy overview." in text and "Admin | Full" in text


@pytest.mark.parametrize(
    "name,data,code",
    [
        ("virus.exe", b"MZ\x90\x00", "unsupported_type"),
        ("fake.pdf", b"this is not a pdf at all", "content_mismatch"),
        ("fake.docx", b"plain text pretending", "content_mismatch"),
        ("empty.txt", b"", "empty_file"),
        ("binary.txt", b"\x00\x01\x02\x03binary", "content_mismatch"),
        ("noext", b"hello", "unsupported_type"),
    ],
)
def test_upload_validation_rejects_bad_files(client, user_ws, providers, name, data, code):
    u, ws = user_ws
    r = upload(client, u["headers"], ws, name, data)
    result = r.json()["results"][0]
    assert r.status_code == 200 and result["accepted"] is False and result["error"]["code"] == code
    assert not list(providers.root.rglob("*.*"))  # rejected uploads leave no files behind


def test_oversize_file_rejected_without_storing(client, user_ws, providers, monkeypatch):
    u, ws = user_ws
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 1024)
    result = upload(client, u["headers"], ws, "big.txt", b"a" * 5000).json()["results"][0]
    assert result["accepted"] is False and result["error"]["code"] == "payload_too_large"
    assert not list(providers.root.rglob("*.txt"))


def test_too_many_files_rejected(client, user_ws, providers, monkeypatch):
    u, ws = user_ws
    monkeypatch.setattr(get_settings(), "max_files_per_request", 2)
    files = [("files", (f"f{i}.txt", io.BytesIO(f"doc {i}".encode()), "text/plain")) for i in range(3)]
    r = client.post(f"/api/v1/workspaces/{ws}/documents", headers=u["headers"], files=files)
    assert r.status_code == 422 and r.json()["error"]["code"] == "too_many_files"


def test_unreadable_pdf_ends_failed_with_actionable_error(client, user_ws, providers):
    u, ws = user_ws
    bad = b"%PDF-1.4\n" + b"garbage" * 50
    upload(client, u["headers"], ws, "broken.pdf", bad)
    assert run_worker() == ["failed"]
    doc = client.get(f"/api/v1/workspaces/{ws}/documents", headers=u["headers"]).json()["items"][0]
    assert doc["status"] == "failed" and doc["error_summary"] and doc["chunk_count"] == 0
    assert providers.store.count(get_settings().namespace_for(ws)) == 0


def test_pdf_without_text_reports_ocr_hint(client, user_ws, providers):
    u, ws = user_ws
    blank = pymupdf.open()
    blank.new_page()
    upload(client, u["headers"], ws, "scan.pdf", blank.tobytes())
    assert run_worker() == ["failed"]
    doc = client.get(f"/api/v1/workspaces/{ws}/documents", headers=u["headers"]).json()["items"][0]
    assert "No extractable text" in doc["error_summary"]


def test_duplicate_content_rejected_per_workspace_but_allowed_across_workspaces(client, user_ws, providers):
    u, ws = user_ws
    assert upload(client, u["headers"], ws, "a.txt", b"identical content here").json()["results"][0]["accepted"]
    dup = upload(client, u["headers"], ws, "renamed.txt", b"identical content here").json()["results"][0]
    assert dup["accepted"] is False and dup["error"]["code"] == "duplicate_document"
    ws2 = client.post("/api/v1/workspaces", json={"name": "Second"}, headers=u["headers"]).json()["id"]
    assert upload(client, u["headers"], ws2, "a.txt", b"identical content here").json()["results"][0]["accepted"]


def test_filename_sanitization():
    assert sanitize_filename("../../etc/passwd.txt") == "passwd.txt"
    assert sanitize_filename("C:\\Users\\x\\report.pdf") == "report.pdf"
    assert sanitize_filename("evil\x00name\n.txt") == "evilname.txt"
    assert sanitize_filename("...") == "document"
    assert len(sanitize_filename("a" * 400 + ".pdf")) <= 200 and sanitize_filename("a" * 400 + ".pdf").endswith(".pdf")


def test_stored_path_is_server_controlled(client, user_ws, providers, db):
    u, ws = user_ws
    upload(client, u["headers"], ws, "../../../etc/passwd.txt", b"hello world")
    doc = db.execute(select(Document)).scalar_one()
    assert doc.filename == "passwd.txt" and doc.storage_key == f"{ws}/{doc.id}.txt"
    assert (providers.root / doc.storage_key).exists()


def test_retryable_provider_failure_retries_then_succeeds(client, user_ws, providers, db):
    u, ws = user_ws
    upload(client, u["headers"], ws, "r.txt", b"retry me please")
    providers.embedder.fail_with = ProviderError("openai", "rate limited", retryable=True)
    providers.embedder.fail_times = 2
    outcomes = []
    for _ in range(3):
        outcomes += run_worker()
        db.expire_all()  # the worker commits in its own sessions
        for d in db.execute(select(Document)).scalars():  # skip the backoff delay
            if d.status == DocumentStatus.uploaded:
                d.locked_at = None
        db.commit()
    assert outcomes == ["retry", "retry", "ready"]
    doc = db.execute(select(Document)).scalar_one()
    db.refresh(doc)
    assert doc.status == DocumentStatus.ready and doc.attempts == 3 and doc.error_summary is None


def test_retries_are_bounded_and_failure_cleans_up(client, user_ws, providers, db):
    u, ws = user_ws
    upload(client, u["headers"], ws, "r.txt", b"always failing")
    providers.embedder.fail_with = ProviderError("openai", "down", retryable=True)
    outcomes = []
    for _ in range(5):
        outcomes += run_worker()
        db.expire_all()
        for d in db.execute(select(Document)).scalars():
            if d.status == DocumentStatus.uploaded:
                d.locked_at = None
        db.commit()
    assert outcomes[-1] == "failed" and outcomes.count("retry") == 2
    db.expire_all()
    doc = db.execute(select(Document)).scalar_one()
    assert doc.status == DocumentStatus.failed and doc.attempts == 3
    assert db.execute(select(Chunk)).first() is None


def test_non_retryable_failure_fails_immediately(client, user_ws, providers, db):
    u, ws = user_ws
    upload(client, u["headers"], ws, "r.txt", b"bad key")
    providers.embedder.fail_with = ProviderError("openai", "The OpenAI API key is invalid.", retryable=False)
    assert run_worker() == ["failed"]
    doc = db.execute(select(Document)).scalar_one()
    assert doc.attempts == 1 and "API key" in doc.error_summary


def test_failed_upsert_never_marks_document_ready(client, user_ws, providers, db):
    u, ws = user_ws
    upload(client, u["headers"], ws, "r.txt", b"upsert will fail")
    providers.store.fail_upsert = ProviderError("pinecone", "unavailable", retryable=False)
    assert run_worker() == ["failed"]
    db.expire_all()
    doc = db.execute(select(Document)).scalar_one()
    assert doc.status == DocumentStatus.failed and doc.chunk_count == 0
    assert providers.store.count(get_settings().namespace_for(ws)) == 0


def test_reindex_does_not_duplicate_vectors(client, user_ws, providers):
    u, ws = user_ws
    text = ("Reindex paragraph about policy. " * 40 + "\n\n") * 6
    doc_id = upload(client, u["headers"], ws, "big.txt", text.encode()).json()["results"][0]["document"]["id"]
    run_worker()
    ns = get_settings().namespace_for(ws)
    before = providers.store.count(ns)
    assert before > 1
    r = client.post(f"/api/v1/workspaces/{ws}/documents/{doc_id}/reindex", headers=u["headers"])
    assert r.status_code == 202 and r.json()["status"] == "uploaded"
    assert client.post(f"/api/v1/workspaces/{ws}/documents/{doc_id}/reindex", headers=u["headers"]).status_code == 409
    assert run_worker() == ["ready"]
    assert providers.store.count(ns) == before


def test_delete_removes_vectors_chunks_and_file(client, user_ws, providers, db):
    u, ws = user_ws
    doc_id = upload(client, u["headers"], ws, "d.txt", b"delete me").json()["results"][0]["document"]["id"]
    run_worker()
    ns = get_settings().namespace_for(ws)
    assert providers.store.count(ns) == 1 and list(providers.root.rglob("*.txt"))
    assert client.delete(f"/api/v1/workspaces/{ws}/documents/{doc_id}", headers=u["headers"]).status_code == 204
    assert providers.store.count(ns) == 0
    assert db.execute(select(Chunk)).first() is None and db.execute(select(Document)).first() is None
    assert not list(providers.root.rglob("*.txt"))
    assert client.get(f"/api/v1/workspaces/{ws}/documents/{doc_id}", headers=u["headers"]).status_code == 404


def test_delete_aborts_when_vector_cleanup_fails(client, user_ws, providers, db):
    u, ws = user_ws
    doc_id = upload(client, u["headers"], ws, "d.txt", b"keep me").json()["results"][0]["document"]["id"]
    run_worker()
    providers.store.fail_delete = ProviderError("pinecone", "The vector database is temporarily unavailable.", retryable=True)
    r = client.delete(f"/api/v1/workspaces/{ws}/documents/{doc_id}", headers=u["headers"])
    assert r.status_code == 502 and r.json()["error"]["code"] == "provider_error"
    assert db.execute(select(Document)).scalar_one().status == DocumentStatus.ready  # nothing half-deleted
    providers.store.fail_delete = None
    assert client.delete(f"/api/v1/workspaces/{ws}/documents/{doc_id}", headers=u["headers"]).status_code == 204


def test_cannot_delete_document_while_actively_processing(client, user_ws, providers, db):
    u, ws = user_ws
    doc_id = upload(client, u["headers"], ws, "busy.txt", b"in flight").json()["results"][0]["document"]["id"]
    doc = db.execute(select(Document)).scalar_one()
    doc.status, doc.locked_at = DocumentStatus.embedding, utcnow()
    db.commit()
    r = client.delete(f"/api/v1/workspaces/{ws}/documents/{doc_id}", headers=u["headers"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "document_busy"


def test_stale_processing_documents_are_recovered(client, user_ws, providers, db):
    u, ws = user_ws
    upload(client, u["headers"], ws, "stale.txt", b"worker died")
    doc = db.execute(select(Document)).scalar_one()
    doc.status, doc.attempts = DocumentStatus.embedding, 1
    doc.locked_at = utcnow() - timedelta(hours=1)
    db.commit()
    assert recover_stale_documents() == 1
    db.expire_all()
    assert db.execute(select(Document)).scalar_one().status == DocumentStatus.uploaded
    assert run_worker() == ["ready"]


def test_list_search_filter_and_pagination(client, user_ws, providers):
    u, ws = user_ws
    for i in range(5):
        upload(client, u["headers"], ws, f"report-{i}.txt", f"content number {i}".encode())
    upload(client, u["headers"], ws, "other_file.txt", b"something else entirely")
    run_worker()
    base = f"/api/v1/workspaces/{ws}/documents"
    assert client.get(base, headers=u["headers"]).json()["total"] == 6
    page = client.get(base + "?page=2&page_size=4", headers=u["headers"]).json()
    assert len(page["items"]) == 2 and page["total"] == 6
    assert client.get(base + "?q=report", headers=u["headers"]).json()["total"] == 5
    assert client.get(base + "?q=%25", headers=u["headers"]).json()["total"] == 0  # wildcard is escaped
    assert client.get(base + "?status=ready", headers=u["headers"]).json()["total"] == 6
    assert client.get(base + "?status=bogus", headers=u["headers"]).status_code == 422


def test_cross_workspace_isolation_for_documents(client, make_user, providers, db):
    alice, bob = make_user("Alice"), make_user("Bob")
    ws_a = personal_workspace(client, alice["headers"])
    ws_b = personal_workspace(client, bob["headers"])
    doc_id = upload(client, alice["headers"], ws_a, "secret.txt", b"alice confidential").json()["results"][0]["document"]["id"]
    run_worker()
    chunk_id = str(db.execute(select(Chunk)).scalar_one().id)
    base_a = f"/api/v1/workspaces/{ws_a}"
    # Bob targeting Alice's workspace: every operation is 404 (existence is not revealed).
    assert client.get(f"{base_a}/documents", headers=bob["headers"]).status_code == 404
    assert client.get(f"{base_a}/documents/{doc_id}", headers=bob["headers"]).status_code == 404
    assert client.delete(f"{base_a}/documents/{doc_id}", headers=bob["headers"]).status_code == 404
    assert client.post(f"{base_a}/documents/{doc_id}/reindex", headers=bob["headers"]).status_code == 404
    assert client.get(f"{base_a}/chunks/{chunk_id}", headers=bob["headers"]).status_code == 404
    assert upload(client, bob["headers"], ws_a, "x.txt", b"inject").status_code == 404
    # Bob using his OWN workspace id with Alice's document/chunk ids: still not found.
    base_b = f"/api/v1/workspaces/{ws_b}"
    assert client.get(f"{base_b}/documents/{doc_id}", headers=bob["headers"]).status_code == 404
    assert client.delete(f"{base_b}/documents/{doc_id}", headers=bob["headers"]).status_code == 404
    assert client.get(f"{base_b}/chunks/{chunk_id}", headers=bob["headers"]).status_code == 404
    assert providers.store.count(get_settings().namespace_for(ws_a)) == 1  # untouched
    # Alice can still read her own chunk through the authorized endpoint.
    own = client.get(f"{base_a}/chunks/{chunk_id}", headers=alice["headers"])
    assert own.status_code == 200 and own.json()["text"] == "alice confidential"


def test_workspace_deletion_removes_namespace_and_files(client, user_ws, providers, db):
    u, ws = user_ws
    team = client.post("/api/v1/workspaces", json={"name": "Temp"}, headers=u["headers"]).json()["id"]
    upload(client, u["headers"], team, "t.txt", b"temporary data")
    run_worker()
    ns = get_settings().namespace_for(team)
    assert providers.store.count(ns) == 1
    assert client.delete(f"/api/v1/workspaces/{team}", headers=u["headers"]).status_code == 204
    assert providers.store.count(ns) == 0 and not list((providers.root / team).rglob("*")) if (providers.root / team).exists() else True
    assert db.execute(select(Document)).first() is None
