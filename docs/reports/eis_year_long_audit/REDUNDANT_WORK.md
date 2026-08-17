# REDUNDANT_WORK

REDUNDANT_DB_WORK=YES
ESTIMATED_SHARE=70–90% of current RGK UPDATEs (qualitative; updater has no dirty-check)

Evidence:

1. Live path updates **already awarded** rows (~3765 awarded vs 1584 main in 24.5 min).
2. `ContractRegistryUpdater.update` writes whenever allowed fields are non-null — no comparison to current DB values.
3. Same contract, many RGK XML versions (EIS contract registry dumps). Feb path skipped missing-from-main; current path rewrites awarded every version.
4. `file_names_xml` INSERT per XML is a second identity besides contract_number; unique conflict now skips parse (3b26815) but first-seen versions still pay INSERT+COMMIT.
5. Unresolved UPSERT ON CONFLICT DO UPDATE even when reason unchanged (JSON rewrite + COMMIT).
6. XML parsed twice per recouped file (`process_contract_file` then `parse_xml_tags_recouped_contract`).
7. OKPD extracted via `root.iter()` then again in `_enrich_rgk_okpd_and_subject`.
8. Per-row INFO logs duplicate the UPDATE.

TOTAL_RGK_XML / UNIQUE_CONTRACTS / REPEATED_VERSIONS: not countable (`file_names_xml` COUNT timed out). Proxy: 31k unresolved unique numbers vs continuous awarded UPDATEs on overlapping ids in journal.
