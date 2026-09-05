import os
import filecmp

def compare_dirs(dir1, dir2):
    dcmp = filecmp.dircmp(dir1, dir2)
    if dcmp.left_only:
        print(f"Only in {dir1}: {dcmp.left_only}")
    if dcmp.right_only:
        print(f"Only in {dir2}: {dcmp.right_only}")
    if dcmp.diff_files:
        print(f"Different files in {dir1} and {dir2}: {dcmp.diff_files}")
    for sub in dcmp.subdirs.values():
        compare_dirs(sub.left, sub.right)

print("Comparing src:")
compare_dirs("C:/Users/Lenovo/Projects/CRM_Streamlit/src", "C:/Users/Lenovo/Projects/canonical_repo/crm_streamlit/src")
