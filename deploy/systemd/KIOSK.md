# S13 graphical kiosk (monitor dashboard)

Components:
- `s13-web-dashboard.service` - local HTTP dashboard on 127.0.0.1:8899
  (`deploy/scripts/s13_web_dashboard.py`): JSON metrics + self-contained HTML/JS
  with colored bars, gauges, CPU/GPU charts, service tiles, queue bars, top CPU.
- `s13-kiosk.service` - X server (`:0 vt7`) + Firefox `--kiosk` on the physical
  monitor, auto-start at boot, `Restart=always`.
- `Xwrapper.config.reference` - required `/etc/X11/Xwrapper.config`
  (`allowed_users=anybody`, `needs_root_rights=yes`) so X can be started from a
  systemd service (not a console login).
- Text console dashboard `s13-console-dashboard.service` is DISABLED while the
  graphical kiosk is active (both would fight over the VT).

Deploy:
```sh
cp deploy/systemd/s13-web-dashboard.service deploy/systemd/s13-kiosk.service /etc/systemd/system/
cp deploy/scripts/s13_web_dashboard.py /usr/local/bin/ && chmod 755 /usr/local/bin/s13_web_dashboard.py
cp deploy/systemd/Xwrapper.config.reference /etc/X11/Xwrapper.config
systemctl disable --now s13-console-dashboard.service
systemctl daemon-reload && systemctl enable --now s13-web-dashboard.service s13-kiosk.service
```
