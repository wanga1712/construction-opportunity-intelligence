import os
import shutil
import subprocess

src_repo = "C:/Users/Lenovo/Projects/CRM_Streamlit"
dst_dir = "C:/Users/Lenovo/Projects/canonical_repo/crm_streamlit"

def get_tracked_files():
    out = subprocess.check_output(["git", "-C", src_repo, "ls-files"]).decode("utf-8")
    files = []
    for line in out.splitlines():
        line = line.strip().strip('"').replace('\\\\', '/').replace('\\', '/')
        if line:
            files.append(line)
    return files

def main():
    tracked = get_tracked_files()
    print(f"Found {len(tracked)} tracked files in CRM_Streamlit")
    
    # Clean dst_dir first
    if os.path.exists(dst_dir):
        print(f"Cleaning dst dir: {dst_dir}")
        shutil.rmtree(dst_dir)
    os.makedirs(dst_dir, exist_ok=True)
    
    # Copy files preserving subdirs
    copied = 0
    for f in tracked:
        src_path = os.path.join(src_repo, f)
        dst_path = os.path.join(dst_dir, f)
        
        # Create directories if they do not exist
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        try:
            shutil.copy2(src_path, dst_path)
            copied += 1
        except Exception as e:
            print(f"Error copying {src_path} -> {dst_path}: {e}")
        
    print(f"Successfully copied {copied} files to {dst_dir}")

if __name__ == "__main__":
    main()
