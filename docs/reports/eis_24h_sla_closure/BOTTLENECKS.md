# BOTTLENECKS

Ranked by observed wall-time / live evidence. Not by load average alone.

## 1. recouped / RGK contract sync (PRIMARY)

Before the UNION fix, every RGK lookup failed SQL then retried other paths. After the fix, journal shows ~2 awarded-contract UPDATEs per second at CPU ~61%.

This is still the dominant work for the current region of 2026-08-12. File-level `Finished file` prints are gated off by default, so file counts are no longer in journal.

Optimizations applied without changing business result:

- valid one-query lookup
- reuse one `AdvancedXMLParser` / `RecoupedContractSync` / `DatabaseManager` per folder
- `DatabaseOperations(db_manager=self._db)` on canonical insert
- in-process non-target version cache (already present)
- skip already-inserted XML names (`insert_file_name` IntegrityError → skip + rollback)

Not done: bulk RGK lookup across many contract numbers in one SQL; moving RGK off the critical path. Those would need a separate correctness plan.

`CPU_BOUND=PARTIAL` (61% on parser PID)
`DB_BOUND=YES` (per-contract UPDATE + lookup)
`DISK_IO_BOUND=NOT_PROVEN`
`NETWORK_BOUND=NOT_PROVEN` (SOAP not in the current recouped burst)
`SERIAL_CODE_BOUND=YES` (one XML / one contract at a time)

## 2. Database roundtrips / new connection per XML (mitigated)

Before: `DatabaseOperations()` and `DatabaseIDFetcher()` and `XMLParser()` per file, each opening PostgreSQL. After: one parser/connection per folder.

## 3. 223-FZ `.//document` xpath

Still per XML file in `required_tags_223_fz.json`. Wall-time share not measured on this source-date because the live process is still in 44-FZ RGK for the current region. Not optimized blindly.

## 4. Repeat processing

File exact-repeat skip is now active: `insert_file_name` returning None skips and deletes the local XML. IntegrityError rolls back so a shared connection is not left aborted.

## 223-FZ mapping invariants (unchanged)

Pinned by `eis_ingestion/tests/test_s7_recovery_opts.py`.
