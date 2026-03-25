import subprocess
import zipfile
import os

zip_path = "github-release-latest-v2.zip"

print(f"Creating {zip_path}...")
with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    # Get all files in the branch
    result = subprocess.run(["git", "ls-tree", "-r", "--name-only", "github-release"], capture_output=True, text=True)
    if result.returncode != 0:
        print("Error getting file list from git.")
        exit(1)
        
    files = result.stdout.strip().split('\n')
    for f in files:
        if not f: continue
        # Get file content
        content_result = subprocess.run(["git", "show", f"github-release:{f}"], capture_output=True)
        if content_result.returncode == 0:
            zf.writestr(f, content_result.stdout)
        else:
            print(f"Failed to read {f}")

print("Zip created successfully.")