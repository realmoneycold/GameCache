"""
Currency Synchronizer Service
Fetches live USD/EUR → UZS exchange rates from the Central Bank of Uzbekistan (CBU) API,
caches them in Redis, and provides a fallback to config baselines on API failure.
Sync loop runs every 12 hours.
"""
import asyncio
import httpx
from decimal import Decimal, InvalidOperation
from typing import Optional
from config import settings
from services.redis_manager import redis_manager

CBU_API_URL = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/"
SYNC_INTERVAL_SECONDS = 43200  # 12 hours

# Redis key prefix for exchange rates
RATE_KEY_PREFIX = "exchange_rate"

# Currencies we care about
TARGET_CURRENCIES = {"USD", "EUR"}


async def _fetch_and_cache_rates() -> bool:
    """
    Fetches live rates from the CBU API and caches them in Redis.
    Returns True on success, False on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(CBU_API_URL)
            response.raise_for_status()
            data = response.json()

        rates_found = 0
        for entry in data:
            ccy = entry.get("Ccy", "")
            if ccy in TARGET_CURRENCIES:
                try:
                    rate = Decimal(entry["Rate"])
                    nominal = Decimal(entry.get("Nominal", "1"))
                    # Per-unit rate = Rate / Nominal
                    per_unit_rate = rate / nominal
                    key = f"{RATE_KEY_PREFIX}:{ccy}"
                    await redis_manager.client.set(key, str(per_unit_rate))
                    rates_found += 1
                    print(f"[CurrencySync] Cached {ccy} rate: {per_unit_rate}")
                except (InvalidOperation, KeyError, ZeroDivisionError) as e:
                    print(f"[CurrencySync] ⚠ Failed to parse rate for {ccy}: {e}")

        if rates_found == len(TARGET_CURRENCIES):
            print(f"[CurrencySync] ✓ Successfully synced {rates_found} exchange rates from CBU.")
            return True
        else:
            print(f"[CurrencySync] ⚠ Partial sync: only {rates_found}/{len(TARGET_CURRENCIES)} rates found.")
            return rates_found > 0

    except httpx.HTTPError as e:
        print(f"[CurrencySync] ⚠ CBU API HTTP error: {e}. Falling back to config baselines.")
        return False
    except Exception as e:
        print(f"[CurrencySync] ⚠ Unexpected error during sync: {e}. Falling back to config baselines.")
        return False


async def get_rate(currency: str = "USD") -> Decimal:
    """
    Returns the live exchange rate for the given currency from Redis.
    Falls back to the config baseline if Redis has no cached value.
    """
    currency = currency.upper()

    # Try Redis first
    if redis_manager.client:
        try:
            cached = await redis_manager.client.get(f"{RATE_KEY_PREFIX}:{currency}")
            if cached:
                return Decimal(cached)
        except Exception as e:
            print(f"[CurrencySync] ⚠ Redis read error for {currency}: {e}")

    # Fallback to config baselines
    if currency == "USD":
        return Decimal(str(settings.USD_TO_UZS_RATE))
    elif currency == "EUR":
        return Decimal(str(settings.EUR_TO_UZS_RATE))
    else:
        # Unknown currency — use USD fallback as a safe default
        print(f"[CurrencySync] ⚠ Unknown currency '{currency}', using USD fallback.")
        return Decimal(str(settings.USD_TO_UZS_RATE))


async def start_sync_loop():
    """
    Background loop that fetches exchange rates immediately on startup,
    then re-syncs every 12 hours.
    """
    print("[CurrencySync] Starting exchange rate sync loop (interval: 12h)...")
    while True:
        await _fetch_and_cache_rates()
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)
