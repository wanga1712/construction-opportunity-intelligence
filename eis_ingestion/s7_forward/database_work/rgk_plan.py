"""Plan 44-FZ RGK batch mutations. Pure functions, no DB I/O."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

from database_work.rgk_dirty import row_is_dirty
from database_work.registry_tables import ALLOWED_UPDATE_FIELDS, tables_for_fz
from parsing_xml.rgk_record import RGKRecord

PLACEHOLDER_TITLE_PREFIX = "Контракт "
MAIN_44 = tables_for_fz("44").main
AWARDED_44 = tables_for_fz("44").awarded


@dataclass
class UnresolvedWrite:
    contract_number: str
    reason: str
    fields: dict[str, Any]
    is_new: bool


@dataclass
class RegistryWrite:
    contract_number: str
    table_name: str
    record_id: Optional[int]
    fields: dict[str, Any]
    promote: bool = False
    insert: bool = False


@dataclass
class BatchPlan:
    records: list[RGKRecord] = field(default_factory=list)
    skip_filenames: set[str] = field(default_factory=set)
    skip_versions: set[str] = field(default_factory=set)
    updates: list[RegistryWrite] = field(default_factory=list)
    inserts: list[RegistryWrite] = field(default_factory=list)
    promotes: list[RegistryWrite] = field(default_factory=list)
    unresolved: list[UnresolvedWrite] = field(default_factory=list)
    filenames: list[str] = field(default_factory=list)
    remember_versions: list[str] = field(default_factory=list)
    metrics: dict[str, int] = field(default_factory=dict)

    def links(self) -> list[dict[str, Any]]:
        by_number = {item.contract_number: item for item in self.inserts + self.updates + self.promotes}
        out: list[dict[str, Any]] = []
        for record in self.records:
            if record.file_name in self.skip_filenames or record.version_key in self.skip_versions:
                continue
            target = by_number.get(record.contract_number)
            if target is None or not record.document_links:
                continue
            for link in record.document_links:
                out.append(
                    {
                        "file_name": link.get("file_name"),
                        "document_links": link.get("document_links"),
                        "contract_number": record.contract_number,
                        "contract_id": target.record_id,
                    }
                )
        return out


def _canonical_okpd_id(fields: Mapping[str, Any]) -> Optional[int]:
    if fields.get("okpd_id") is None:
        return None
    try:
        return int(fields["okpd_id"])
    except (TypeError, ValueError):
        return None


def _canonical_title(fields: Mapping[str, Any], contract_number: str) -> Optional[str]:
    title = fields.get("auction_name")
    if not title or not str(title).strip():
        return None
    title = str(title).strip()
    if title.startswith(PLACEHOLDER_TITLE_PREFIX):
        return None
    if title == f"{PLACEHOLDER_TITLE_PREFIX}{contract_number}":
        return None
    return title


def _should_promote_44(table_name: str, fields: Mapping[str, Any]) -> bool:
    if table_name.endswith("_awarded") or table_name.endswith("_completed"):
        return False
    suffixes = ("_unknown", "_unclear", "_commission_work")
    promotable = table_name == MAIN_44 or any(table_name.endswith(s) for s in suffixes)
    if not promotable:
        return False
    return fields.get("contractor_id") is not None and fields.get("delivery_end_date") is not None


def _update_payload(fields: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in fields.items()
        if key in ALLOWED_UPDATE_FIELDS and value is not None and value != ""
    }


def _unresolved_changed(
    existing: Optional[Mapping[str, Any]], reason: str, fields: Mapping[str, Any]
) -> bool:
    if existing is None:
        return True
    if str(existing.get("reason") or "") != reason:
        return True
    old_subject = existing.get("contract_subject")
    new_subject = fields.get("auction_name") or fields.get("contract_subject")
    if (old_subject or None) != (new_subject or None):
        return True
    old_codes = list(existing.get("okpd_codes") or [])
    new_codes = list(fields.get("okpd_codes") or [])
    return old_codes != new_codes


def _overlay_state(row: dict[str, Any], fields: Mapping[str, Any]) -> dict[str, Any]:
    updated = dict(row)
    for key in (
        "final_price",
        "contractor_id",
        "delivery_start_date",
        "delivery_end_date",
        "auction_name",
        "okpd_id",
    ):
        if fields.get(key) is not None and fields.get(key) != "":
            updated[key] = fields[key]
    return updated


def resolve_okpd_id(codes: Iterable[str], okpd_map: Mapping[str, int]) -> Optional[int]:
    for code in codes:
        okpd_id = okpd_map.get(code)
        if okpd_id is not None:
            return int(okpd_id)
    return None


def _queue_unresolved(
    pending: dict[str, UnresolvedWrite],
    unresolved_map: Mapping[str, Mapping[str, Any]],
    metrics: dict[str, int],
    contract_number: str,
    reason: str,
    fields: dict[str, Any],
) -> None:
    existing = unresolved_map.get(contract_number)
    changed = _unresolved_changed(existing, reason, fields)
    write = UnresolvedWrite(contract_number, reason, fields, existing is None)
    pending[contract_number] = write
    if changed:
        metrics["unresolved"] += 1
        if write.is_new:
            metrics["unresolved_new"] += 1
        else:
            metrics["unresolved_changed"] += 1
    else:
        metrics["unresolved_unchanged"] += 1


def plan_44_batch(
    records: list[RGKRecord],
    *,
    known_filenames: set[str],
    okpd_map: Mapping[str, int],
    contractor_map: Mapping[str, int],
    registry_map: Mapping[str, dict],
    unresolved_map: Mapping[str, Mapping[str, Any]],
    version_cache: Mapping[str, Any],
) -> BatchPlan:
    plan = BatchPlan(records=list(records))
    state: dict[str, dict] = {key: dict(value) for key, value in registry_map.items()}
    pending: dict[str, RegistryWrite] = {}
    unresolved_pending: dict[str, UnresolvedWrite] = {}
    metrics = {
        "input": len(records),
        "duplicates": 0,
        "found": 0,
        "changed": 0,
        "unchanged": 0,
        "promoted": 0,
        "inserted": 0,
        "unresolved": 0,
        "unresolved_new": 0,
        "unresolved_changed": 0,
        "unresolved_unchanged": 0,
        "updates_skipped": 0,
    }

    for record in records:
        if record.file_name in known_filenames:
            plan.skip_filenames.add(record.file_name)
            metrics["duplicates"] += 1
            continue
        if record.version_key and record.version_key in version_cache:
            plan.skip_versions.add(record.version_key)
            metrics["duplicates"] += 1
            continue

        okpd_id = resolve_okpd_id(record.okpd_codes, okpd_map)
        record.okpd_id = okpd_id
        if okpd_id is not None:
            for code in record.okpd_codes:
                if okpd_map.get(code) == okpd_id:
                    record.okpd_code = code
                    break
        if record.contractor_inn:
            record.contractor_id = contractor_map.get(record.contractor_inn)

        fields = record.as_fields()
        row = state.get(record.contract_number)
        if record.okpd_codes and okpd_id is None and row is None:
            _queue_unresolved(
                unresolved_pending, unresolved_map, metrics,
                record.contract_number, "MISSING_OKPD_ID", fields,
            )
            if record.version_key:
                plan.remember_versions.append(record.version_key)
            plan.filenames.append(record.file_name)
            continue

        if row is None:
            title = _canonical_title(fields, record.contract_number)
            canonical_okpd = _canonical_okpd_id(fields)
            if canonical_okpd is None or title is None:
                reason = "MISSING_OKPD_ID" if canonical_okpd is None else "MISSING_REAL_TITLE"
                if canonical_okpd is None and title is None:
                    reason = "MISSING_OKPD_AND_TITLE"
                _queue_unresolved(
                    unresolved_pending, unresolved_map, metrics,
                    record.contract_number, reason, fields,
                )
                plan.filenames.append(record.file_name)
                continue

            insert_fields = dict(fields)
            insert_fields["okpd_id"] = canonical_okpd
            insert_fields["auction_name"] = title
            insert_fields.setdefault("initial_price", 0)
            insert_fields.setdefault(
                "tender_link",
                "https://zakupki.gov.ru/epz/contract/contractCard/common-info.html"
                f"?reestrNumber={record.contract_number}",
            )
            write = RegistryWrite(
                contract_number=record.contract_number,
                table_name=MAIN_44,
                record_id=None,
                fields=insert_fields,
                insert=True,
                promote=_should_promote_44(MAIN_44, insert_fields),
            )
            pending[record.contract_number] = write
            state[record.contract_number] = {
                "table_name": AWARDED_44 if write.promote else MAIN_44,
                "record_id": None,
                "contract_number": record.contract_number,
                "final_price": insert_fields.get("final_price"),
                "contractor_id": insert_fields.get("contractor_id"),
                "delivery_start_date": insert_fields.get("delivery_start_date"),
                "delivery_end_date": insert_fields.get("delivery_end_date"),
                "auction_name": title,
                "okpd_id": canonical_okpd,
            }
            plan.filenames.append(record.file_name)
            metrics["inserted"] += 1
            if write.promote:
                metrics["promoted"] += 1
            continue

        pending_write = pending.get(record.contract_number)
        if pending_write and pending_write.insert:
            pending_write.fields.update(_update_payload(fields))
            pending_write.promote = pending_write.promote or _should_promote_44(
                MAIN_44, pending_write.fields
            )
            state[record.contract_number] = _overlay_state(row, fields)
            if pending_write.promote:
                state[record.contract_number]["table_name"] = AWARDED_44
            plan.filenames.append(record.file_name)
            continue

        metrics["found"] += 1
        promote = _should_promote_44(row["table_name"], fields)
        if row_is_dirty(row, fields):
            write = RegistryWrite(
                contract_number=record.contract_number,
                table_name=row["table_name"],
                record_id=row.get("record_id"),
                fields=_update_payload(fields),
                promote=promote,
            )
            pending[record.contract_number] = write
            state[record.contract_number] = _overlay_state(row, fields)
            if promote:
                state[record.contract_number]["table_name"] = AWARDED_44
                metrics["promoted"] += 1
            metrics["changed"] += 1
        else:
            metrics["unchanged"] += 1
            metrics["updates_skipped"] += 1
            if promote:
                write = pending.get(record.contract_number) or RegistryWrite(
                    contract_number=record.contract_number,
                    table_name=row["table_name"],
                    record_id=row.get("record_id"),
                    fields=_update_payload(fields),
                    promote=True,
                )
                write.promote = True
                pending[record.contract_number] = write
                state[record.contract_number]["table_name"] = AWARDED_44
                metrics["promoted"] += 1
        plan.filenames.append(record.file_name)

    plan.inserts = [write for write in pending.values() if write.insert]
    plan.updates = [
        write
        for write in pending.values()
        if not write.insert and write.record_id is not None and write.fields
        and row_is_dirty(registry_map.get(write.contract_number) or {}, write.fields)
    ]
    plan.promotes = [write for write in pending.values() if write.promote]
    plan.unresolved = [
        item
        for item in unresolved_pending.values()
        if item.is_new
        or _unresolved_changed(unresolved_map.get(item.contract_number), item.reason, item.fields)
    ]
    plan.metrics = metrics
    plan.filenames = list(dict.fromkeys(plan.filenames))
    return plan
