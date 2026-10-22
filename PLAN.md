# Legal Doc Assistant — Build Plan

## Context
Portfolio project for a backend SWE role on an AI legal drafting team. A small FastAPI service: upload plain-text legal documents into PostgreSQL, ask questions about them, and an LLM agent (Claude Haiku) answers by calling two tools, streaming the answer over SSE. Goal is a tight, well-tested, readable codebase that shows backend fundamentals: clean layering, dependency injection, reliability (timeouts, retries, validation, structured logs), and real integration tests. The user writes the tests; I build structure + fixtures, say which tests to write, and review them. Work stops after every phase for review, with one commit per phase.

Working directory is empty (`/home/user`, not a git repo). The project lives in a new public GitHub repo, `Wafinator/legal-doc-assistant`, cloned to `/home/user/legal-doc-assistant` (phase 0).

## Key decisions (with the "why")
| Decision | Choice | Why |
|---|---|---|
| Packaging | **uv** + `pyproject.toml`, Python 3.12 pinned in `.python-version` | Current standard Python tooling. One lockfile, fast installs, roughly what NuGet + `dotnet restore` do for you in C#. |
| DB access | **Sync** SQLAlchemy 2.0 (typed `Mapped[]` models) + psycopg 3 | FastAPI runs sync endpoints in a thread pool, so sync is fine at this scale. It keeps test fixtures much simpler (no event-loop scoping problems). Async is a possible later upgrade. |
| Schema | `Base.metadata.create_all` at startup; Alembic left out | One table. Migrations are listed as a "next step" in the README. |
| Keyword search | Postgres **full-text search**: generated `tsvector` column + GIN index, `websearch_to_tsquery`, `ts_headline` snippets, ranked by `ts_rank` | Real keyword search with stemming ("terminate" matches "termination"), no vector DB. A good thing to talk about in interviews. |
| Sections | Pure function `split_sections(text)` that finds headings (markdown `#`, numbered like `1.` / `12.3`, `ARTICLE IV`, `Section 5`, ALL-CAPS lines) and is computed when asked, not stored | No extra table. Pure functions are the easiest unit tests. |
| LLM | Anthropic SDK, model `claude-haiku-5-5`, `output_config={"effort": "low"}` to keep cost down, thinking left at default (adaptive) | Haiku 5.5 is the current Haiku. Effort is the cost lever on this model. The code reads content blocks **by type**, never `content[0]`, because responses can start with `thinking` blocks. |
| Agent loop | **Hand-written** loop, not the SDK's beta Tool Runner | You asked to build the loop and its max-step limit, and owning it lets us inject a fake client and log every tool call. |
| Retries | SDK `max_retries=0`. We write our own exponential backoff with jitter | So every retry gets logged and tested. Retry on 429, 5xx/529, connection errors and timeouts. Never retry 400/401/403/404. |
| LLM boundary | `LLMClient` Protocol (like a C# interface) with `AnthropicLLMClient` and, in tests, `FakeLLMClient`. FastAPI `Depends(get_llm_client)` is overridden in tests | Tests run offline with no API key. |
| SSE | Plain `StreamingResponse(media_type="text/event-stream")` with a small `format_sse(event, data)` helper | Writing the frames by hand teaches the protocol. It's about 10 lines and needs no extra dependency. |
| Logging | stdlib `logging` + a JSON formatter + `contextvars` request ID set by middleware | One JSON line per event (request, llm_call, tool_call, agent_done) carrying `request_id`, latency_ms and tokens. No extra dependency. |
| API input | JSON body `{title, content}` for upload (no multipart) | Smallest surface. Pydantic validates lengths and rejects blank strings. |

## Layout
```
legal-doc-assistant/
  pyproject.toml  uv.lock  .python-version  .env.example  docker-compose.yml  README.md
  docker/init-db.sql                 # creates legal_docs + legal_docs_test databases
  app/
    main.py          # create_app(): routers, middleware, startup create_all
    config.py        # pydantic-settings: DATABASE_URL, ANTHROPIC_API_KEY, model, timeouts, max_steps
    db.py            # engine, SessionLocal, get_db dependency
    models.py        # Document ORM model
    schemas.py       # Pydantic request/response models
    logging_setup.py # JSON formatter, request-id middleware
    documents/       # repository.py (create/list/get/search), sections.py (split_sections)
    llm/             # client.py (Protocol, AnthropicLLMClient, LLMResponse/Usage), retry.py
    agent/           # tools.py (tool schemas + execute_tool), loop.py (run_agent), events.py
    api/             # documents.py, ask.py (routers), sse.py
  tests/
    conftest.py      # engine, db reset, TestClient, dependency overrides, factories
    fakes.py         # FakeLLMClient (scripted responses)
    unit/  integration/
  .github/workflows/ci.yml
```

## Phases
### [x] Phase 0: create the repo (before any code)
- Create `Wafinator/legal-doc-assistant` (public, empty) on GitHub, add it as `origin` of the local repo to `/home/user/legal-doc-assistant`, attach it to this session, and work on `main`.
- Copy this plan into the repo as `PLAN.md` and make it the first commit, so it stays with the project. At the end of each phase I'll tick that phase off in `PLAN.md`.
- Phase commits are pushed to GitHub as we go, so CI runs for real in phase 5. If the repo can't be created from this session, I'll tell you the exact step that failed and how to fix it.

Each phase ends the same way: run the suite, commit, then **stop** with an explanation of what was built, the list of tests for you to write, and room for questions.

### [x] Phase 1: setup, Docker Compose, model, document endpoints
- `uv init`, dependencies: fastapi, uvicorn, sqlalchemy, psycopg[binary], pydantic-settings, anthropic. Dev dependencies: pytest, httpx, ruff.
- `docker-compose.yml`: `postgres:16` with a healthcheck, plus an init script that creates the dev and test databases.
- `Document`: id, title, content, created_at, plus a generated `search_vector` with a GIN index.
- Endpoints: `POST /documents` (201), `GET /documents` (id, title, created_at, char_count, with `limit`/`offset` paging, no content), `GET /documents/{id}` (404 if missing), `GET /health`.
- Test scaffolding: `conftest.py` with a session-scoped engine pointed at `legal_docs_test`, an autouse `TRUNCATE documents RESTART IDENTITY CASCADE` before each test, a `client` fixture, and a `make_document` factory. *(Built: conftest sets `DATABASE_URL` to the test DB before importing the app, so no `get_db` override is needed. `dependency_overrides` is used for the LLM client in phase 2.)*
- **Tests you'll write:** upload returns 201 and the body round-trips; validation 422s (empty or whitespace title, oversized content, missing fields); the list endpoint excludes content and pages correctly; fetching an unknown id returns 404; a test that proves the reset fixture isolates tests.

### [ ] Phase 2: LLM client wrapper
- `LLMClient.stream_turn(system, messages, tools) -> Iterator[TextDelta | LLMResponse]`. `LLMResponse` holds `content` (raw block dicts, which keep `thinking` blocks intact so they can be passed back unchanged), `stop_reason`, and `usage`.
- `AnthropicLLMClient` wraps `client.messages.stream(...)` with an `httpx.Timeout` (connect / read) and `max_retries=0`.
- `retry.py`: `call_with_retries(fn, policy, sleep=time.sleep)` with exponential backoff, full jitter and a max-attempts cap. It honors the `retry-after` header and has an `is_retryable(exc)` classifier. **It retries only before the first token is streamed out**, because a retry after that would show the user duplicated text.
- Structured log per call: model, attempt, latency_ms, input/output tokens, stop_reason.
- **Tests you'll write:** `is_retryable` across the error classes (you'll build a `RateLimitError` from an `httpx.Response`); backoff timing with an injected fake `sleep`; giving up after max attempts; no retry on a 400; and no retry once a delta has been emitted.

### [ ] Phase 3: agent loop and tools
- Tools (`strict: true` schemas, `additionalProperties: false`):
  - `search_documents(query, document_id?)` returns the top 5 hits as `{document_id, title, snippet, rank}`.
  - `get_section(document_id, heading)` matches headings case-insensitively, exact match first, then contains. If nothing matches it returns `is_error` plus the list of available headings so the model can try again.
- `run_agent(question, document_id, llm, db, max_steps)` yields events. Each step: call the LLM; if `stop_reason == "tool_use"`, run every `tool_use` block, then send back **all** `tool_result`s in one user message; if `end_turn`, finish. Hitting `max_steps` produces a clear "step limit reached" outcome. Bad tool input or a tool exception becomes an `is_error` tool_result instead of crashing the request. A `max_tokens` or `refusal` stop reason is handled explicitly.
- A system prompt keeps answers grounded in tool results and asks for section citations.
- **Tests you'll write:** unit tests for `split_sections` on contracts and court-filing-style headings; integration tests for `search_documents` (stemming, filtering by document_id, no hits); the loop with a scripted fake (single answer, search then section then answer, max-step cutoff, unknown tool name, a tool error fed back to the model, tokens summed across steps).

### [ ] Phase 4: SSE streaming
- `POST /ask` with `{question (1–2000 chars), document_id?}` → `text/event-stream`. Event types: `tool_call`, `tool_result` (summary), `token` (text delta), `done` (`{steps, usage, latency_ms}`), `error`.
- A total agent deadline (for example 60s) on top of the per-call timeouts. Errors after the stream starts go out as an `error` event, because the HTTP status has already been sent as 200. A missing document returns 404 *before* the stream opens.
- Request-log middleware: method, path, status, latency_ms, request_id (also returned in the `X-Request-ID` header).
- **Tests you'll write:** parse the SSE frames from TestClient and assert the event order; the 404 happens before streaming; 422 on a bad question; a fake that raises mid-stream produces an `error` event; a log-capture test (`caplog`) for the tool-call and usage log lines.

### [ ] Phase 5: GitHub Actions CI
- `ci.yml` runs on every push and PR: a `postgres:16` service container, `astral-sh/setup-uv`, `uv sync --frozen`, `ruff check`, `pytest`. No API key needed.
- Push, then confirm the workflow run passes on GitHub.

### [ ] Phase 6: README
Covers what the project is and why, an architecture diagram (Mermaid: request → router → agent loop ↔ LLMClient / tools → Postgres), the design decisions above, setup (`docker compose up -d`, `uv sync`, `.env`, `uv run uvicorn`), example `curl` requests including `curl -N` for SSE, how testing works, and "what I'd do next" (Alembic, async, auth, eval set).

## Verification (every phase)
- `docker compose up -d` and then `uv run pytest` must be green. That includes the scaffolding smoke test I add, and your tests once you've written them.
- Phases 1, 3 and 4: run `uv run uvicorn app.main:app` and exercise it with `curl`. Phase 4 can also run end to end against the real Haiku API if you provide an `ANTHROPIC_API_KEY`; otherwise I'll verify it with the fake client only and say so.
- `uv run ruff check .` is clean before each commit.
