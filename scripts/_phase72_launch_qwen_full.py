#!/usr/bin/env python3
"""Launch Phase 7.2 full Qwen baseline arm (same scorer as T-lite)."""
from __future__ import annotations

import subprocess
from pathlib import Path


def main() -> None:
    uid = subprocess.check_output(["id", "-u"], text=True).strip()
    gid = subprocess.check_output(["id", "-g"], text=True).strip()
    Path("/tmp/phase72_qwen_full.json").unlink(missing_ok=True)
    wrapper = Path("/tmp/phase72_qwen_full_wrap.sh")
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "cd /opt/CRM_Streamlit\n"
        "export PYTHONPATH=/opt/CRM_Streamlit:/opt/pythonProject89\n"
        "export PHASE72_MODE=full\n"
        "export PHASE72_ARMS=qwen\n"
        "export PHASE72_OUT=/tmp/phase72_qwen_full.json\n"
        "export PHASE72_FORMAT_JSON=1\n"
        "exec /opt/CRM_Streamlit/.venv313/bin/python -u "
        "scripts/_phase72_t_lite_bakeoff.py "
        ">>/tmp/phase72_qwen_full.log 2>&1\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    Path("/tmp/phase72_qwen_full.log").write_text("", encoding="utf-8")
    cmd = [
        "sudo",
        "-n",
        "systemd-run",
        f"--uid={uid}",
        f"--gid={gid}",
        "--slice=crm-background-compute.slice",
        "--unit=crm-phase72-qwen-full.service",
        "--working-directory=/opt/CRM_Streamlit",
        "--property=CPUWeight=50",
        "--property=Nice=5",
        "--collect",
        "/bin/bash",
        str(wrapper),
    ]
    print(subprocess.check_output(cmd, text=True))


if __name__ == "__main__":
    main()
