# DYNAMIC_CATEGORY_EXTENSION_TEST.md

WIP: Phase 9 SHADOW paint extension (in-memory only; production taxonomy unchanged).

## Setup

Shadow registry = production ACTIVE (8) + ephemeral:

```json
{"category_code":"paint","category_name":"Краски и лакокрасочные материалы"}
```

No paint regex, OKPD prior, prompt example, or Python mapper added.

| Guard | Value |
|--|--|
| PAINT_TEST_PROMPT_SOURCE_CHANGED | NO |
| PAINT_TEST_PYTHON_HINT_ADDED | NO |
| PAINT_TEST_OKPD_RULE_ADDED | NO |

## Results

| Case | Title | paint selected? | subject |
|--|--|--|--|
| A DIRECT | Поставка краски акриловой фасадной | YES | GOODS / paint product |
| B OBJECT | Ремонт фасада здания | NO (abstained) | OBJECT_WORKS / facade repair |
| C PC | Поставка персональных компьютеров | NO | computers |
| D ROAD | Ремонт автомобильной дороги | NO | road repair |

```
PAINT_DIRECT_DISCOVERED=YES
PAINT_OBJECT_RESEARCH_CANDIDATE=NO
PAINT_IRRELEVANT_FP_COUNT=0
```

Object facade did not force `paint` (allowed “may”); irrelevant cases clean.
