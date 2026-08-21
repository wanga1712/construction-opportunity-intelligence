# REGISTRY_PROMPT_SCALE_AUDIT.md

WIP: Phase 9 — full registry visibility (no retrieval/filtering).

ACTIVE commercial categories in SHADOW payload: **8**

| Scale | prompt_chars_est | prompt_tokens_est (~4 chars/tok) |
|--|--|--|
| 1x CURRENT | 11043 | 2760 |
| 2x | 16426 | 4106 |
| 5x | 32575 | 8143 |
| 10x | 59490 | 14872 |

```
CURRENT_REGISTRY_COUNT=8
CURRENT_PROMPT_TOKENS_EST=2760
5X_PROMPT_TOKENS_EST=8143
10X_PROMPT_TOKENS_EST=14872
SUBCATEGORY_ARCHITECTURE=DEFERRED_AFTER_CATEGORY_SELECTION
```

Choice: keep all ACTIVE categories in first pass; omit subcategory lists until category selected (prompt-size evidence favors A over embedding all subs).
