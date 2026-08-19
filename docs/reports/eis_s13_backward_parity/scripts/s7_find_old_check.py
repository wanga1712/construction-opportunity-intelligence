with open('/tmp/isolated_db_rgk_replay.py') as f:
    c = f.read()
print("old_check_count=" + str(c.count("production file_names_xml changed")))
print("old_check2_count=" + str(c.count("prod_files_before != prod_files_after")))
