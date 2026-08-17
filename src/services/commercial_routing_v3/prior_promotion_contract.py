"""OKPD prior semantics: commercial product vs contextual research.

Promotion contract:
  CONTEXTUAL_RESEARCH_PRIOR is NOT a commercial category result.
  Example: cable OKPD 27.32 → search docs for tray/ladder/support terms;
  only later explicit evidence may promote cable_support_systems to a
  real commercial opportunity.

Direct product non-expansion:
  cable ≠ cable tray / ladder / support system
  lighting cable ≠ lighting fixture
"""
from __future__ import annotations

CONTEXT_TO_COMMERCIAL_PROMOTION_CONTRACT = """
A contextual prior is a search hypothesis only.
It must NOT be emitted as a commercial category assertion by priors alone.
Promotion requires later explicit document/title evidence for the sellable product.
Search lexicon (cable→supports example): кабельный лоток, лоток, лестничный лоток,
кабельная лестница, кабельрост, кабельная эстакада, кабельные конструкции,
консоль, стойка, подвес, кронштейн, система крепления кабеля.
"""

DIRECT_PRODUCT_NON_EXPANSION_RULE = """
For DIRECT_GOODS_PURCHASE the explicit product title + exact OKPD + official
goods description define what is purchased. Do not expand into co-used products.
"""
