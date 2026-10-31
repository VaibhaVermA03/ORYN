"""Operator command-line tools. Run on the server with database access:

    python -m app.cli make-admin --email you@example.com
    python -m app.cli evaluate --workspace <uuid> --dataset eval.json [--judge]

`make-admin` is the supported way to provision the FIRST global administrator: it requires shell
access to the deployment (so it cannot be triggered remotely) and an existing, active account.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid

from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.models import EvaluationRun, User, UserRole
from app.db.session import session_scope
from app.schemas.auth import normalize_email
from app.schemas.evaluation import EvalDataset
from app.services import evaluation_service as ev
from app.services.audit_service import record_audit


def make_admin(email: str) -> int:
    email = normalize_email(email)
    with session_scope() as db:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None or not user.is_active:
            print(f"No active account with email {email}. Sign up first, then rerun.", file=sys.stderr)
            return 1
        if user.role == UserRole.admin:
            print(f"{email} is already an administrator.")
            return 0
        user.role = UserRole.admin
        record_audit(db, action="user.promote_admin", actor_id=None, target_type="user", target_id=user.id,
                     details={"via": "cli"})
    print(f"{email} is now a global administrator. The role applies to their next request.")
    return 0


def evaluate(workspace: str, dataset_path: str, judge: bool) -> int:
    try:
        with open(dataset_path, encoding="utf-8") as f:
            dataset = EvalDataset.model_validate(json.load(f))
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"Invalid dataset: {exc}", file=sys.stderr)
        return 2
    s = get_settings()
    if len(dataset.samples) > s.eval_max_samples:
        print(f"Dataset has more than {s.eval_max_samples} samples.", file=sys.stderr)
        return 2
    with session_scope() as db:
        run = ev.create_run(db, workspace_id=uuid.UUID(workspace), created_by=None, name=dataset.name,
                            samples=[x.model_dump() for x in dataset.samples], judge=judge)
        run_id = run.id
    ev.run_evaluation(run_id)
    with session_scope() as db:
        finished = db.get(EvaluationRun, run_id)
        if finished is None:
            return 1
        run = finished
        print(json.dumps({"id": str(run_id), "status": run.status, "metrics": run.metrics,
                          "note": run.error_summary}, indent=2, default=str))
        return 0 if run.status == "completed" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("make-admin", help="Grant the global administrator role to an existing account")
    a.add_argument("--email", required=True)
    e = sub.add_parser("evaluate", help="Run a RAG evaluation on a workspace")
    e.add_argument("--workspace", required=True)
    e.add_argument("--dataset", required=True)
    e.add_argument("--judge", action="store_true", help="Enable LLM-judged metrics (extra OpenAI cost)")
    args = parser.parse_args(argv)
    configure_logging(get_settings().log_level)
    if args.command == "make-admin":
        return make_admin(args.email)
    return evaluate(args.workspace, args.dataset, args.judge)


if __name__ == "__main__":
    raise SystemExit(main())
