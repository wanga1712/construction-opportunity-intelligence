"""Category management and taxonomy lifecycle for discovered products."""

from __future__ import annotations

from collections import defaultdict
import difflib
import threading
from typing import Any, Dict, List, Optional, Set
import uuid

from src.product_discovery.dto import (
    DiscoveryStatus,
    ProductCategoryDTO,
    ProductObservationDTO,
)
from src.product_discovery.product_normalizer import normalize_product_name


class ProductCategoryManager:
    """Manages autonomous discovery, alias resolution, and lifecycle of hierarchical product categories."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._categories: Dict[str, ProductCategoryDTO] = {}
        self._observations: List[ProductObservationDTO] = []
        self._alias_to_id: Dict[str, str] = {}
        self._category_procurement_ids: Dict[str, Set[int]] = defaultdict(set)

    def _find_matching_category_id(self, name: str) -> Optional[str]:
        """Finds matching category id by exact name, alias, or high fuzzy similarity."""
        key = name.strip().lower()
        if key in self._alias_to_id:
            return self._alias_to_id[key]

        for cat_id, cat in self._categories.items():
            if cat.canonical_name.strip().lower() == key:
                return cat_id
            for alias in cat.aliases:
                if alias.strip().lower() == key:
                    return cat_id

        canonical_names = [c.canonical_name for c in self._categories.values() if c.status != DiscoveryStatus.MERGED]
        matches = difflib.get_close_matches(name, canonical_names, n=1, cutoff=0.88)
        if matches:
            matched_name = matches[0]
            for cat_id, cat in self._categories.items():
                if cat.canonical_name == matched_name:
                    return cat_id

        return None

    def register_observation(self, obs: ProductObservationDTO) -> ProductCategoryDTO:
        """Registers a discovered product observation and links or creates its hierarchical product category."""
        with self._lock:
            canonical = obs.normalized_name or normalize_product_name(obs.raw_text)
            domain = obs.domain or "CONSTRUCTION"
            matched_id = self._find_matching_category_id(canonical)

            if matched_id and matched_id in self._categories:
                cat = self._categories[matched_id]
                cat.observation_count += 1
                cat.total_discovered_amount += obs.total_amount
                self._category_procurement_ids[cat.category_id].add(obs.procurement_id)
                cat.procurement_count = len(self._category_procurement_ids[cat.category_id])

                if obs.raw_text and obs.raw_text not in cat.aliases and obs.raw_text != cat.canonical_name:
                    cat.aliases.append(obs.raw_text)
                    self._alias_to_id[obs.raw_text.strip().lower()] = cat.category_id
            else:
                cat_id = f"cat_{str(uuid.uuid4())[:8]}"
                cat = ProductCategoryDTO(
                    category_id=cat_id,
                    canonical_name=canonical,
                    domain=domain,
                    hierarchy_level="SUBCATEGORY" if obs.subcategory_name else "CATEGORY",
                    status=DiscoveryStatus.AUTO_DISCOVERED,
                    observation_count=1,
                    procurement_count=1,
                    total_discovered_amount=obs.total_amount,
                    aliases=[obs.raw_text] if obs.raw_text and obs.raw_text != canonical else [],
                )
                self._categories[cat_id] = cat
                self._alias_to_id[canonical.strip().lower()] = cat_id
                if obs.raw_text:
                    self._alias_to_id[obs.raw_text.strip().lower()] = cat_id
                self._category_procurement_ids[cat_id].add(obs.procurement_id)

            obs.normalized_name = canonical
            obs.category_name = cat.canonical_name
            self._observations.append(obs)
            return cat

    def confirm_category(
        self,
        category_id: str,
        actor: str = "model",
    ) -> Optional[ProductCategoryDTO]:
        """Confirms a product category status with strict authority boundaries."""
        with self._lock:
            cat = self._categories.get(category_id)
            if not cat:
                return None

            is_human_expert = actor in ("expert", "superuser", "admin", "lead_expert") or actor.startswith("expert")

            if is_human_expert:
                cat.status = DiscoveryStatus.EXPERT_CONFIRMED
            else:
                if cat.status == DiscoveryStatus.AUTO_DISCOVERED:
                    cat.status = DiscoveryStatus.MODEL_CONFIRMED

            return cat

    def reject_category(self, category_id: str, actor: str = "expert") -> Optional[ProductCategoryDTO]:
        """Rejects a category."""
        with self._lock:
            cat = self._categories.get(category_id)
            if not cat:
                return None
            cat.status = DiscoveryStatus.REJECTED
            return cat

    def merge_categories(
        self,
        source_id: str,
        target_id: str,
        actor: str = "expert",
    ) -> Optional[ProductCategoryDTO]:
        """Merges a source category into target category and updates aliases."""
        with self._lock:
            source = self._categories.get(source_id)
            target = self._categories.get(target_id)
            if not source or not target:
                return None

            target.observation_count += source.observation_count
            target.total_discovered_amount += source.total_discovered_amount
            pids = self._category_procurement_ids[source_id]
            self._category_procurement_ids[target_id].update(pids)
            target.procurement_count = len(self._category_procurement_ids[target_id])

            for alias in [source.canonical_name] + source.aliases:
                if alias not in target.aliases and alias != target.canonical_name:
                    target.aliases.append(alias)
                    self._alias_to_id[alias.strip().lower()] = target.category_id

            source.status = DiscoveryStatus.MERGED
            return target

    def get_all_categories(self, status: Optional[DiscoveryStatus] = None) -> List[ProductCategoryDTO]:
        """Returns categories, optionally filtered by lifecycle status."""
        with self._lock:
            cats = list(self._categories.values())
            if status is not None:
                cats = [c for c in cats if c.status == status]
            return sorted(cats, key=lambda c: (c.observation_count, c.total_discovered_amount), reverse=True)

    def get_all_observations(self, procurement_id: Optional[int] = None) -> List[ProductObservationDTO]:
        """Returns observations, optionally filtered by procurement_id."""
        with self._lock:
            obs = list(self._observations)
            if procurement_id is not None:
                obs = [o for o in obs if o.procurement_id == procurement_id]
            return obs

