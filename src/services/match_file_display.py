"""Отображение имён файлов совпадений и ссылки на скачивание."""
from __future__ import annotations

import os
import re
from urllib.parse import parse_qs, urlparse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HASH_FILE_RE = re.compile(
    r"^file_[0-9A-Fa-f]{8,}\.(pdf|xlsx?|xls|docx?|doc)$",
    re.IGNORECASE,
)


def _norm_path(path: str) -> str:
    return (path or "").replace("\\", "/")


def _basename(path: str) -> str:
    return os.path.basename(_norm_path(path))


def _parent_name(path: str) -> str:
    return os.path.basename(os.path.dirname(_norm_path(path)))


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _is_hash_name(name: str) -> bool:
    return bool(_HASH_FILE_RE.match((name or "").strip()))


def _hash_from_file_name(name: str) -> str:
    m = _HASH_FILE_RE.match((name or "").strip())
    if not m:
        return ""
    stem = (name or "").rsplit(".", 1)[0]
    return stem.removeprefix("file_").upper()


def _uid_from_url(url: str) -> str:
    try:
        query = parse_qs(urlparse(url or "").query)
    except Exception:
        return ""
    values = query.get("uid") or query.get("fileUid") or []
    return (values[0] if values else "").strip().upper()


def _match_file_uids(mf: Dict[str, Any]) -> set[str]:
    uids: set[str] = set()
    for raw in [mf.get("file_name"), mf.get("yandex_path")]:
        base = _basename(_norm_path(raw or ""))
        uid = _hash_from_file_name(base)
        if uid:
            uids.add(uid)
    for d in mf.get("details") or []:
        base = _basename(_norm_path(d.get("source_file") or ""))
        uid = _hash_from_file_name(base)
        if uid:
            uids.add(uid)
    return uids


def _path_tokens(mf: Dict[str, Any]) -> List[str]:
    tokens: List[str] = []
    for key in ("yandex_path",):
        raw = mf.get(key)
        if raw:
            tokens.extend(_norm_path(raw).lower().split("/"))
    for d in mf.get("details") or []:
        sf = _norm_path(d.get("source_file") or "")
        if sf:
            tokens.append(sf.lower())
            tokens.extend(p for p in sf.lower().split("/") if p)
    folder = (mf.get("folder_name") or "").strip()
    if folder:
        tokens.append(folder.lower())
    return tokens


def find_related_platform_documents(
    mf: Dict[str, Any],
    documents: List[Dict[str, Any]],
    *,
    contract_number: str | None = None,
) -> List[Dict[str, Any]]:
    """Документы площадки, связанные с файлом совпадения (может быть несколько)."""
    if not documents:
        return []

    folder = (mf.get("folder_name") or "").strip()
    folder_digits = _digits(folder)
    contract_digits = _digits(contract_number or "")
    path_tokens = _path_tokens(mf)
    match_uids = _match_file_uids(mf)

    scored: List[tuple[int, Dict[str, Any]]] = []
    for doc in documents:
        name = (doc.get("file_name") or "").strip()
        if not name:
            continue
        doc_uid = _uid_from_url(doc.get("url") or "")
        name_lower = name.lower()
        stem = name_lower.rsplit(".", 1)[0]
        doc_digits = _digits(name)
        score = 0

        if doc_uid and doc_uid in match_uids:
            score += 1000

        if folder_digits and len(folder_digits) >= 6:
            if folder_digits in doc_digits:
                score += 60
            if folder.lower() in name_lower:
                score += 50

        if contract_digits and len(contract_digits) >= 6:
            if contract_digits in doc_digits:
                score += 55
            if contract_number and contract_number.lower() in name_lower:
                score += 45

        for token in path_tokens:
            if len(token) < 3:
                continue
            if stem and (stem in token or token in stem):
                score += 35
            if stem and stem in token:
                score += 20

        if score > 0:
            scored.append((score, doc))

    scored.sort(key=lambda x: (-x[0], x[1].get("file_name") or ""))

    seen: set[str] = set()
    result: List[Dict[str, Any]] = []
    for _, doc in scored:
        url = doc.get("url") or ""
        key = url or doc.get("file_name") or ""
        if key in seen:
            continue
        seen.add(key)
        result.append(doc)

    if result:
        return result

    if contract_digits:
        for doc in documents:
            if contract_digits in _digits(doc.get("file_name") or ""):
                result.append(doc)
        if result:
            return result

    if len(documents) == 1:
        return documents

    return []


def documents_for_download(
    mf: Dict[str, Any],
    documents: List[Dict[str, Any]],
    *,
    contract_number: str | None = None,
) -> List[Dict[str, Any]]:
    """Документы для скачивания: связанные или вся документация закупки."""
    related = find_related_platform_documents(
        mf, documents, contract_number=contract_number,
    )
    return related if related else list(documents)


def find_platform_document(
    mf: Dict[str, Any],
    documents: List[Dict[str, Any]],
    *,
    contract_number: str | None = None,
) -> Optional[Dict[str, Any]]:
    related = find_related_platform_documents(
        mf, documents, contract_number=contract_number,
    )
    return related[0] if related else None


def _named_documents(
    related_docs: List[Dict[str, Any]] | None,
    fallback_documents: List[Dict[str, Any]] | None,
) -> List[Dict[str, Any]]:
    if related_docs:
        return related_docs
    # Не подставляем всю документацию закупки как имя файла совпадения.
    # Иначе несколько разных внутренних файлов выглядят одинаково:
    # "Извещение..." / "Описание объекта..." и т.п.
    return []


def resolve_match_display_name(
    mf: Dict[str, Any],
    platform_doc: Optional[Dict[str, Any]] = None,
    *,
    contract_number: str | None = None,
    related_docs: List[Dict[str, Any]] | None = None,
    fallback_documents: List[Dict[str, Any]] | None = None,
) -> str:
    """Человекочитаемое имя для заголовка блока совпадений."""
    name_docs = _named_documents(related_docs, fallback_documents)

    # Для совпадений внутри архивов реальное имя лежит в details.source_file;
    # имя документа площадки часто является общим «Извещение...». 
    for d in mf.get("details") or []:
        sf = _norm_path(d.get("source_file") or "")
        base = _basename(sf)
        if base and not _is_hash_name(base):
            return base

    if platform_doc:
        plat_name = (platform_doc.get("file_name") or "").strip()
        if plat_name:
            return plat_name

    if name_docs:
        primary = (name_docs[0].get("file_name") or "").strip()
        if primary:
            if len(name_docs) > 1:
                return f"{primary} (+{len(name_docs) - 1})"
            return primary

    stored = (mf.get("file_name") or "").strip()
    for d in mf.get("details") or []:
        sf = _norm_path(d.get("source_file") or "")
        if not sf:
            continue
        base = _basename(sf)
        if base and not _is_hash_name(base):
            return base

    yp = _norm_path(mf.get("yandex_path") or "")
    if yp:
        base = _basename(yp)
        if base and not _is_hash_name(base):
            return base

    inner = inner_match_file_name(mf)
    if inner:
        ext = Path(inner).suffix.lower().lstrip(".") or "файл"
        return f"Внутренний {ext.upper()} с совпадениями · {inner}"
    cn = (contract_number or mf.get("folder_name") or "").strip()
    if cn:
        return f"Документация № {cn}"
    if stored and not _is_hash_name(stored):
        return stored
    return "Документ с совпадениями"


def inner_match_file_name(mf: Dict[str, Any]) -> Optional[str]:
    """Техническое имя внутреннего файла (file_XXXX.pdf), если есть."""
    stored = (mf.get("file_name") or "").strip()
    if stored and _is_hash_name(stored):
        return stored
    for d in mf.get("details") or []:
        base = _basename(_norm_path(d.get("source_file") or ""))
        if base and _is_hash_name(base):
            return base
    return None


def local_file_path(mf: Dict[str, Any]) -> Optional[Path]:
    """Путь к локальному файлу, если он существует на машине с CRM."""
    candidates: List[str] = []
    if mf.get("yandex_path"):
        candidates.append(mf["yandex_path"])
    for d in mf.get("details") or []:
        if d.get("source_file"):
            candidates.append(d["source_file"])

    for raw in candidates:
        p = Path(raw)
        if p.is_file():
            return p
    return None


def local_download_name(mf: Dict[str, Any], path: Path) -> str:
    display = resolve_match_display_name(mf)
    if "→" in display:
        display = display.split("→")[-1].strip()
    if _is_hash_name(display):
        return path.name
    return display
