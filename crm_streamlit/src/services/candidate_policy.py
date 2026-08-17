"""CandidatePolicy: Вычисление медали и приоритета на основе профиля закупки."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("candidate_policy")

class CandidatePolicy:
    @staticmethod
    def calculate_opportunity(
        route_profile: str,
        lifecycle: str,
        item: Dict[str, Any],
        egrz_info: Optional[Dict[str, Any]],
        cohort_median: float,
        opp: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Вычисляет балл и медаль для конкретной category opportunity по каскадным правилам.
        """
        # V3 integration guard: reuse precomputed track-scoped medal/score if present.
        v3_level = opp.get("candidate_level") or opp.get("candidate_medal")
        if v3_level in ("GOLD", "SILVER", "BRONZE", "WOOD"):
            v3_score = opp.get("candidate_score")
            if v3_score is None:
                v3_score = opp.get("commercial_priority_score") or opp.get("research_value_score") or 0.0
            try:
                v3_score_f = float(v3_score)
            except Exception:
                v3_score_f = 0.0
            return {
                "candidate_score": round(v3_score_f, 2),
                "candidate_level": v3_level,
                "details": {"v3_track_specific": True},
            }
        opp_conf = float(opp.get("confidence") or 1.0)
        price = float(item.get("price") or item.get("initial_price") or 0.0)
        median = cohort_median if cohort_median > 0 else 5000000.0
        ratio = price / median
        
        details: Dict[str, Any] = {}
        ai_res_mock = {"confidence": opp_conf}
        
        if lifecycle == "OPEN":
            score = CandidatePolicy._evaluate_open(
                route_profile, item, ai_res_mock, price, ratio, opp_conf, egrz_info, details
            )
        else:
            score = CandidatePolicy._evaluate_awarded(
                route_profile, item, ai_res_mock, price, ratio, opp_conf, details
            )
            
        opp_status = opp.get("opportunity_status", "POSSIBLE")
        expected_vol = opp.get("expected_volume", "UNKNOWN")
        
        # Каскадный алгоритм
        if opp_status in ("ABSENT", "UNLIKELY", "OUT_OF_PROFILE"):
            level = None
        else:
            if score >= 80.0:
                level = "GOLD"
            elif score >= 50.0:
                level = "SILVER"
            elif score >= 20.0:
                level = "BRONZE"
            else:
                level = "WOOD"
                
            # Если POSSIBLE и LOW volume -> GOLD запрещен
            if opp_status == "POSSIBLE" and expected_vol == "LOW" and level == "GOLD":
                level = "SILVER"
                
        return {
            "candidate_score": round(score, 2),
            "candidate_level": level,
            "details": details
        }

    @staticmethod
    def calculate(
        route_profile: str,
        lifecycle: str,
        item: Dict[str, Any],
        ai_result: Dict[str, Any],
        cohort_median: float,
        egrz_info: Optional[Dict[str, Any]] = None,
        business_scope_status: str = "IN_PROFILE"
    ) -> Dict[str, Any]:
        """
        Вычисляет баллы и медали по всем категориям и находит лучшую.
        """
        policy_name = f"{lifecycle}_{route_profile}"
        
        if business_scope_status == "OUT_OF_PROFILE":
            return {
                "candidate_level": None,
                "candidate_score": None,
                "best_opportunity_category": None,
                "category_opportunities": [],
                "policy_applied": policy_name,
                "details": {
                    "business_scope_status": "OUT_OF_PROFILE"
                }
            }
            
        # V3 discovery integration: if caller provided category_opportunities
        # explicitly as an empty list, do NOT inject legacy `UNKNOWN` categories.
        opps = ai_result.get("category_opportunities", None)
        if opps is None:
            # Обратная совместимость
            proposed_cats = ai_result.get("proposed_categories") or ["UNKNOWN"]
            opps = []
            for cat in proposed_cats:
                opps.append({
                    "category_code": cat,
                    "subcategory_code": None,
                    "opportunity_status": "CONFIRMED_SOURCE" if ai_result.get("confidence", 1.0) >= 0.7 else "POSSIBLE",
                    "expected_role": "PRIMARY_SUPPLY",
                    "commercial_entry_point": "DIRECT_SUPPLY",
                    "expected_volume": "HIGH" if float(item.get("initial_price") or 0.0) >= cohort_median else "MEDIUM",
                    "confidence": float(ai_result.get("confidence") or 1.0),
                    "priority": 1.0,
                    "research_action": "PRIORITY_DOCS"
                })
                
        processed_opps = []
        best_level = None
        best_score = None
        best_cat = None
        best_details = {}
        
        level_ranks = {"GOLD": 4, "SILVER": 3, "BRONZE": 2, "WOOD": 1, None: 0}
        
        for opp in opps:
            res = CandidatePolicy.calculate_opportunity(
                route_profile, lifecycle, item, egrz_info, cohort_median, opp
            )
            opp_copy = dict(opp)
            opp_copy["candidate_score"] = res["candidate_score"]
            opp_copy["candidate_level"] = res["candidate_level"]
            opp_copy["candidate_reasons"] = ai_result.get("reasons") or "AI calculated"
            processed_opps.append(opp_copy)
            
            curr_level = res["candidate_level"]
            curr_score = res["candidate_score"]
            
            if level_ranks.get(curr_level, 0) > level_ranks.get(best_level, 0):
                best_level = curr_level
                best_score = curr_score
                best_cat = opp.get("category_code")
                best_details = res["details"]
            elif level_ranks.get(curr_level, 0) == level_ranks.get(best_level, 0) and best_level is not None:
                if curr_score > (best_score or 0.0):
                    best_score = curr_score
                    best_cat = opp.get("category_code")
                    best_details = res["details"]
                    
            if not best_details:
                best_details = res["details"]
                
        return {
            "candidate_level": best_level,
            "candidate_score": best_score,
            "best_opportunity_category": best_cat,
            "category_opportunities": processed_opps,
            "policy_applied": policy_name,
            "details": best_details
        }
        
    @staticmethod
    def _evaluate_open(
        profile: str,
        item: Dict[str, Any],
        ai_res: Dict[str, Any],
        price: float,
        ratio: float,
        confidence: float,
        egrz_info: Optional[Dict[str, Any]],
        details: Dict[str, Any]
    ) -> float:
        score = 30.0  # базовый балл
        
        # Входные даты и расчет окна подачи (submission window)
        sub_end_raw = item.get("end_date") or item.get("submission_end")
        remaining_days = None
        if sub_end_raw:
            try:
                if isinstance(sub_end_raw, str):
                    dt = datetime.fromisoformat(sub_end_raw.replace("Z", "+00:00"))
                else:
                    dt = datetime.combine(sub_end_raw, datetime.min.time()).replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                remaining_days = (dt - now).days
            except Exception as e:
                logger.debug(f"Failed to parse submission end date: {e}")
                
        # Начисление баллов по цене относительно медианы когорты
        price_points = min(ratio * 20.0, 40.0)
        score += price_points
        details["price_points"] = round(price_points, 2)
        
        # Окно подачи
        if remaining_days is not None:
            details["remaining_days"] = remaining_days
            if remaining_days < 0:
                score -= 30.0  # Просроченная подача
                details["submission_window_notes"] = "expired"
            elif remaining_days <= 2:
                score -= 15.0  # Слишком мало времени
                details["submission_window_notes"] = "urgent_penalty"
            elif 5 <= remaining_days <= 15:
                score += 10.0  # Идеальное окно
                details["submission_window_notes"] = "optimal_window_bonus"
        else:
            details["remaining_days"] = "unknown"
            
        # Специфические логики профилей
        if profile in ("CONSTRUCTION_BUILDING", "CONSTRUCTION_INFRASTRUCTURE"):
            details["sub_policy"] = "OPEN_CONSTRUCTION"
            # Учитываем экспертизу ЕГРЗ
            if egrz_info and egrz_info.get("status") == "YES":
                score += 20.0
                details["egrz_bonus"] = 20.0
            else:
                details["egrz_bonus"] = 0.0
                
        elif profile == "DESIGN_ENGINEERING":
            details["sub_policy"] = "OPEN_DESIGN"
            title = (item.get("title") or "").lower()
            desc = (item.get("description") or "").lower()
            # Проверяем стадии проектирования
            design_keywords = ["стадия п", "проектная документация", "стадия р", "рабочая документация", "изыскания"]
            has_keywords = any(kw in title or kw in desc for kw in design_keywords)
            if has_keywords:
                score += 20.0
                details["design_stage_bonus"] = 20.0
            else:
                details["design_stage_bonus"] = 0.0
                
        elif profile == "DIRECT_SUPPLY":
            details["sub_policy"] = "OPEN_DIRECT_SUPPLY"
            # Вычисляем estimated_addressable_value как preliminary
            est_value = price * 0.4  # предположим, что 40% цены идет на адресные товары
            details["estimated_addressable_value"] = est_value
            details["estimated_addressable_value_status"] = "preliminary"
            
            # Учитываем уверенность в категории
            cat_conf = confidence
            score += cat_conf * 15.0
            details["category_confidence_bonus"] = round(cat_conf * 15.0, 2)
            
        elif profile == "COMPUTERS_IT":
            details["sub_policy"] = "OPEN_COMPUTERS"
            # Компьютеры не требуют экспертизы ЕГРЗ, оцениваем чисто по ИТ-весам
            cat_conf = confidence
            score += cat_conf * 25.0
            details["it_confidence_bonus"] = round(cat_conf * 25.0, 2)
            
        # Ограничиваем и умножаем на уверенность ИИ
        score = min(max(score, 0.0), 100.0) * confidence
        return score

    @staticmethod
    def _evaluate_awarded(
        profile: str,
        item: Dict[str, Any],
        ai_res: Dict[str, Any],
        price: float,
        ratio: float,
        confidence: float,
        details: Dict[str, Any]
    ) -> float:
        score = 40.0  # базовый балл для AWARDED
        
        # Начисление баллов по цене относительно медианы когорты
        price_points = min(ratio * 15.0, 30.0)
        score += price_points
        details["price_points"] = round(price_points, 2)
        
        # Временные окна выполнения работ (delivery/execution windows)
        start_date = item.get("delivery_start_date") or item.get("execution_start_at")
        end_date = item.get("delivery_end_date") or item.get("execution_end_at")
        
        if start_date and end_date:
            try:
                if isinstance(start_date, str):
                    d1 = datetime.fromisoformat(start_date.split("T")[0])
                else:
                    d1 = datetime.combine(start_date, datetime.min.time())
                    
                if isinstance(end_date, str):
                    d2 = datetime.fromisoformat(end_date.split("T")[0])
                else:
                    d2 = datetime.combine(end_date, datetime.min.time())
                    
                duration_days = (d2 - d1).days
                details["execution_duration_days"] = duration_days
                if duration_days > 180:
                    score += 15.0  # Длинные стабильные контракты лучше
                    details["duration_bonus"] = 15.0
                elif duration_days < 30:
                    score -= 10.0  # Слишком короткие сроки
                    details["duration_bonus"] = -10.0
            except Exception as e:
                logger.debug(f"Failed to parse awarded window dates: {e}")
                
        # Наличие победителя и подрядчика
        winner_name = item.get("winner_name") or item.get("contractor_name")
        if winner_name:
            score += 10.0
            details["has_winner_bonus"] = 10.0
            
        if profile in ("CONSTRUCTION_BUILDING", "CONSTRUCTION_INFRASTRUCTURE"):
            details["sub_policy"] = "AWARDED_CONSTRUCTION"
        elif profile == "COMPUTERS_IT":
            details["sub_policy"] = "AWARDED_COMPUTERS"
        else:
            details["sub_policy"] = f"AWARDED_{profile}"
            
        score = min(max(score, 0.0), 100.0) * confidence
        return score
