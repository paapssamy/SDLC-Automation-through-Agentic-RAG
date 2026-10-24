# SDLC Automation through Agentic RAG for a Banking Payments Application

A web platform where **ten role-based AI agents** use **Agentic RAG** over the bank's own
as-is documentation to produce each SDLC artifact (impact analysis, user story, code change,
test cases, living documentation). **A human reviewer approves every artifact before the next
stage can start** (maker–checker). Everything runs locally with free tools; Azure DevOps and
Confluence run in **mock mode** by default, and the LLM can be a deterministic mock, so the full
demo works with no company account and no API key.

## Quick start (demo)

Prerequisites: Python 3.11+ (built and tested on 3.12), Docker Desktop, Git.

```powershell
# one time
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env            # already present if you cloned this folder after setup

# every time
.\scripts\start_demo.ps1          # starts the DB, prepares data, opens the app
```

`start_demo.ps1` does the following; you can run the steps yourself:

```powershell
docker compose up -d                                   # PostgreSQL 16 + pgvector (host port 5460)
.\.venv\Scripts\python scripts\demo_setup.py --reset --kb   # tables, HNSW index, audit trigger,
                                                       # seed users, as-is docs generated + approved
.\.venv\Scripts\streamlit run app\ui\Home.py           # http://localhost:8501
```

> The database is published on **host port 5460** (not 5432) so it does not clash with other
> PostgreSQL containers. Change it in `docker-compose.yml` and `DATABASE_URL` if you prefer.

### Demo users

| Username | Role | Password |
|---|---|---|
| `ba` | Business Analyst | `Demo@123` |
| `techlead` | Technical Lead | `Demo@123` |
| `dev` | Developer | `Demo@123` |
| `qa` | QA Lead | `Demo@123` |
| `admin` | Administrator | `Demo@123` |

Demo passwords are for local use only. Change them in the Admin page for anything else.

A step-by-step viva walkthrough is in [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).

## Configuration (`.env`)

Copy `.env.example` to `.env`. Secrets live **only** in `.env` (never in code, DB or git).

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `mock` | `mock` (offline, deterministic), `groq`, or `azure` |
| `GROQ_API_KEY`, `GROQ_MODEL` | – / `llama-3.1-8b-instant` | Groq settings (if that model is retired, set the current Groq Llama 8B model name) |
| `AZURE_OPENAI_*` | – | Azure OpenAI endpoint, key, deployment |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | `hash` = fast offline fallback (used by tests) |
| `RAG_SIMILARITY_THRESHOLD`, `RAG_TOP_K`, `RAG_KEEP_TOP` | `0.35`, `10`, `5` | RAG tuning |
| `ADO_MODE` / `CONFLUENCE_MODE` | `mock` | `live` uses the real REST APIs |
| `TEST_RUNNER` | `mock` | `local_command` runs `TEST_RUNNER_COMMAND` (e.g. `mvn -q test`) in `workspace/test_env/` |
| `RELEASE_POLL_MINUTES` | `5` | ADO polling interval |
| `APP_MODE` | `demo` | `production` starts the release scheduler automatically |

### Switching to production options

* **Groq (real LLM):** set `LLM_PROVIDER=groq` and `GROQ_API_KEY=...`, then
  `python scripts/cli_pipeline.py` to verify the whole chain.
* **Azure OpenAI:** set `LLM_PROVIDER=azure` plus endpoint, key and deployment.
* **Live Azure DevOps:** `ADO_MODE=live`, `ADO_ORG_URL`, `ADO_PROJECT`, `ADO_PAT`.
* **Live Confluence:** `CONFLUENCE_MODE=live`, `CONFLUENCE_BASE_URL`, `CONFLUENCE_SPACE`,
  `CONFLUENCE_USER`, `CONFLUENCE_API_TOKEN`.
* **Real test run:** `TEST_RUNNER=local_command` and put a Maven project in `workspace/test_env/`.

Every prompt is masked before it reaches an LLM (account numbers, IBANs, e-mails, phone
numbers, BIC-like references).

## Run the tests

```powershell
.\.venv\Scripts\python -m pytest                       # all tests (separate DB sdlc_rag_test)
.\.venv\Scripts\python scripts\make_test_report.py     # + coverage → docs/test_report.md
.\.venv\Scripts\ruff check . ; .\.venv\Scripts\ruff format --check .
```

Tests never call a real LLM; tests marked `@pytest.mark.live` need real systems and are skipped.
Latest result: see [docs/test_report.md](docs/test_report.md).

## Architecture in one page

Six layers, each talking only to the next: **Presentation** (Streamlit) → **Application**
(`WorkflowOrchestrator`, `ApprovalService`, `NotificationService`, scheduler) → **Agents** (ten) →
**Knowledge/RAG** → **Data** (PostgreSQL + pgvector) → **Integration** (LLM, ADO, Confluence,
test runner). It is a modular monolith.

* Agents never call each other. The orchestrator starts the next agent only if the **database**
  status of the previous artifact is `APPROVED` — checked server-side, never from UI state.
* Status values: `DRAFT, PENDING_REVIEW, CHANGES_REQUESTED, APPROVED, REJECTED, PUBLISHED,
  SUPERSEDED` (DB `CHECK` constraint + `InvalidTransitionError`). Artifacts are never deleted.
* Patterns: Template Method (`BaseAgent.run`), Strategy (`LLMClient`, `VectorStore`, embedder),
  Adapter (`AdoClient`, `ConfluenceClient`, `TestRunnerAdapter`), State (`services/artifacts.py`),
  Maker–Checker (`ApprovalService`), Observer (`EventBus` / notifications).

| # | Agent | Module | Needs LLM |
|---|---|---|---|
| 1 | `JavaParserAgent` | 3.1 as-is documentation | yes |
| 2 | `ImpactAnalysisAgent` | 3.3 | yes |
| 3 | `StoryGeneratorAgent` | 3.4 | yes |
| 4 | `CodeGenerationAgent` | 3.5 | yes |
| 5 | `TestGeneratorAgent` | 3.6 | yes |
| 6 | `TestExecutionAgent` | 3.7 | no |
| 7 | `ReleaseMonitorAgent` | 3.8 | no |
| 8 | `IncrementalDocUpdater` | 3.8 | yes |
| 9 | `AdoReposConnector` | 3.5 / 3.8 | no |
| 10 | `ConfluenceSyncAgent` | 3.9 | no |

Who approves what: documentation and impact analysis → Technical Lead; user story → Business
Analyst; code change → Developer; test cases and sign-off → QA Lead; release doc updates →
Technical Lead.

### Folder map

```
app/config.py        settings from .env          app/agents/     the ten agents
app/db/              models (16+1 tables), init  app/rag/        embeddings, pgvector, retriever
app/llm/             Groq, Azure, Mock clients   app/services/   orchestrator, approvals, auth, …
app/integrations/    ADO, Confluence, runners    app/ui/         Streamlit Home + 9 pages
app/prompts/         versioned prompt templates  sample_data/    Java app, requirements, specs, ADO fixtures
scripts/             demo_setup, cli_pipeline, semantic_search, make_test_report, start_demo
workspace/           generated: branches/, confluence/, mock_ado/ (git-ignored)
```

`notification` is one extra table beyond the 16 designed tables (it stores in-app messages).

## Assumptions and notes

* Built and verified on Python 3.12 (the brief says 3.11; the code uses nothing newer).
* The knowledge base only serves `APPROVED`/`PUBLISHED` documentation to the agents, so a
  Technical Lead must approve the as-is documentation first (`demo_setup.py --kb` does this).
* Release doc updates are written to the knowledge base (new text + embedding + version row in
  one transaction) and then confirmed by the Technical Lead; a rejection restores the previous
  text as a new version, and approval publishes the page to Confluence.
* The Maven runner is optional; the default `MockRunner` simulates one boundary defect on run 1
  and passes on re-run so the QA flow can be shown end to end.
