"""LLM-based pre-classification of contracts by keyword-category relevance."""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Dict, Optional

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:7b"

# Threshold below which a category is skipped (env: CLASSIFIER_SKIP_THRESHOLD)
DEFAULT_SKIP_THRESHOLD = 2.0

CATEGORY_DESCRIPTIONS: Dict[str, str] = {
    "flooring": "Напольные покрытия: линолеум, ламинат, керамогранит, ПВХ-плитка, спортивные и наливные полы",
    "lighting": "Светотехника: светильники, прожекторы, LED, уличное освещение, лампы, опоры",
    "waterproofing": "Гидроизоляция зданий: изоляция кровли, подвала, фундамента, стен, рулонная гидроизоляция",
    "waterproofing_concrete_repair": "Гидроизоляция и ремонт бетона: пенетрирующие составы, инъекции, гидрофобизатор, ремонтные смеси",
    "drainage_water_management": "Водоотвод и дренаж: лотки, дождеприёмники, дренажные трубы, коллекторы, ливнёвка",
    "cable_support_systems": "Кабеленесущие системы: кабель-каналы, металлические лотки, короба, перфолента",
    "composite_structures": "Композитные конструкции: стеклопластик FRP, решётки, настилы, поручни, профили из стеклопластика",
    "concrete_materials": "Материалы для бетона: добавки в бетон, пластификаторы, ускорители твердения, микрокремнезём",
    "bridge_road_infrastructure": "Мостовая и дорожная инфраструктура: мосты, дорожное полотно, асфальт, путепроводы",
    "external_utility_networks": "Наружные инженерные сети: наружные трубопроводы, тепловые сети, водоснабжение и канализация вне зданий",
    "structural_reinforcement": "Усиление и ремонт конструкций: усиление несущих конструкций, обоймы, торкрет-бетон, анкеры",
}

_PROMPT_TEMPLATE = (
    'Тендер: "{name}"{okpd}\n\n'
    "Оцени вероятность (0-10) присутствия в документах тендера МАТЕРИАЛОВ из каждой категории.\n"
    "0 = точно нет, 10 = почти наверняка. Категории:\n"
    "{cats}\n\n"
    "Ответь ТОЛЬКО JSON без пояснений:\n"
    '{{{keys}}}'
)


def _build_prompt(auction_name: str, okpd: Optional[str]) -> str:
    okpd_line = f'\nОКПД2: {okpd}' if okpd else ''
    cats = "\n".join(f'- {code}: {desc}' for code, desc in CATEGORY_DESCRIPTIONS.items())
    keys = ", ".join(f'"{k}": <0-10>' for k in CATEGORY_DESCRIPTIONS)
    return _PROMPT_TEMPLATE.format(name=auction_name, okpd=okpd_line, cats=cats, keys=keys)


def _call_ollama(prompt: str, timeout: int = 45) -> Optional[Dict[str, float]]:
    body = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0, "num_predict": 300},
    }).encode()
    req = urllib.request.Request(
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        raw = data.get("response", "")
        m = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
        if not m:
            return None
        parsed = json.loads(m.group())
        return {str(k): float(v) for k, v in parsed.items() if isinstance(v, (int, float))}
    except Exception:
        return None


class ContractClassifier:
    """Pre-classifies a contract's category relevance using local Ollama LLM."""

    _CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS contract_category_scores (
            contract_number VARCHAR(100) NOT NULL,
            category_code   VARCHAR(100) NOT NULL,
            score           SMALLINT     NOT NULL DEFAULT 5,
            classified_by   VARCHAR(50)  DEFAULT 'qwen2.5:7b',
            classified_at   TIMESTAMPTZ  DEFAULT NOW(),
            PRIMARY KEY (contract_number, category_code)
        )
    """

    def __init__(self, db, logger) -> None:
        self.db = db
        self.logger = logger
        self._table_ready = False

    def _ensure_table(self) -> None:
        if self._table_ready:
            return
        try:
            self.db.execute_query("tender_monitor", self._CREATE_TABLE_SQL)
            self._table_ready = True
        except Exception as exc:
            self.logger.error(f"ContractClassifier: table create failed: {exc}")

    def _get_cached(self, contract_number: str) -> Optional[Dict[str, float]]:
        try:
            rows = self.db.execute_query(
                "tender_monitor",
                "SELECT category_code, score FROM contract_category_scores WHERE contract_number = %s",
                (contract_number,),
                fetch=True,
            ) or []
            if rows:
                return {row[0]: float(row[1]) for row in rows}
        except Exception as exc:
            self.logger.error(f"ContractClassifier cache read error: {exc}")
        return None

    def _save_scores(self, contract_number: str, scores: Dict[str, float]) -> None:
        self._ensure_table()
        for code, score in scores.items():
            try:
                self.db.execute_query(
                    "tender_monitor",
                    """
                    INSERT INTO contract_category_scores
                        (contract_number, category_code, score)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (contract_number, category_code)
                    DO UPDATE SET score = EXCLUDED.score, classified_at = NOW()
                    """,
                    (contract_number, code, int(round(score))),
                )
            except Exception as exc:
                self.logger.error(f"ContractClassifier save error: {exc}")

    def _get_contract_info(
        self, contract_number: str, table_source: str
    ) -> tuple[str, Optional[str]]:
        """Returns (auction_name, okpd_code). okpd_code may be None."""
        sql = f"""
            SELECT r.auction_name, COALESCE(o.sub_code, o.main_code) AS okpd_code
            FROM {table_source} r
            LEFT JOIN collection_codes_okpd o ON o.id = r.okpd_id
            WHERE r.contract_number = %s
            LIMIT 1
        """
        try:
            rows = self.db.execute_query(
                "tender_monitor", sql, (contract_number,), fetch=True
            ) or []
            if rows:
                return rows[0][0] or "", rows[0][1]
        except Exception as exc:
            self.logger.warning(
                f"ContractClassifier: cannot fetch contract info for {contract_number} "
                f"from {table_source}: {exc}"
            )
        return "", None

    def classify(
        self,
        contract_number: str,
        table_source: str,
    ) -> Dict[str, float]:
        """
        Returns {category_code: score_0_to_10}.
        Empty dict = Ollama unavailable; caller should use all keywords.
        """
        cached = self._get_cached(contract_number)
        if cached:
            return cached

        auction_name, okpd = self._get_contract_info(contract_number, table_source)
        if not auction_name:
            return {}

        prompt = _build_prompt(auction_name, okpd)
        scores = _call_ollama(prompt)
        if not scores:
            self.logger.warning(
                f"ContractClassifier: Ollama unavailable/failed for {contract_number}, "
                "all keywords will be used"
            )
            return {}

        # Fill missing categories with neutral score 5
        for code in CATEGORY_DESCRIPTIONS:
            if code not in scores:
                scores[code] = 5.0

        self._save_scores(contract_number, scores)

        skipped = [c for c, s in scores.items() if s < DEFAULT_SKIP_THRESHOLD]
        self.logger.info(
            f"ContractClassifier [{contract_number}] \"{auction_name[:60]}\": "
            + ", ".join(f"{k}={v:.0f}" for k, v in sorted(scores.items(), key=lambda x: -x[1]))
            + (f" | skip={skipped}" if skipped else "")
        )
        return scores
