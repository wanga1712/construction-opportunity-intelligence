#!/usr/bin/env python3
"""Launch background-slice CPU burn + ollama load, then probe."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

ROOT = Path("/opt/CRM_Streamlit")


def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, check=False, capture_output=True, text=True)
    return (p.stdout or "") + (p.stderr or "")


def main() -> None:
    print(
        run(
            [
                "sudo",
                "-n",
                "systemd-run",
                "--uid=" + str(subprocess.check_output(["id", "-u"], text=True).strip()),
                "--gid=" + str(subprocess.check_output(["id", "-g"], text=True).strip()),
                "--slice=crm-background-compute.slice",
                "--unit=crm-ui-cpu-burn.service",
                "--collect",
                "--working-directory=/opt/CRM_Streamlit",
                "/opt/CRM_Streamlit/.venv313/bin/python",
                str(ROOT / "scripts" / "_ui_bg_cpu_burn.py"),
                "300",
            ]
        )
    )
    ollama_loop = ROOT / "scripts" / "_ui_ollama_loop.py"
    ollama_loop.write_text(
        "import json, urllib.request, time\n"
        "body=json.dumps({'model':'qwen2.5:7b','prompt':'write 40 words',"
        "'stream':False,'options':{'num_predict':48}}).encode()\n"
        "for i in range(80):\n"
        "    try:\n"
        "        urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:11434/api/generate', data=body, method='POST'), timeout=120).read()\n"
        "    except Exception:\n"
        "        time.sleep(1)\n",
        encoding="utf-8",
    )
    print(
        run(
            [
                "sudo",
                "-n",
                "systemd-run",
                "--uid=" + str(subprocess.check_output(["id", "-u"], text=True).strip()),
                "--gid=" + str(subprocess.check_output(["id", "-g"], text=True).strip()),
                "--slice=crm-background-compute.slice",
                "--unit=crm-ui-ollama-load.service",
                "--collect",
                "--working-directory=/opt/CRM_Streamlit",
                "/opt/CRM_Streamlit/.venv313/bin/python",
                str(ollama_loop),
            ]
        )
    )
    time.sleep(5)
    print("LOAD=" + Path("/proc/loadavg").read_text().strip())
    print(run(["ps", "-eo", "pid,psr,ni,%cpu,comm", "--sort=-%cpu"]).splitlines()[:15])
    print("OLLAMA_PS=" + run(["curl", "-s", "http://127.0.0.1:11434/api/ps"]))
    print("PROBES=" + run(["/opt/CRM_Streamlit/.venv313/bin/python", str(ROOT / "scripts" / "_ui_contend_probes.py")]))
    print("BURN_CG=" + run(["systemctl", "show", "crm-ui-cpu-burn.service", "-p", "ControlGroup", "-p", "CPUAffinity"]))
    print("OLLAMA_CG=" + run(["systemctl", "show", "ollama", "-p", "ControlGroup"]))


if __name__ == "__main__":
    main()
