#!/usr/bin/env python3
"""Deploy arch files to S13 and launch under background-compute slice."""
from __future__ import annotations

import subprocess
from pathlib import Path

pairs = [
    ("arch_prompts.py", "/opt/CRM_Streamlit/src/services/commercial_routing_v3/arch_prompts.py"),
    ("arch_shadow_runner.py", "/opt/CRM_Streamlit/src/services/commercial_routing_v3/arch_shadow_runner.py"),
    ("registry_extract_mapper.py", "/opt/CRM_Streamlit/src/services/commercial_routing_v3/registry_extract_mapper.py"),
    ("_arch_decomposition_experiment.py", "/opt/CRM_Streamlit/scripts/_arch_decomposition_experiment.py"),
    (
        "test_v3_architecture_decomposition_contract.py",
        "/opt/CRM_Streamlit/tests/test_v3_architecture_decomposition_contract.py",
    ),
]


def main() -> None:
    for src_name, dst in pairs:
        src = Path("/tmp") / src_name
        data = src.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        Path(dst).write_bytes(data)
        print("installed", dst)

    r = subprocess.run(
        [
            "/opt/CRM_Streamlit/.venv313/bin/python",
            "-m",
            "pytest",
            "tests/test_v3_architecture_decomposition_contract.py",
            "-q",
            "--tb=line",
        ],
        cwd="/opt/CRM_Streamlit",
        env={"PYTHONPATH": "/opt/CRM_Streamlit:/opt/pythonProject89", "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    print(r.stdout)
    print(r.stderr[-400:] if r.stderr else "")
    print("pytest_rc", r.returncode)
    if r.returncode != 0:
        raise SystemExit(r.returncode)

    for name in (
        "MODEL_CATEGORY_CALIBRATION_CORPUS.json",
        "MODEL_CATEGORY_HOLDOUT_CORPUS.json",
    ):
        p = Path("/tmp") / name
        print(name, "OK" if p.exists() else "MISSING")

    uid = subprocess.check_output(["id", "-u"], text=True).strip()
    gid = subprocess.check_output(["id", "-g"], text=True).strip()
    wrap = Path("/tmp/arch_decomp_wrap.sh")
    wrap.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "cd /opt/CRM_Streamlit\n"
        "export PYTHONPATH=/opt/CRM_Streamlit:/opt/pythonProject89\n"
        "export ARCH_CORPUS=both\n"
        "export ARCH_ARCHS=A,B\n"
        "export ARCH_OUT=/tmp/arch_decomposition_summary.json\n"
        "exec /opt/CRM_Streamlit/.venv313/bin/python -u "
        "scripts/_arch_decomposition_experiment.py "
        ">>/tmp/arch_decomposition.log 2>&1\n",
        encoding="utf-8",
    )
    wrap.chmod(0o755)
    Path("/tmp/arch_decomposition.log").write_text("", encoding="utf-8")
    Path("/tmp/arch_decomposition_summary.json").unlink(missing_ok=True)
    cmd = [
        "sudo",
        "-n",
        "systemd-run",
        f"--uid={uid}",
        f"--gid={gid}",
        "--slice=crm-background-compute.slice",
        "--unit=crm-arch-decomposition.service",
        "--working-directory=/opt/CRM_Streamlit",
        "--property=CPUWeight=50",
        "--property=Nice=5",
        "--collect",
        "/bin/bash",
        str(wrap),
    ]
    print(subprocess.check_output(cmd, text=True))
    print(subprocess.check_output(["systemctl", "is-active", "crm-arch-decomposition.service"], text=True))
    print(
        subprocess.check_output(
            ["systemctl", "show", "crm-arch-decomposition.service", "-p", "ControlGroup"],
            text=True,
        )
    )


if __name__ == "__main__":
    main()
