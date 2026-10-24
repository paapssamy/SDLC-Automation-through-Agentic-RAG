# 10-minute viva demo script

**Before the viva:** `.\scripts\start_demo.ps1` (database + seed users + approved as-is
documentation + app). Open http://localhost:8501. Mock LLM is fine; switch to Groq beforehand
if you want live generation (`LLM_PROVIDER=groq`). Password for all users: `Demo@123`.

Tip: use one normal and one private browser window so you can stay logged in as two roles.

| Min | Log in as | What to do | What to point out |
|---|---|---|---|
| 0:00 | – | Show the Home page after login (`techlead`) | Pipeline counts by status, pending reviews, notifications; six layers / modular monolith |
| 1:00 | `techlead` | **As-Is Documentation**: open a section, e.g. `Pacs008MessageBuilder` | Docs come from Java parsing (nested classes, interfaces); already approved and published to `workspace/confluence/` |
| 2:00 | `ba` | **Requirement and Impact**: choose sample `REQ-1_purpose_code`, click *Generate impact analysis* | Key entities, affected services, complexity/risk/effort, **sources with similarity scores**, status `PENDING_REVIEW` |
| 3:00 | `ba` | **User Stories** → pick that analysis → *Generate* | **Gate demo (ST-03):** it is refused with "must be APPROVED" — checked on the server, a page refresh does not help |
| 3:45 | `techlead` | **Review Queue** → approve the impact analysis | Maker–checker; unknown services (if any) would be red; try *Request changes* with empty comment → comment required |
| 4:30 | `ba` | **User Stories** → *Generate*; then **Review Queue** → approve | INVEST check; after approval an **ADO work item id** appears (mock ADO) |
| 5:30 | `dev` | **Code Changes** → *Generate*; click *Adopt* first | **Strictest gate (ST-02):** adoption refused. Show the coloured unified diff; approve in Review Queue; *Adopt* → `workspace/branches/story-<id>/` |
| 6:30 | `qa` | **Test Cases** → *Generate*; approve all in Review Queue | SIT/UAT/regression, type, priority, automated flag; QA can edit a case |
| 7:15 | `qa` | **Test Execution** → *Run*: one boundary case fails (simulated defect); run again; record the manual result; *Sign-off* | `run_no` increments, logs stored, results uploaded to ADO Test Plans (mock) |
| 8:15 | `techlead` | **Releases and Docs** → *Run now* | Two mock releases replayed in order; only affected sections (e.g. `Pacs008MessageBuilder`, `CutOffTimeService`) get a new version; unchanged sections are skipped; `last_processed_release_id` stored (missed releases are replayed after downtime) |
| 9:00 | `techlead` | **Review Queue** → approve one release update, reject the other | Approval publishes a new Confluence page version; rejection restores the previous text as a new version (history kept) |
| 9:30 | `ba` → `admin` | Open **Admin and Audit** as `ba` (Access denied, SG-01), then as `admin` | RBAC enforced in the service layer; audit log is append-only (DB trigger, SG-02); integration settings hold only env-var names (SG-03) |

## Extra scenarios if time allows

* **Short requirement fallback:** requirement `REQ-5_add_lei` ("Add LEI") has no strong match, so
  the retriever adds the baseline core product specifications; the review screen shows the
  fallback warning and low scores (UT-04 / IT-01).
* **Request changes:** reject an impact analysis with a comment, then *Regenerate with reviewer
  feedback* — version number goes 1 → 2, same row.
* **Security:** in SQL, `UPDATE audit_log …` fails with "audit_log is append-only".
* **Other samples:** `REQ-2` (sanctions list), `REQ-3` (cut-off time), `REQ-4` (charges option).

## Reset between runs

```powershell
.\.venv\Scripts\python scripts\demo_setup.py --reset --kb
```

## If something goes wrong

* *Cannot connect to database* → `docker compose up -d` and wait ~10 s.
* *Generation fails with a real LLM* → set `LLM_PROVIDER=mock` and restart the app; the flow is identical.
* *Embedding model download* → needed once; afterwards it works offline (`EMBEDDING_MODEL=hash` is a fallback).
