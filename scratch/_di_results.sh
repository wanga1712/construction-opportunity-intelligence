#!/bin/bash
PSQL="sudo -n -u postgres psql -d document_intelligence -Atc"
echo "--- document_processing_results columns ---"
$PSQL "select column_name||' '||data_type from information_schema.columns where table_name='document_processing_results' order by ordinal_position"
echo "--- sample row (truncated) ---"
$PSQL "select left(row_to_json(t)::text, 900) from document_processing_results t order by id desc limit 2"
echo "--- document_files columns ---"
$PSQL "select column_name||' '||data_type from information_schema.columns where table_name='document_files' order by ordinal_position"
