from __future__ import annotations

from pathlib import Path

import pytest

from document_processor.documentation_links_loader import (
    SourceLinkIdentityError,
    SourceLinkMappingError,
    SourceLinksRepository,
    SourceProcurementIdentity,
)


class FakeDB:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.error = error
        self.calls = []

    def execute_query(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        return self.rows


def identity(number="0173200001424001779"):
    return SourceProcurementIdentity(
        source_table="reestr_contract_44_fz_awarded",
        source_id=316812,
        registry_number=number,
        source_type="44",
    )


def test_native_number_lookup_never_uses_reestr_row_id() -> None:
    db = FakeDB([("https://source/a", "a.pdf")])
    links = SourceLinksRepository(db, "tender_monitor").resolve_links(identity())
    assert links == [("https://source/a", "a.pdf")]
    sql = db.calls[0][0][1]
    params = db.calls[0][0][2]
    assert "contract_number = %s" in sql
    assert "contract_id" not in sql
    assert params == ("0173200001424001779",)


def test_compatibility_api_ignores_legacy_reestr_ids() -> None:
    db = FakeDB([("https://source/a", "a.pdf")])
    links = SourceLinksRepository(db, "tender_monitor").load_for_contract(
        "links_documentation_44_fz",
        "0173200001424001779",
        [316812, 999999],
    )
    assert links == [("https://source/a", "a.pdf")]
    sql = db.calls[0][0][1]
    params = db.calls[0][0][2]
    assert "contract_id" not in sql
    assert params == ("0173200001424001779",)


def test_genuine_no_links_is_empty_result() -> None:
    db = FakeDB([])
    assert SourceLinksRepository(db, "tender_monitor").resolve_links(identity("zero")) == []


@pytest.mark.parametrize(
    "bad_identity",
    [
        SourceProcurementIdentity("reestr_contract_44_fz", 1, "", "44"),
        SourceProcurementIdentity("unsupported", 1, "123", "615"),
        SourceProcurementIdentity("reestr_contract_223_fz", 1, "123", "44"),
    ],
)
def test_unsupported_identity_is_not_no_links(bad_identity) -> None:
    with pytest.raises(SourceLinkIdentityError, match="SOURCE_LINK_IDENTITY_UNSUPPORTED"):
        SourceLinksRepository(FakeDB(), "tender_monitor").resolve_links(bad_identity)


def test_schema_failure_is_explicit_and_not_swallowed() -> None:
    db = FakeDB(error=RuntimeError("column missing"))
    with pytest.raises(SourceLinkMappingError, match="SOURCE_LINK_MAPPING_ERROR"):
        SourceLinksRepository(db, "tender_monitor").resolve_links(identity())


def test_duplicate_links_are_deduplicated_deterministically() -> None:
    db = FakeDB(
        [
            ("HTTPS://SOURCE/a?b=2&a=1", "A.PDF"),
            ("https://source/a?a=1&b=2", "a.pdf"),
            ("https://source/b", "b.pdf"),
        ]
    )
    links = SourceLinksRepository(db, "tender_monitor").resolve_links(identity())
    assert links == [
        ("HTTPS://SOURCE/a?b=2&a=1", "A.PDF"),
        ("https://source/b", "b.pdf"),
    ]


def test_production_source_has_no_exception_driven_column_guessing() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "document_processor"
        / "documentation_links_loader.py"
    ).read_text(encoding="utf-8")
    assert "contract_id IN" not in source
    assert "sql_by_number" not in source
    assert "except Exception:\n            pass" not in source
