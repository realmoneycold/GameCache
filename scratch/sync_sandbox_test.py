import asyncio
import sys
import os
from decimal import Decimal

# Add root folder to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.db import async_session
from database.models import Product
from services.catalog_sync import _sync_catalog
from sqlalchemy import select

async def main():
    print("[Integration Test] Starting Catalog Sync Task against official Sandbox endpoint...")
    try:
        # Run sync task
        synced_count = await _sync_catalog()
        print(f"[Integration Test] Catalog sync completed. Synced count: {synced_count}")
        
        if synced_count > 0:
            print("\n[Integration Test] Verifying database records inside local Postgres...")
            async with async_session() as session:
                result = await session.execute(select(Product).limit(5))
                products = result.scalars().all()
                print(f"[Integration Test] Total products retrieved (first 5 max): {len(products)}")
                for p in products:
                    print(f"  - ID: {p.id} | API ID: {p.api_product_id} | Title: {p.title} | Platform: {p.platform} | Price: ${p.base_usd_price}")
        else:
            print("[Integration Test] Warning: No products were synced.")
            
    except Exception as e:
        print(f"[Integration Test] Error during integration test run: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
