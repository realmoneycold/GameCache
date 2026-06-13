"""
Dynamic Pricing Utility
Calculates the final local UZS price using live exchange rates and a configurable profit margin.
Formula: Final UZS Price = (Base Price × Live Exchange Rate) × (1 + Profit Margin)
"""
from decimal import Decimal
from services import currency_sync
from config import settings


async def calculate_local_price(base_foreign_price: Decimal, currency: str = "USD") -> Decimal:
    """
    Converts a foreign-currency base price to UZS using the live exchange rate
    and applies the configured profit margin surcharge.

    Args:
        base_foreign_price: The product's base price in foreign currency (e.g. USD).
        currency: The source currency code (default: "USD").

    Returns:
        The final price in UZS, rounded to the nearest whole unit.
        (Tiyin suffixes are added later by the reservation engine.)
    """
    rate = await currency_sync.get_rate(currency)
    margin = Decimal(str(settings.PROFIT_MARGIN_PERCENT)) / Decimal("100")
    final_price = base_foreign_price * rate * (Decimal("1") + margin)
    # Round to nearest whole UZS — tiyins are added by the tiyin collision solver
    return final_price.quantize(Decimal("1"))
