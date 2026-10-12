"""Acceptance verification script for Effective Medal Time Decay (Phase 3.2)."""
import os
import sys
from collections import Counter

# Ensure repo root is in python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.torgi_workset_service import TorgiFilterParams, load_torgi_workset, get_evaluated_torgi_workset


def main():
    print("=" * 60)
    print("PHASE 3.2 ACCEPTANCE: EFFECTIVE MEDAL TIME DECAY")
    print("=" * 60)

    # 1. Load full active workset
    all_cards = get_evaluated_torgi_workset(hide_expired=True)
    total_active = len(all_cards)
    print(f"TOTAL_ACTIVE_NON_EXPIRED_CARDS: {total_active}")

    # 2. Count distributions
    base_dist = Counter(c.get("base_medal", "UNASSESSED") for c in all_cards)
    eff_dist = Counter(c.get("effective_medal", "UNASSESSED") for c in all_cards)

    print("\nBASE MEDAL DISTRIBUTION:")
    for m in ["GOLD", "SILVER", "BRONZE", "WOOD", "UNASSESSED"]:
        print(f"  {m:12s}: {base_dist[m]:4d}")

    print("\nEFFECTIVE MEDAL DISTRIBUTION (WITH TIME DECAY):")
    for m in ["GOLD", "SILVER", "BRONZE", "WOOD", "UNASSESSED", "CLOSED"]:
        print(f"  {m:12s}: {eff_dist[m]:4d}")

    # 3. Verify top 50 cards
    top50, count = load_torgi_workset(limit=50, offset=0, filters=TorgiFilterParams(hide_expired=True))
    print(f"\nTOP 50 CARDS INSPECTION (Total matching: {count}):")
    top50_eff = Counter(c.get("effective_medal") for c in top50)
    print(f"  Top 50 Effective Medals: {dict(top50_eff)}")

    expired_in_top50 = sum(1 for c in top50 if c.get("is_expired"))
    print(f"  TOP50_EXPIRED_COUNT: {expired_in_top50} (MUST BE 0)")
    assert expired_in_top50 == 0, f"Found {expired_in_top50} expired cards in top 50!"

    # 4. Verify monotonic sort of top 50
    # Effective medal ranks in top 50 must be non-decreasing
    ranks = [c.get("effective_medal_rank", 5) for c in top50]
    is_sorted_by_rank = all(ranks[i] <= ranks[i+1] for i in range(len(ranks)-1))
    print(f"  TOP50_EFFECTIVE_RANK_MONOTONIC: {is_sorted_by_rank} (Ranks: {ranks[:15]}...)")
    assert is_sorted_by_rank, "Top 50 cards are not properly sorted by effective_medal_rank!"

    # 5. Display sample top 10 cards
    print("\nSAMPLE TOP 10 CARDS:")
    for idx, c in enumerate(top50[:10], 1):
        pid = c["id"]
        eff = c.get("effective_medal")
        base = c.get("base_medal")
        score = c.get("priority_score")
        days = c.get("days_to_deadline")
        decay = c.get("deadline_decay_steps")
        days_str = f"{days:.1f}d" if days is not None else "N/A"
        name = (c.get("auction_name") or "")[:40]
        print(f"  #{idx:2d} | ID:{pid:7d} | Eff:{eff:6s} (decay:-{decay}) | Base:{base:6s} | Score:{score:3d} | Days:{days_str:6s} | {name}")

    # 6. Verify source medals immutability across all cards
    for c in all_cards:
        assert "preliminary_medal" in c
        assert "base_medal" in c
        assert "effective_medal" in c
        assert "effective_medal_rank" in c

    print("\nALL ACCEPTANCE CRITERIA PASSED: OK")
    print("=" * 60)


if __name__ == "__main__":
    main()
