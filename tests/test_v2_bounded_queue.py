"""Comprehensive Unit and Integration tests for Stage 1 V2 Bounded Queue Priority & WFQ Scheduler.

Verification matrix:
1. MODEL_CONTROLS_ORDER = YES
2. MODEL_CONTROLS_ADMISSION = NO (strict admission isolation)
3. WOOD_EXPLORATION_ENABLED = YES (WOOD can be claimed, capacity > 0)
4. AGING_ENABLED = YES (starvation prevention via progressive boost)
5. STARVATION_POSSIBLE = NO
6. POST_RESEARCH_FEATURE_COUNT = 0
7. NO_CLASS_GETS_100_PERCENT_CAPACITY = YES
8. NO_CLASS_GETS_ZERO_PERCENT_CAPACITY = YES
9. Feature flag toggle (MODEL_QUEUE_PRIORITY_ENABLED)
10. Unscored fallback & deterministic tie-breaking
11. Extreme values & malformed OKPD robustness
12. Multi-step 500-item queue simulation
"""

from datetime import datetime, timedelta, timezone
import pytest

from src.learning.okpd_prior.combined_v2 import (
    FEATURE_NAMES_V2,
    ResearchPriorityModelV2,
)
from src.learning.okpd_prior.model import (
    BAND_BRONZE,
    BAND_GOLD,
    BAND_SILVER,
    BAND_WOOD,
    assign_priority_band,
)
from src.services.research_queue_priority import (
    BAND_UNSCORED,
    QueueTaskItem,
    Stage1QueuePriorityCalculator,
    WFQBoundedScheduler,
)



@pytest.fixture
def fitted_model() -> ResearchPriorityModelV2:
    """Provides a fitted V2 model on synthetic representative examples."""
    titles = [
        "Поставка светодиодных светильников и опор освещения",
        "Поставка вычислительной техники и серверов",
        "Капитальный ремонт кровли и фасада здания",
        "Поставка медицинских расходных материалов и лекарств",
        "Оказание услуг по уборке помещений (клининг)",
        "Поставка мебели офисной и стульев",
    ]
    okpds = [
        "27.40.39.110",
        "26.20.14.000",
        "43.99.90.000",
        "21.20.10.110",
        "81.21.10.000",
        "31.01.11.000",
    ]
    prices = [1500000.0, 3200000.0, 5000000.0, 450000.0, 200000.0, 350000.0]
    y = [1, 1, 1, 0, 0, 0]

    model = ResearchPriorityModelV2(random_state=42)
    model.fit(titles, okpds, prices, y)
    return model


def test_post_research_feature_count_is_zero():
    """Verify strictly 0 post-research features are used in V2 priority model."""
    forbidden_terms = [
        "match",
        "evidence",
        "finding",
        "page",
        "sheet",
        "confirmed",
        "rejected",
        "v4_status",
        "validation",
        "result",
        "observation",
    ]
    for feature in FEATURE_NAMES_V2:
        for term in forbidden_terms:
            assert term not in feature.lower(), f"Forbidden post-research feature detected: {feature}"
    assert len(FEATURE_NAMES_V2) == 12


def test_admission_isolation_never_drops_tasks():
    """MODEL_CONTROLS_ADMISSION = NO: All items remain queue eligible regardless of score/band."""
    calculator = Stage1QueuePriorityCalculator()
    scheduler = WFQBoundedScheduler(calculator=calculator, model_queue_priority_enabled=True)

    items = [
        QueueTaskItem(
            id=1,
            procurement_id=101,
            auction_name="Закупка клининга",
            okpd_code="81.21.10",
            initial_price=10000.0,
            created_at=datetime.now(timezone.utc),
        ),
        QueueTaskItem(
            id=2,
            procurement_id=102,
            auction_name="Поставка опор освещения",
            okpd_code="27.40.39",
            initial_price=2000000.0,
            created_at=datetime.now(timezone.utc),
        ),
    ]

    for it in items:
        assert it.queue_eligible is True

    ordered = scheduler.order_tasks(items)
    assert len(ordered) == 2
    assert {it.id for it in ordered} == {1, 2}


def test_model_controls_order_when_enabled(fitted_model):
    """MODEL_CONTROLS_ORDER = YES: Prior model reorders tasks by predicted priority."""
    now = datetime.now(timezone.utc)
    # Item 1: Low prior (cleaning), created earlier
    item1 = QueueTaskItem(
        id=1,
        procurement_id=101,
        auction_name="Оказание услуг по уборке помещений (клининг)",
        okpd_code="81.21.10.000",
        initial_price=50000.0,
        created_at=now - timedelta(minutes=10),
    )
    # Item 2: High prior (lighting fixtures), created later
    item2 = QueueTaskItem(
        id=2,
        procurement_id=102,
        auction_name="Поставка светодиодных светильников и опор освещения",
        okpd_code="27.40.39.110",
        initial_price=2500000.0,
        created_at=now,
    )

    calculator = Stage1QueuePriorityCalculator(model=fitted_model, aging_enabled=False)
    scheduler = WFQBoundedScheduler(calculator=calculator, model_queue_priority_enabled=True)

    ordered = scheduler.order_tasks([item1, item2], now=now)
    assert ordered[0].id == 2  # Item 2 is GOLD / higher priority
    assert ordered[1].id == 1  # Item 1 is WOOD / lower priority


def test_feature_flag_fallback():
    """When MODEL_QUEUE_PRIORITY_ENABLED is False, orders by FIFO / raw priority."""
    now = datetime.now(timezone.utc)
    t1 = now - timedelta(hours=5)
    t2 = now - timedelta(hours=2)

    item1 = QueueTaskItem(
        id=1,
        procurement_id=101,
        auction_name="Low priority old item",
        okpd_code="81.21.10",
        initial_price=10000.0,
        created_at=t1,
        raw_priority_score=50,
    )
    item2 = QueueTaskItem(
        id=2,
        procurement_id=102,
        auction_name="High priority new item",
        okpd_code="27.40.39",
        initial_price=2000000.0,
        created_at=t2,
        raw_priority_score=90,
    )

    scheduler_disabled = WFQBoundedScheduler(model_queue_priority_enabled=False)
    ordered_disabled = scheduler_disabled.order_tasks([item1, item2])
    assert ordered_disabled[0].id == 2
    assert ordered_disabled[1].id == 1


def test_aging_prevents_starvation_of_wood_items(fitted_model):
    """AGING_ENABLED = YES: Old WOOD item eventually gains enough boost to exceed newer item."""
    now = datetime.now(timezone.utc)
    old_wood_item = QueueTaskItem(
        id=1,
        procurement_id=101,
        auction_name="Поставка канцелярских товаров",
        okpd_code="17.23.13",
        initial_price=50000.0,
        created_at=now - timedelta(hours=60),
    )
    new_bronze_item = QueueTaskItem(
        id=2,
        procurement_id=102,
        auction_name="Текущий ремонт забора",
        okpd_code="43.29.19",
        initial_price=150000.0,
        created_at=now - timedelta(hours=1),
    )

    calculator = Stage1QueuePriorityCalculator(
        model=fitted_model,
        aging_enabled=True,
        aging_rate_per_hour=0.5,
        max_aging_boost=40.0,
    )
    scheduler = WFQBoundedScheduler(calculator=calculator, model_queue_priority_enabled=True)

    ordered = scheduler.order_tasks([new_bronze_item, old_wood_item], now=now)
    assert old_wood_item.effective_priority > new_bronze_item.effective_priority
    assert ordered[0].id == old_wood_item.id


def test_wood_exploration_capacity_and_simulation():
    """Verify WOOD items are claimed in simulation and no starvation occurs."""
    now = datetime.now(timezone.utc)
    items = []
    for i in range(5):
        items.append(
            QueueTaskItem(
                id=i + 1,
                procurement_id=100 + i,
                auction_name="Поставка светодиодных светильников и опор",
                okpd_code="27.40.39.110",
                initial_price=2000000.0,
                created_at=now - timedelta(hours=i),
                priority_band=BAND_GOLD,
                effective_priority=80,
            )
        )
    for i in range(5):
        items.append(
            QueueTaskItem(
                id=i + 6,
                procurement_id=200 + i,
                auction_name="Капитальный ремонт фасада",
                okpd_code="43.99.90.000",
                initial_price=5000000.0,
                created_at=now - timedelta(hours=i),
                priority_band=BAND_SILVER,
                effective_priority=60,
            )
        )
    for i in range(5):
        items.append(
            QueueTaskItem(
                id=i + 11,
                procurement_id=250 + i,
                auction_name="Поставка мебели офисной",
                okpd_code="31.01.11.000",
                initial_price=300000.0,
                created_at=now - timedelta(hours=i),
                priority_band=BAND_BRONZE,
                effective_priority=40,
            )
        )
    for i in range(5):
        items.append(
            QueueTaskItem(
                id=i + 16,
                procurement_id=300 + i,
                auction_name="Услуги прачечной и химчистки",
                okpd_code="96.01.19.000",
                initial_price=50000.0,
                created_at=now - timedelta(hours=20 + i * 2),
                priority_band=BAND_WOOD,
                effective_priority=20,
            )
        )

    calculator = Stage1QueuePriorityCalculator(model=None, aging_enabled=True)
    scheduler = WFQBoundedScheduler(calculator=calculator, model_queue_priority_enabled=True)

    sim_res = scheduler.simulate_schedule(items, batch_size=5, steps=4, start_time=now, step_hours=4.0)
    assert sim_res["total_claimed"] == 20
    assert sim_res["remaining_unclaimed"] == 0
    assert sim_res["band_claim_counts"][BAND_WOOD] > 0
    assert sim_res["starvation_occurred"] is False




def test_unscored_fallback_handling():
    """Unscored items (no model) receive default score and remain fully queue eligible."""
    now = datetime.now(timezone.utc)
    calculator = Stage1QueuePriorityCalculator(model=None)
    scheduler = WFQBoundedScheduler(calculator=calculator, model_queue_priority_enabled=True)

    item = QueueTaskItem(
        id=99,
        procurement_id=999,
        auction_name="Неизвестная закупка",
        okpd_code="",
        initial_price=0.0,
        created_at=now,
    )

    calculator.calculate_item_priority(item, now=now)
    assert item.priority_band == BAND_UNSCORED
    assert item.predicted_probability is None
    assert item.effective_priority == 20
    assert item.queue_eligible is True

    ordered = scheduler.order_tasks([item], now=now)
    assert len(ordered) == 1
    assert ordered[0].id == 99


def test_deterministic_tie_breaking():
    """Identical items break ties deterministically by created_at and id."""
    now = datetime.now(timezone.utc)
    t1 = now - timedelta(hours=2)
    t2 = now - timedelta(hours=1)

    item1 = QueueTaskItem(
        id=10,
        procurement_id=1,
        auction_name="Закупка А",
        okpd_code="27.40.39",
        initial_price=1000.0,
        created_at=t1,
    )
    item2 = QueueTaskItem(
        id=5,
        procurement_id=2,
        auction_name="Закупка Б",
        okpd_code="27.40.39",
        initial_price=1000.0,
        created_at=t1,
    )
    item3 = QueueTaskItem(
        id=1,
        procurement_id=3,
        auction_name="Закупка В",
        okpd_code="27.40.39",
        initial_price=1000.0,
        created_at=t2,
    )

    calculator = Stage1QueuePriorityCalculator(model=None, aging_enabled=False)
    scheduler = WFQBoundedScheduler(calculator=calculator, model_queue_priority_enabled=True)

    ordered = scheduler.order_tasks([item3, item1, item2], now=now)
    assert [x.id for x in ordered] == [5, 10, 1]


def test_aging_cap_enforcement():
    """Aging boost never exceeds max_aging_boost."""
    now = datetime.now(timezone.utc)
    old_item = QueueTaskItem(
        id=1,
        procurement_id=1,
        auction_name="Очень старая закупка",
        okpd_code="81.21.10",
        initial_price=1000.0,
        created_at=now - timedelta(days=365),  # 1 year old
    )
    calculator = Stage1QueuePriorityCalculator(
        model=None,
        aging_enabled=True,
        aging_rate_per_hour=1.0,
        max_aging_boost=35.0,
    )
    calculated = calculator.calculate_item_priority(old_item, now=now)
    assert calculated.effective_priority == 20 + 35  # base 20 + max 35 = 55


def test_empty_and_single_item_queue():
    """Queue scheduler gracefully handles empty and single-element collections."""
    scheduler = WFQBoundedScheduler(model_queue_priority_enabled=True)
    assert scheduler.order_tasks([]) == []
    assert scheduler.select_next_batch([], batch_size=10) == []

    single = QueueTaskItem(
        id=1,
        procurement_id=10,
        auction_name="Одиночная закупка",
        okpd_code="27.40.39",
        initial_price=100000.0,
        created_at=datetime.now(timezone.utc),
    )
    res = scheduler.select_next_batch([single], batch_size=5)
    assert len(res) == 1
    assert res[0].id == 1


def test_malformed_inputs_robustness(fitted_model):
    """Model and calculator handle None / invalid OKPD and price inputs gracefully."""
    now = datetime.now(timezone.utc)
    item = QueueTaskItem(
        id=1,
        procurement_id=1,
        auction_name="",
        okpd_code="NOT_AN_OKPD_CODE!@#$",
        initial_price=-500.0,
        created_at=now,
    )
    calculator = Stage1QueuePriorityCalculator(model=fitted_model)
    res = calculator.calculate_item_priority(item, now=now)
    assert res.priority_band in (BAND_GOLD, BAND_SILVER, BAND_BRONZE, BAND_WOOD, BAND_UNSCORED)
    assert 0 <= res.effective_priority <= 100


def test_large_queue_500_items_simulation():
    """Simulation on 500 items verifies full coverage and no starvation across 25 batches."""
    now = datetime.now(timezone.utc)
    items = []
    bands_list = [BAND_GOLD, BAND_SILVER, BAND_BRONZE, BAND_WOOD]
    base_scores = {BAND_GOLD: 80, BAND_SILVER: 60, BAND_BRONZE: 40, BAND_WOOD: 20}
    for i in range(500):
        band = bands_list[i % 4]
        items.append(
            QueueTaskItem(
                id=i + 1,
                procurement_id=1000 + i,
                auction_name=f"Закупка {i}",
                okpd_code="27.40.39.110",
                initial_price=1000000.0,
                created_at=now - timedelta(hours=i * 0.5),
                priority_band=band,
                effective_priority=base_scores[band],
            )
        )

    calculator = Stage1QueuePriorityCalculator(model=None, aging_enabled=True)
    scheduler = WFQBoundedScheduler(calculator=calculator, model_queue_priority_enabled=True)

    sim_res = scheduler.simulate_schedule(items, batch_size=20, steps=25, start_time=now, step_hours=2.0)
    assert sim_res["total_claimed"] == 500
    assert sim_res["remaining_unclaimed"] == 0
    assert sim_res["band_claim_counts"][BAND_WOOD] > 0
    assert sim_res["band_claim_counts"][BAND_GOLD] > 0
    assert sim_res["starvation_occurred"] is False


