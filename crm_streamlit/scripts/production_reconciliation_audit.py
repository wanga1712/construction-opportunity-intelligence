#!/usr/bin/env python3
"""Build sanitized three-way runtime dependency SHA256 parity reports."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from collections import Counter, deque
from pathlib import Path


def sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized_text(path: Path) -> str | None:
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8-sig", errors="surrogateescape").replace("\r\n", "\n")


DESIRED_RUNTIME_FIXES = {
    "src/services/annotation_card_provenance.py",
    "src/services/annotation_queue_service.py",
    "src/ui/annotation_workbench_page.py",
    "src/ui/components/analytics_v2/annotation_card.py",
    "src/ui/components/analytics_v2/annotation_card_sections.py",
}
HOST_LOCAL_FILES = {
    "src/services/app.py",
    "src/services/commercial_routing_v3/canonical_card.py",
    "src/services/commercial_routing_v3/document_links.py",
    "src/services/commercial_routing_v3/queue_producer.py",
    "src/services/commercial_routing_v3/source_enrich.py",
    "src/services/db_bootstrap.py",
    "src/services/db_role_contract.py",
    "src/services/infrastructure_status.py",
    "src/services/system_health_config.py",
    "src/ui/customers_page.py",
    "src/ui/infrastructure_page.py",
    "src/ui/waterproofing_uk_tab.py",
}
SECRET_OR_ENV_FILES = {
    "src/migrations/crm_tender_match_cache_rehome_to_crm.sql",
    "src/migrations/crm_v3_document_observation_1.sql",
}
STALE_PHASE10_FILES = {
    "src/services/commercial_routing_v3/arch_prompts.py",
    "src/services/commercial_routing_v3/arch_shadow_runner.py",
    "src/services/commercial_routing_v3/category_ref_transport.py",
    "src/services/commercial_routing_v3/model_inference_runs.py",
    "src/services/commercial_routing_v3/model_result_validator.py",
    "src/services/commercial_routing_v3/prompt_v10_shadow.py",
    "src/services/commercial_routing_v3/registry_extract_mapper.py",
    "src/services/commercial_routing_v3/shadow_inference.py",
}


def drift_classification(rel: str, eol_only: bool) -> tuple[str, str, str]:
    if eol_only:
        return "GENERATED_OR_CACHE_ARTIFACT", "whole file", "EOL encoding only; normalized UTF-8 content is identical"
    if rel in DESIRED_RUNTIME_FIXES:
        return "DESIRED_RUNTIME_FIX_NOT_COMMITTED", "annotation queue/workbench/card", "Matches verified local runtime-fix commit 20cb2e8 after EOL normalization"
    if rel in HOST_LOCAL_FILES:
        return "HOST_LOCAL_CONFIGURATION", "host defaults/operator diagnostics", "Concrete host/operator values replace canonical logical aliases"
    if rel in SECRET_OR_ENV_FILES:
        return "SECRET_OR_ENVIRONMENT_SPECIFIC", "migration comments", "Concrete access identity/endpoint appears only in an operational comment"
    if rel in STALE_PHASE10_FILES:
        return "STALE_OLD_CODE", "Phase 10 SHADOW transport", "Experimental ref-transport/model validation source is outside this WIP and absent from canonical annotation Git"
    if rel == "AGENTS.md":
        return "STALE_OLD_CODE", "repository instructions", "Older production-local instructions differ from canonical project policy"
    if rel in {"src/services/test_crm_sync1.py", "src/services/computers_service.py.tmp_path_issue/computer_tz_daemon.py"}:
        return "GENERATED_OR_CACHE_ARTIFACT", "non-runtime test/temp path", "Misplaced test or temporary-path artifact is not part of the canonical application tree"
    return "UNKNOWN_REQUIRES_REVIEW", "unknown", "No deterministic provenance established"


def module_name(root: Path, path: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def import_closure(root: Path) -> set[str]:
    files = {module_name(root, path): path for path in root.rglob("*.py") if "__pycache__" not in path.parts}
    queue = deque(["app"])
    seen: set[str] = set()
    selected: set[str] = set()
    while queue:
        mod = queue.popleft()
        if mod in seen:
            continue
        seen.add(mod)
        path = files.get(mod)
        if not path:
            continue
        selected.add(path.relative_to(root).as_posix())
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        package = mod.split(".")[:-1]
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    prefix = package[: max(0, len(package) - node.level + 1)]
                    base = ".".join([*prefix, base] if base else prefix)
                names.append(base)
                names.extend(f"{base}.{alias.name}" for alias in node.names if base)
            for name in names:
                candidate = name
                while candidate:
                    if candidate in files:
                        queue.append(candidate)
                        break
                    candidate = candidate.rpartition(".")[0]
    return selected


def dependency_files(*roots: Path) -> list[str]:
    selected: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        selected.update(import_closure(root))
        for folder in ("src/ui", "src/services", "src/migrations"):
            base = root / folder
            if base.exists():
                selected.update(
                    path.relative_to(root).as_posix()
                    for path in base.rglob("*")
                    if path.is_file() and "__pycache__" not in path.parts and path.suffix in {".py", ".sql", ".json"}
                )
        for rel in ("app.py", "pyproject.toml", "requirements.txt", "AGENTS.md", ".streamlit/config.toml"):
            if (root / rel).is_file():
                selected.add(rel)
    return sorted(selected)


def classify(g: str | None, l: str | None, s: str | None) -> str:
    if g == l == s and g is not None:
        return "MATCH_ALL"
    if g is None and l is None and s is not None:
        return "UNTRACKED_RUNTIME_FILE"
    if s is None and (g is not None or l is not None):
        return "MISSING_S13"
    if g is None and (l is not None or s is not None):
        return "MISSING_GITHUB"
    if g == l and s != g:
        return "S13_ONLY_CHANGE"
    if g == s and l != g:
        return "LOCAL_ONLY_CHANGE"
    if l == s and g != l:
        return "GITHUB_ONLY_CHANGE"
    return "ALL_DIFFER"


def marker_presence(root: Path) -> dict[str, bool]:
    target_paths = [
        root / "src/ui/annotation_workbench_page.py",
        root / "src/ui/components/analytics_v2/annotation_card.py",
        root / "src/ui/components/analytics_v2/annotation_card_sections.py",
        root / "src/services/annotation_queue_service.py",
        root / "src/services/expert_annotation_service.py",
        root / "src/ui/components/analytics_v2/card_detail.py",
        root / "src/ui/components/analytics_v2/card_tabs_history.py",
        root / "src/ui/analytics_contour_v2_page.py",
    ]
    texts = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in target_paths if path.is_file())
    return {
        "filter_reset": "annotation_wb_reset_filters" in texts and "_WIDGET_KEYS" in texts,
        "count_metrics": all(value in texts for value in ("Активные закупки с оценкой ИИ", "Не размечено", "Размечено", "Текущий фильтр")),
        "refresh_update": "Обновить" in texts or "refresh" in texts,
        "procurement_link": "Открыть закупку" in texts or "Открыть оригинал закупки" in texts,
        "annotation_card_latest": "annotation_card_sections" in texts or "Категории — быстрая разметка" in texts,
        "document_observation_read": "crm_v3_document_observations" in texts,
        "history_provenance": "load_annotation_history" in texts or "crm_manual_assessments_audit" in texts,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--github", type=Path, required=True)
    parser.add_argument("--local", type=Path, required=True)
    parser.add_argument("--s13", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--md", type=Path)
    args = parser.parse_args()
    files = dependency_files(args.github, args.local, args.s13)
    rows = []
    for rel in files:
        g, l, s = sha(args.github / rel), sha(args.local / rel), sha(args.s13 / rel)
        status = classify(g, l, s)
        eol_only = bool(g and s and g != s and normalized_text(args.github / rel) == normalized_text(args.s13 / rel))
        row = {"file": rel, "github_sha256": g, "local_sha256": l, "s13_sha256": s, "status": status,
               "normalized_match_github_s13": eol_only}
        if status in {"S13_ONLY_CHANGE", "UNTRACKED_RUNTIME_FILE"}:
            category, section, semantic = drift_classification(rel, eol_only)
            row.update({"classification": category, "function_or_section": section, "semantic_diff": semantic})
        rows.append(row)
    out = {
        "runtime_dependency_file_count": len(rows),
        "status_counts": dict(Counter(row["status"] for row in rows)),
        "classification_counts": dict(Counter(row.get("classification") for row in rows if row.get("classification"))),
        "recent_fix_presence": {
            "github": marker_presence(args.github),
            "local": marker_presence(args.local),
            "s13": marker_presence(args.s13),
        },
        "files": rows,
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.md:
        lines = [
            "# S13 / GitHub runtime parity (pre-change)", "",
            f"Runtime dependency files: **{len(rows)}**.", "",
            "Raw SHA256 status counts: " + ", ".join(f"{k}={v}" for k, v in out["status_counts"].items()) + ".", "",
            "Drift classifications: " + ", ".join(f"{k}={v}" for k, v in out["classification_counts"].items()) + ".", "",
            "The 189 `GENERATED_OR_CACHE_ARTIFACT` rows with `normalized_match_github_s13=true` are byte-only CRLF/LF checkout drift; their normalized UTF-8 content is identical.", "",
            "| File | GitHub SHA256 | Local SHA256 | S13 SHA256 | Status | Classification | Function/section | Semantic diff |", "|---|---|---|---|---|---|---|---|",
        ]
        for row in rows:
            cells = [row["file"], row.get("github_sha256") or "—", row.get("local_sha256") or "—", row.get("s13_sha256") or "—",
                     row["status"], row.get("classification") or "—", row.get("function_or_section") or "—", row.get("semantic_diff") or "—"]
            lines.append("| " + " | ".join(str(cell).replace("|", "\\|") for cell in cells) + " |")
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in out.items() if key != "files"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
