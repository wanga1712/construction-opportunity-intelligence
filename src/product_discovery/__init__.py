"""Document Product Discovery Subsystem.

Discovers commercial products and materials from tender documents/estimates,
establishes co-product graphs, and expands product category taxonomy autonomously.
"""

from src.product_discovery.dto import (
    CategoryRelationDTO,
    DiscoveryStatus,
    ProductCategoryDTO,
    ProductObservationDTO,
    RowType,
    UnitCategory,
)

__all__ = [
    "RowType",
    "DiscoveryStatus",
    "UnitCategory",
    "ProductObservationDTO",
    "ProductCategoryDTO",
    "CategoryRelationDTO",
]
