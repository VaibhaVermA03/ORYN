from __future__ import annotations

import io
import json
import uuid

import pytest
from sqlalchemy import select

from app.cli import evaluate as cli_evaluate
from app.cli import make_admin
from app.core.exceptions import ProviderError
from app.db.models import EvaluationResult, EvaluationRun, User, UserRole
from app.services import evaluation_service as ev
from app.services.evaluation_service import (
    aggregate,
    faithfulness_score,
    rescale_1_to_5,
    retrieval_metrics,
    set_judge,
)
from tests.conftest import personal_workspace, run_worker
from tests.fakes import FakeJudge

REFUND = b"Refund policy: customers may request a refund within 14 days of purchase."
SHIPPING = b"Shipping policy: orders over fifty dollars ship free. Delivery takes five business days."


def upload(client, headers, ws, name, data):
    r = client.post(f"/api/v1/workspaces/{ws}/documents", headers=headers,
                    files=[("files", (name, io.BytesIO(data), "text/plain"))])
    assert r.json()["results"][0]["accepted"], r.text


@pytest.fixture
def kb(client, make_user, providers):
    u = make_user("Eval Owner")
    ws = personal_workspace(client, u["headers"])
    upload(client, u["headers"], ws, "refunds.txt", REFUND)
    upload(client, u["headers"], ws, "shipping.txt", SHIPPING)
    assert run_worker() == ["ready", "ready"]
    return u, ws


@pytest.fixture(autouse=True)
def _reset_judge():
    yield
    set_judge(None)


def dataset(*samples, name="smoke"):
    return {"name": name, "samples": list(samples)}


S_REFUND = {"question": "What is the refund policy?", "ground_truth": "14 days", "relevant_documents": ["refunds.txt"]}
S_SHIP = {"question": "How does shipping delivery work?", "relevant_documents": ["Shipping.txt"]}
S_OFFTOPIC = {"question": "Who painted the Mona Lisa?", "relevant_documents": ["refunds.txt"]}
S_NOLABEL = {"question": "refund within 14 days"}


# ------------------------------------------------------------------ pure metric functions


def test_retrieval_metrics_definitions():
    m = retrieval_metrics(["a.pdf", "a.pdf", "b.pdf", "c.pdf"], ["A.pdf", "z.pdf"])
    assert m == {"context_precision": 0.5, "context_recall": 0.5, "hit_rate": 1.0}
    assert retrieval_metrics(["x.pdf"], ["a.pdf"]) == {"context_precision": 0.0, "context_recall": 0.0, "hit_rate": 0.0}
    assert retrieval_metrics([], ["a.pdf"]) == {"context_precision": 0.0, "context_recall": 0.0, "hit_rate": 0.0}
    assert retrieval_metrics(["a.pdf"], None) == {"context_precision": None, "context_recall": None, "hit_rate": None}
    assert retrieval_metrics(["a.pdf"], []) == {"context_precision": None, "context_recall": None, "hit_rate": None}


def test_judge_score_conversions_reject_garbage():
    assert faithfulness_score(4, 3) == 0.75 and faithfulness_score(2, 5) == 1.0  # clamped, never > 1
    assert faithfulness_score(0, 0) is None and faithfulness_score("x", 1) is None and faithfulness_score(3, -1) is None
    assert rescale_1_to_5(1) == 0.0 and rescale_1_to_5(5) == 1.0 and rescale_1_to_5(3) == 0.5
    assert rescale_1_to_5(0) is None and rescale_1_to_5(9) is None and rescale_1_to_5("n/a") is None and rescale_1_to_5(None) is None


def test_aggregate_ignores_nulls_and_reports_n():
    agg = aggregate([{"a": 1.0, "b": None}, {"a": 0.0, "b": 0.5}, {"a": None}], ("a", "b", "c"))
    assert agg["a"] == {"mean": 0.5, "n": 2} and agg["b"] == {"mean": 0.5, "n": 1} and agg["c"] == {"mean": None, "n": 0}


# ------------------------------------------------------------------ API runs


def start(client, u, ws, ds, judge=False):
    return client.post(f"/api/v1/workspaces/{ws}/evaluations", headers=u["headers"], json={"dataset": ds, "judge": judge})


def test_evaluation_run_computes_real_metrics_and_stores_config(client, kb, providers):
    u, ws = kb
    r = start(client, u, ws, dataset(S_REFUND, S_SHIP, S_OFFTOPIC, S_NOLABEL))
    assert r.status_code == 202 and "does not guarantee production accuracy" in r.json()["disclaimer"]
    detail = client.get(f"/api/v1/workspaces/{ws}/evaluations/{r.json()['id']}", headers=u["headers"]).json()
    assert detail["status"] == "completed" and detail["sample_count"] == 4 and len(detail["results"]) == 4
    cfg = detail["config"]
    assert cfg["chat_model"] and cfg["embedding_model"] and cfg["rerank_model"] and cfg["context_chunks"] == 5
    assert cfg["judge"] is False and len(cfg["dataset"]) == 4
    m = detail["metrics"]
    # 3 labelled samples contribute to retrieval metrics; the unlabelled one is excluded, not zero-filled.
    assert m["context_recall"]["n"] == 3 and m["hit_rate"]["n"] == 3
    by_q = {x["question"]: x for x in detail["results"]}
    refund = by_q[S_REFUND["question"]]["metrics"]
    assert refund["hit_rate"] == 1.0 and refund["context_recall"] == 1.0 and refund["generation_ms"] > 0
    assert by_q[S_SHIP["question"]]["metrics"]["hit_rate"] == 1.0  # filename match is case-insensitive
    off = by_q[S_OFFTOPIC["question"]]
    assert off["contexts"] == [] and off["metrics"]["hit_rate"] == 0.0 and off["metrics"]["generation_ms"] is None
    assert by_q[S_NOLABEL["question"]]["metrics"]["hit_rate"] is None
    assert m["_summary"] == {"samples": 4, "succeeded": 4, "failed": 0, "abstained": 1}
    assert m["generation_ms"]["n"] == 3 and m["total_ms"]["n"] == 4
    # No judge requested -> LLM metrics are absent rather than invented.
    assert m["faithfulness"] == {"mean": None, "n": 0} and m["answer_relevance"]["n"] == 0


def test_judge_metrics_are_opt_in_and_skip_abstained_answers(client, kb, providers):
    u, ws = kb
    judge = FakeJudge()
    set_judge(judge)
    r = start(client, u, ws, dataset(S_REFUND, S_OFFTOPIC), judge=True)
    detail = client.get(f"/api/v1/workspaces/{ws}/evaluations/{r.json()['id']}", headers=u["headers"]).json()
    m = detail["metrics"]
    assert m["faithfulness"] == {"mean": 0.5, "n": 1}  # 2/4 claims; the abstained sample is excluded
    assert m["answer_relevance"] == {"mean": 0.75, "n": 1} and m["answer_correctness"] == {"mean": 1.0, "n": 1}
    assert detail["config"]["judge"] is True and detail["config"]["judge_model"] == "fake-judge"
    assert len(judge.calls) == 3  # faithfulness + relevance + correctness, only for the answered sample
    assert "untrusted" in judge.calls[0][0]


def test_judge_requires_openai_configuration(client, kb, providers):
    u, ws = kb  # no judge installed and no API key in the environment
    r = start(client, u, ws, dataset(S_REFUND), judge=True)
    assert r.status_code == 503 and r.json()["error"]["code"] == "provider_not_configured"
    assert client.get(f"/api/v1/workspaces/{ws}/evaluations", headers=u["headers"]).json() == []


def test_failed_samples_are_recorded_and_do_not_abort_the_run(client, kb, providers):
    u, ws = kb
    original = providers.reranker.rerank
    state = {"n": 0}

    def flaky(query, documents, top_n):
        state["n"] += 1
        if state["n"] == 1:
            raise ProviderError("cohere", "The reranking service is rate limiting requests.", retryable=True)
        return original(query, documents, top_n)

    providers.reranker.rerank = flaky
    r = start(client, u, ws, dataset(S_REFUND, S_SHIP))
    detail = client.get(f"/api/v1/workspaces/{ws}/evaluations/{r.json()['id']}", headers=u["headers"]).json()
    assert detail["status"] == "completed" and detail["error_summary"] == "1 of 2 samples failed."
    failed = [x for x in detail["results"] if x["error"]]
    assert len(failed) == 1 and failed[0]["metrics"] == {} and "rate limiting" in failed[0]["error"]
    assert detail["metrics"]["_summary"]["failed"] == 1 and detail["metrics"]["hit_rate"]["n"] == 1


def test_run_fails_when_every_sample_fails(client, kb, providers):
    u, ws = kb
    providers.reranker.fail_with = ProviderError("cohere", "down", retryable=False)
    r = start(client, u, ws, dataset(S_REFUND))
    detail = client.get(f"/api/v1/workspaces/{ws}/evaluations/{r.json()['id']}", headers=u["headers"]).json()
    assert detail["status"] == "failed" and "Every sample failed" in detail["error_summary"]


def test_dataset_validation_and_limits(client, kb, providers, monkeypatch):
    from app.core.config import get_settings

    u, ws = kb
    assert start(client, u, ws, {"name": "x", "samples": []}).status_code == 422
    assert start(client, u, ws, dataset({"question": "   "})).status_code == 422
    monkeypatch.setattr(get_settings(), "eval_max_samples", 2)
    r = start(client, u, ws, dataset(S_REFUND, S_SHIP, S_NOLABEL))
    assert r.status_code == 422 and r.json()["error"]["code"] == "dataset_too_large"


def test_only_one_run_at_a_time_and_stale_runs_are_failed(client, kb, providers, db):
    from datetime import timedelta

    from app.db.base import utcnow

    u, ws = kb
    run = EvaluationRun(workspace_id=uuid.UUID(ws), dataset_name="stuck", status="running", sample_count=1,
                        config={}, metrics={})
    db.add(run)
    db.commit()
    r = start(client, u, ws, dataset(S_REFUND))
    assert r.status_code == 409 and r.json()["error"]["code"] == "evaluation_running"
    run.created_at = utcnow() - timedelta(hours=2)
    db.commit()
    assert start(client, u, ws, dataset(S_REFUND)).status_code == 202  # stale run was failed, new one allowed
    db.expire_all()
    assert db.get(EvaluationRun, run.id).status == "failed"


def test_evaluation_authorization_and_isolation(client, make_user, kb, providers, db):
    u, ws = kb
    member, outsider = make_user("Member"), make_user("Outsider")
    client.post(f"/api/v1/workspaces/{ws}/members", json={"email": member["email"]}, headers=u["headers"])
    run_id = start(client, u, ws, dataset(S_REFUND)).json()["id"]
    base = f"/api/v1/workspaces/{ws}/evaluations"
    # Plain members cannot start or read evaluations (they spend money and expose questions).
    assert client.post(base, headers=member["headers"], json={"dataset": dataset(S_REFUND)}).status_code == 403
    assert client.get(base, headers=member["headers"]).status_code == 403
    assert client.get(f"{base}/{run_id}", headers=member["headers"]).status_code == 403
    # Non-members learn nothing about the workspace.
    assert client.get(base, headers=outsider["headers"]).status_code == 404
    assert client.get(f"{base}/{run_id}", headers=outsider["headers"]).status_code == 404
    # Another workspace's id with this run id does not resolve.
    other = client.post("/api/v1/workspaces", json={"name": "Other"}, headers=u["headers"]).json()["id"]
    assert client.get(f"/api/v1/workspaces/{other}/evaluations/{run_id}", headers=u["headers"]).status_code == 404


# ------------------------------------------------------------------ CLI


def test_cli_make_admin_promotes_existing_active_account_only(client, make_user, db, capsys):
    u = make_user("Future Admin")
    assert make_admin("ghost@example.com") == 1
    assert make_admin(u["email"].upper()) == 0 and "now a global administrator" in capsys.readouterr().out
    db.expire_all()
    assert db.get(User, uuid.UUID(u["id"])).role == UserRole.admin
    assert make_admin(u["email"]) == 0 and "already" in capsys.readouterr().out
    me = client.get("/api/v1/users/me", headers=u["headers"]).json()
    assert me["role"] == "admin"


def test_cli_evaluate_runs_dataset_file(kb, providers, tmp_path, capsys):
    u, ws = kb
    path = tmp_path / "ds.json"
    path.write_text(json.dumps(dataset(S_REFUND, name="cli")))
    assert cli_evaluate(ws, str(path), judge=False) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "completed" and out["metrics"]["hit_rate"]["mean"] == 1.0
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert cli_evaluate(ws, str(bad), judge=False) == 2


def test_eval_results_cascade_with_run(kb, client, providers, db):
    u, ws = kb
    run_id = start(client, u, ws, dataset(S_REFUND)).json()["id"]
    assert db.execute(select(EvaluationResult)).first() is not None
    db.delete(db.get(EvaluationRun, uuid.UUID(run_id)))
    db.commit()
    assert db.execute(select(EvaluationResult)).first() is None
    assert ev  # module imported for coverage of service wiring
