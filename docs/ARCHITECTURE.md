# ORYN architecture

ORYN is a multi-tenant "chat with your documents" platform. A **workspace** is the tenant boundary: documents, vectors,
conversations and analytics all belong to exactly one workspace.

```
Browser (React SPA)
   |  HTTPS  JSON + SSE   (access token in memory; refresh token in an HttpOnly cookie)
   v
FastAPI  --------------------------------------------+
   |  SQLAlchemy 2                                    |  provider calls (retry + timeout)
   v                                                  v
PostgreSQL  (users, sessions, workspaces,       OpenAI   embeddings + chat (streaming)
 documents, chunks + FTS index, chats,          Pinecone vectors, one namespace per workspace
 query metrics, evaluations, audit events)      Cohere   rerank
   ^
   |  claims jobs with FOR UPDATE SKIP LOCKED
Ingestion worker (thread in the API process, or a separate process)
   |  local disk / persistent volume: original uploads
```

## Ingestion
Upload -> validate (extension, magic bytes, size, content hash; duplicates in a workspace are rejected) -> store file ->
row in `documents` with status `uploaded`. The worker moves it through `extracting -> chunking -> embedding -> indexing -> ready`
(or `failed` with a user-safe `error_summary`). Postgres is the queue: a job is claimed with `FOR UPDATE SKIP LOCKED`, stale
locks are recovered, and failures retry with exponential backoff (15 s x 2^(n-1)). Vector ids are deterministic
(`<document>:<version>:<chunk index>`), so a retry overwrites instead of duplicating. Delete removes vectors (listed by id
prefix), then database rows, then the file.

Chunks are split by **characters** (default 4000 with 700 overlap, roughly 1000 tokens). Characters are used because a
tokenizer would need a network download at build time.

## Retrieval and answering
1. Embed the question (OpenAI).
2. Dense search in Pinecone (namespace `ws-<workspace id>` plus a `workspace_id` metadata filter) and lexical search in
   PostgreSQL full text (`websearch_to_tsquery`, OR-combined, `ts_rank_cd`).
3. Fuse both lists with Reciprocal Rank Fusion (k = 60).
4. Re-hydrate the candidate chunks **from Postgres** with `workspace_id` and `status = ready` filters. Pinecone is never trusted
   as the source of truth for text or tenancy.
5. Rerank with Cohere. Candidates below `MIN_RERANK_SCORE` are dropped. There is no silent fallback if the reranker fails.
6. If nothing relevant remains, the LLM is **not called**; the user gets a fixed "not enough information" reply.
7. Otherwise the top `CONTEXT_CHUNKS` go to the model inside `<source>` tags. The system prompt tells the model to treat them as
   untrusted data.

## Streaming protocol (SSE over POST)
Events: `status` (`started` / `retrieving` / `generating`), `sources`, `token`, `done`, `error`. Headers disable proxy buffering
(`Cache-Control: no-cache, no-transform`, `X-Accel-Buffering: no`). The server persists the assistant message on completion,
error **and client disconnect** (status `cancelled`). `sources` is a structured payload; the `[n]` markers in the text are
advisory and the UI shows the structured list.

## Tenancy
Every workspace route calls `require_member`. Non-members receive **404**, not 403, so workspace ids cannot be probed.
Conversations are private to (workspace, user): other members, including admins, cannot read them. Tests cover cross-tenant
access for documents, chunks, conversations, analytics and evaluations.

## Frontend
React 19 + TypeScript (strict) + Vite + Tailwind 4. TanStack Query for server state, React Hook Form + Zod for forms,
Radix primitives for dialogs, `react-markdown` (no raw HTML) for model output. The access token lives only in memory; on page
load the app calls `/auth/refresh` with the cookie. `src/lib/sse.ts` is a small incremental SSE parser used with `fetch`.

## Known design limits
- Rate limiting and the inline worker are per process. Run one API instance, or move to Redis and `INGESTION_WORKER_MODE=separate`.
- Uploaded files live on local disk (a persistent volume on Render); there is no object-storage adapter yet.
- Evaluation runs execute in a background thread of the API process.
