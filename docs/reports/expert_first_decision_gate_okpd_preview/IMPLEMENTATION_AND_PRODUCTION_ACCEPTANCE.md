# CRM-V3 expert first decision gate and OKPD preview

Date: 2026-08-25 (Europe/Moscow)  
Result: **PASS / STOP**  
Implementation commit: `b47f4241e35f8bb233cbfc50794af56409100c41`

## Delivered behavior

- The real inline Analytics card now asks the first human question, `Закупка относится к нашему профилю?`, before the advanced workspace and exposes `Да / Нет / Не уверен`.
- `Нет` opens a fast, optional-reason path and `Сохранить и следующая →`. Persistence reuses `_build_out_of_profile_payload`; category, object, stage and medal are not required.
- `Да` keeps the existing advanced expert form available and editable. It does not copy model suggestions into expert fields and does not invent a new positive-scope persistence contract.
- `Не уверен` is an unresolved session draft; it is not persisted as `NOT_INTERESTING` or a fabricated assessment.
- Model suggestions are explicitly read-only and visually separated from expert inputs. Advanced labels and medal choices are human-readable.
- A factual `ОКПД2: code — name` preview is rendered only when data exists. It uses the already batch-loaded card fields and adds zero per-card SQL.

## Authority and boundaries

No model, prompt, model input, inference queue/worker, publication, document resolver/pipeline, parser, schema or DDL was changed. Superuser-role authority was unavailable, so no role-specific alternate form was invented; the existing advanced form remains preserved for the current operator route. The optional rejection reason is an additive JSON field (`expert_out_of_profile_reason`) and does not alter canonical scope-state semantics.

## Control procurement

- CRM id: `11235`
- Title: `Поставка медицинских изделий (перчатки нитриловые) для нужд ФГБУ «НМИЦ пульмонологии» ФМБА России`
- Law/source: `44-ФЗ` / `reestr_contract_44_fz`
- OKPD2: `22.19 — Изделия из резины прочие`
- Initial AI state: `UNASSESSED`
- Initial/current human scope annotation: absent

The production acceptance selected UI decisions but did not press either save button. A final read-only check therefore remains the rollback-equivalent safety proof: no production annotation was created and AI state stayed `UNASSESSED`. Payload construction and fast-save behavior are covered by isolated tests; no fake production assessment was needed.

## Verification

### Automated tests

- Focused local suite: **33 passed** (`test_expert_first_decision_gate.py`, `test_analytics_stage_workspace.py`, `test_expert_annotation_ui.py`, `test_annotation_state_service.py`).
- Focused S13 suite using the deployed runtime: **33 passed**.
- Python compilation: **PASS**.
- Broad runnable repository suite: **708 passed, 31 failed, 8 errors, 3 skipped, 391 subtests passed**. The failures/errors are pre-existing environment/fixture/artifact debt, including the unavailable external `pythonProject89/modules` source root; none intersects the changed focused suite.

### Real route AppTest

Route: `app.py → objects_v2 → Аналитический контур v2 → Идут торги`.

Result: **PASS**, zero Streamlit exceptions. The visible card was control CRM id `11235`; title, amount, deadline, law, customer, region, OKPD2, source link, first question and all three decisions were visible. The NO branch exposed the message, optional reason and SAVE+NEXT. The advanced workspace remained accessible and raw technical field labels were absent.

### Visual acceptance

Production screenshots are stored beside this report:

- `real_route_card.png` — factual card and primary decision gate;
- `real_route_fast_no.png` and `real_route_fast_no_save_next.png` — fast negative path;
- `real_route_advanced.png` — read-only model area and expert workspace;
- `real_route_medal.png` — human-facing advanced labels and medal field.

### Deployment

The changed runtime files were copied to S13, line endings normalized, hashes checked against the worktree, `git diff --check` passed, and only `crm-streamlit.service` was restarted. Post-restart service state was active and HTTP returned 200. Candidate inference remained disabled; no enqueue, inference, annotation save, DDL or unrelated service action occurred.

## Module-size note

`stage_workspace.py` is 164 lines. `annotation_card.py` is 757 lines versus the pre-existing 633-line stateful form boundary. The added first-decision branch shares the same Streamlit session keys, rerun behavior and canonical persistence helper as the advanced form; splitting that transaction boundary in this narrowly constrained UI WIP would raise behavioral risk. The already recorded Stage 2 component decomposition remains the appropriate place for broader extraction.

## Closure

All requested acceptance gates passed. This WIP stops here; no next stage is started.
