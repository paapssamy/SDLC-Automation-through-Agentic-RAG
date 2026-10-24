# Test Report

Generated on 2026-10-21 by `scripts/make_test_report.py` (LLM = mock, embeddings = hash, ADO/Confluence = mock, separate test database).

## Summary per level

| Level | Executed | Passed | Failed | Skipped |
|---|---:|---:|---:|---:|
| Unit | 23 | 23 | 0 | 0 |
| Integration | 8 | 6 | 0 | 2 |
| System | 52 | 52 | 0 | 0 |
| Security and governance | 7 | 7 | 0 | 0 |
| **Total** | **90** | **88** | **0** | **2** |

**Line coverage of `app/` (excluding `app/ui`): 87.3%** (2174 of 2490 statements; target ≥ 80%).

Pages under `app/ui` are exercised by `tests/system/test_ui_smoke.py` (every page × every role renders without error) but are excluded from the coverage figure.

## Required test IDs

| ID | Test function(s) | Result |
|---|---|---|
| UT-01 | test_ut01_two_classes_and_one_interface | PASS |
| UT-02 | test_ut02_nested_class_included | PASS |
| UT-03 | test_ut03_embedding_dimension | PASS |
| UT-04 | test_ut04_no_related_document_uses_baseline_fallback | PASS |
| UT-05 | test_ut05_text_around_json_is_cleaned, test_ut05_invalid_json_is_retried_then_valid_returned, test_ut05_generation_error_after_three_attempts | PASS |
| UT-06 | test_ut06_invalid_status_transition | PASS |
| UT-07 | test_ut07_masking_of_account_numbers | PASS |
| IT-01 | test_it01_short_requirement_against_40_sections | PASS |
| IT-02 | test_full_chain_to_signoff_and_st02_code_adoption | PASS |
| IT-03 | test_it03_doc_update_saves_version_and_embedding_in_one_transaction, test_it03_failure_rolls_back_everything | PASS |
| IT-04 | test_it04_missed_releases_are_replayed_in_order_after_restart | PASS |
| ST-01 | test_st01_requirement_to_impact_with_sources | PASS |
| ST-02 | test_full_chain_to_signoff_and_st02_code_adoption | PASS |
| ST-03 | test_st03_next_stage_blocked_while_pending | PASS |
| SG-01 | test_sg01_business_analyst_cannot_open_administration | PASS |
| SG-02 | test_sg02_audit_log_is_append_only | PASS |
| SG-03 | test_sg03_integration_config_holds_only_env_var_names | PASS |

## Defect table

| ID | Found in | Description | Resolution | Status |
|---|---|---|---|---|
| DEF-01 | Phase 2 | Mock impact analysis picked an unrelated service (ChargesCalculator) for the pacs.008 requirement | Generated documentation lacked the class descriptions; parser now keeps the first Javadoc sentence and the mock weights entity matches | Fixed |
| DEF-02 | Phase 2 | Service for package `payment` was named PaymentRequest (most getters) instead of PaymentService | Anchor-class heuristic now prefers role suffixes (Service, Builder, Validator …) | Fixed |
| DEF-03 | Phase 2 | UT-05: 'max 3 retries' was implemented as 3 attempts in total | First try + up to 3 retries; message and test updated | Fixed |
| DEF-04 | Phase 1 | Embedding model load hung when huggingface.co could not be reached | Local cache is tried first (local_files_only=True), download only if missing | Fixed |
| DEF-05 | Phase 5 | Streamlit 'magic' tried to display a one-line conditional expression; use_container_width is deprecated | Replaced by an if/else block and width='stretch' | Fixed |
| DEF-06 | Phase 0 | Host port 5432 (and 5433) already used by other local containers | Project database is published on host port 5460 | Fixed |

Tests marked `@pytest.mark.live` (real ADO / Confluence / Groq) are not part of this run.
