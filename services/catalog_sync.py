"""
Wholesale Catalog Synchronization Engine
Fetches the full product catalog from the B2B distributor API,
performs bulk upserts into PostgreSQL, and flags stale products.
Runs on startup and refreshes every 24 hours.
"""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from sqlalchemy import update
from database.db import async_session, engine
from database.models import Product
from services.wholesale_client import wholesale_client

SYNC_INTERVAL_SECONDS = 86400  # 24 hours


async def _sync_catalog() -> int:
    """
    Fetches the full catalog from the B2B supplier and upserts into PostgreSQL.
    Returns the number of products synced, or -1 on failure.
    """
    try:
        is_sqlite = "sqlite" in str(engine.url)
        if is_sqlite:
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert
            insert_func = sqlite_insert
        else:
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            insert_func = pg_insert

        print("[CatalogSync] Fetching catalog from wholesale supplier...")
        raw_products = await wholesale_client.fetch_catalog()
        print(f"[CatalogSync] Received {len(raw_products)} products from supplier.")

        if not raw_products:
            print("[CatalogSync] ⚠ Empty catalog received. Skipping sync.")
            return 0

        # Track all supplier product IDs for stale-flagging later
        supplier_product_ids: list[str] = []

        async with async_session() as session:
            async with session.begin():
                for item in raw_products:
                    try:
                        api_product_id = str(item["productId"])
                        title = str(item.get("name", "Unknown Product"))
                        platform = str(item.get("platform", "Unknown"))
                        price = Decimal(str(item.get("price", "0.00")))

                        supplier_product_ids.append(api_product_id)

                        # Bulk upsert: INSERT ... ON CONFLICT (api_product_id) DO UPDATE
                        stmt = (
                            insert_func(Product)
                            .values(
                                api_product_id=api_product_id,
                                title=title,
                                platform=platform,
                                base_usd_price=price,
                                is_available=True,
                                updated_at=datetime.now(timezone.utc),
                            )
                            .on_conflict_do_update(
                                index_elements=[Product.api_product_id],
                                set_={
                                    "title": title,
                                    "platform": platform,
                                    "base_usd_price": price,
                                    "is_available": True,
                                    "updated_at": datetime.now(timezone.utc),
                                },
                            )
                        )
                        await session.execute(stmt)

                    except (KeyError, InvalidOperation, TypeError) as e:
                        print(f"[CatalogSync] ⚠ Skipping malformed product: {item} — {e}")
                        continue

                # Flag stale products that are no longer in the supplier's catalog
                if supplier_product_ids:
                    stale_stmt = (
                        update(Product)
                        .where(Product.api_product_id.notin_(supplier_product_ids))
                        .where(Product.is_available == True)
                        .values(is_available=False, updated_at=datetime.now(timezone.utc))
                    )
                    result = await session.execute(stale_stmt)
                    stale_count = result.rowcount
                    if stale_count > 0:
                        print(f"[CatalogSync] Flagged {stale_count} stale product(s) as unavailable.")

            await session.commit()

        synced = len(supplier_product_ids)
        print(f"[CatalogSync] ✓ Successfully synced {synced} products.")
        return synced

    except Exception as e:
        print(f"[CatalogSync] ✗ Catalog sync failed: {e}")
        return -1


async def start_sync_loop():
    """
    Background loop that syncs the catalog immediately on startup,
    then re-syncs every 24 hours.
    """
    print("[CatalogSync] Starting catalog sync loop (interval: 24h)...")
    while True:
        await _sync_catalog()
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)
