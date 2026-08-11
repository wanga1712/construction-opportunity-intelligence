from pathlib import Path

from document_processor.pipelines.s13_v2_pipeline import _archive_parent_identity


def test_archive_parent_identity_for_nested_member(tmp_path: Path) -> None:
    archive = tmp_path / 'archive.zip'
    archive.write_bytes(b'PK')
    member = tmp_path / 'archive' / 'docs' / 'spec.xls'
    member.parent.mkdir(parents=True)
    member.write_bytes(b'xls')

    assert _archive_parent_identity(member) == (
        'archive.zip',
        str(archive),
        'docs/spec.xls',
    )


def test_archive_parent_identity_none_for_source_file(tmp_path: Path) -> None:
    source = tmp_path / 'source.pdf'
    source.write_bytes(b'pdf')

    assert _archive_parent_identity(source) == (None, None, None)
