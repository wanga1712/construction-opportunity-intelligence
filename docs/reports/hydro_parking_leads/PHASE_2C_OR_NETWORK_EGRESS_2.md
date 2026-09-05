# Phase 2C-OR — Network egress through existing Amnezia

Status: `BLOCKED` with `AMNEZIA_SSH_AUTHORITY_REQUIRED`.

## Read-only topology audit

```text
S13_AWG_IP=10.8.0.13/32
AWG_ALLOWED_IPS=10.8.0.0/24
AWG_CONFIG_CHANGED=NO
DEFAULT_ROUTE_CHANGED=NO
OPENROUTER_DIRECT=HTTP_403
OPENROUTER_VIA_AWG0=TIMEOUT
```

The Amnezia peer endpoint was read from the existing awg0 runtime metadata,
but no existing approved SSH alias resolves to that endpoint. Existing aliases
were inspected read-only; `mint-vpn` resolves to S13 itself. No username,
identity or endpoint was guessed, and no SSH connection to an unapproved host
was attempted.

```text
SSH_AUTHORITY_PROVEN=NO
AMNEZIA_SERVER_OPENROUTER_REACHABLE=NOT_VERIFIED
LOCAL_SOCKS_TUNNEL=NOT_CREATED
PROXY_PUBLIC_ACCESS=NO
OPENROUTER_PROVIDER_USES_SOCKS=NO
SMOKE_3=NOT_STARTED
SMOKE_10=NOT_STARTED
```

No `AllowedIPs`, default route, firewall/NAT rule, PostgreSQL route, CRM
service or Analytics V3 file was changed. No persistent tunnel service was
created. The next safe gate requires an approved SSH alias/identity for the
existing Amnezia server; then server egress can be tested before a temporary
localhost-only SOCKS forward is created.
