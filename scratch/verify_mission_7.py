import asyncio
import os
import sys
import subprocess
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import settings
from database.models import Product
from services.wholesale_client import wholesale_client
from aiogram.types import Message, Chat, User as TGUser

# Mock list of products returned from DB
mock_db_products = [
    Product(api_product_id="steam_gift_card_10", title="Steam Gift Card $10", platform="Steam", base_usd_price=Decimal("10.00"), is_available=True),
    Product(api_product_id="out_of_stock_product", title="Out Of Stock Game Key", platform="Origin", base_usd_price=Decimal("15.00"), is_available=True),
    Product(api_product_id="gta_v", title="Grand Theft Auto V", platform="Rockstar", base_usd_price=Decimal("20.00"), is_available=True)
]

async def test_catalog_sync():
    print("\n--- Testing Catalog Sync Service ---")

    # 1. Start Mock B2B Server
    print("Starting Mock B2B Server on Port 8081...")
    b2b_proc = subprocess.Popen(
        ["venv/bin/uvicorn", "scratch.mock_b2b_server:app", "--host", "127.0.0.1", "--port", "8081"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    time.sleep(2)  # Wait for uvicorn to bind

    # Update client settings to point to mock B2B server
    wholesale_client.base_url = "http://127.0.0.1:8081"
    wholesale_client.api_token = "test_token"

    # Mock the SQLAlchemy session and execute to decouple from live PostgreSQL
    mock_session = AsyncMock()
    mock_session.begin = MagicMock()
    mock_session.begin.return_value.__aenter__ = AsyncMock()
    mock_session.begin.return_value.__aexit__ = AsyncMock()
    
    mock_result = MagicMock()
    mock_result.rowcount = 1
    mock_session.execute.return_value = mock_result

    # Mock context manager for async_session
    mock_session_maker = MagicMock()
    mock_session_maker.return_value = mock_session
    mock_session.__aenter__.return_value = mock_session

    try:
        from services.catalog_sync import _sync_catalog

        # Patch async_session used in catalog_sync
        with patch("services.catalog_sync.async_session", mock_session_maker):
            # Run Sync 1
            print("Running catalog sync against mock server...")
            synced_count = await _sync_catalog()
            print(f"Synced count: {synced_count}")
            assert synced_count == 3
            
            # Verify database calls were made
            assert mock_session.execute.call_count >= 3
            print("✓ Catalog sync executes inserts and updates successfully!")

            # 2. Test stale product flagging logic
            print("Testing stale product flagging logic...")
            mock_session.execute.reset_mock()
            
            # Mock the fetch_catalog call to return only 2 products (omitting gta_v)
            original_fetch = wholesale_client.fetch_catalog
            wholesale_client.fetch_catalog = AsyncMock(return_value=[
                {"productId": "steam_gift_card_10", "name": "Steam Gift Card $10", "platform": "Steam", "price": 10.00},
                {"productId": "out_of_stock_product", "name": "Out Of Stock Game Key", "platform": "Origin", "price": 15.00}
            ])

            synced_count2 = await _sync_catalog()
            print(f"Second sync synced count: {synced_count2}")
            assert synced_count2 == 2
            
            # Verify update query was executed (for stale products NOT IN list)
            # 2 inserts + 1 update = 3 execute calls
            assert mock_session.execute.call_count == 3
            print("✓ Stale product flagging update executed successfully!")
            
            # Restore original fetch
            wholesale_client.fetch_catalog = original_fetch

    finally:
        b2b_proc.terminate()
        b2b_proc.wait()

async def test_throttling_middleware():
    print("\n--- Testing Throttling Middleware ---")
    from bot.middlewares.throttling import ThrottlingMiddleware
    from services.redis_manager import redis_manager
    
    middleware = ThrottlingMiddleware()
    mock_handler = AsyncMock(return_value="handler_called")
    
    # 1. Test Fail-Open (Redis not connected)
    print("Testing middleware fail-open when Redis is disconnected...")
    original_client = redis_manager.client
    redis_manager.client = None
    
    # Create a real Message object using minimal parameters
    chat = Chat(id=123, type="private")
    user = TGUser(id=99999, is_bot=False, first_name="Test")
    mock_event = Message(message_id=1, date=datetime.now(), chat=chat, from_user=user, text="test")
    
    res = await middleware(mock_handler, mock_event, {})
    assert res == "handler_called"
    print("✓ Passed fail-open check")

    # 2. Test Rate Limiting behavior with a Mock Redis client
    print("Testing rate limiter sliding window checks using Mock Redis...")
    mock_redis = AsyncMock()
    redis_manager.client = mock_redis
    
    # Scenario: User makes 3 rapid requests within the same window
    # 1st request: incr returns 1
    mock_redis.incr.return_value = 1
    res1 = await middleware(mock_handler, mock_event, {})
    assert res1 == "handler_called"
    mock_redis.expire.assert_called_with("user_spam_lock:99999", 1)
    
    # 2nd request: incr returns 2
    mock_redis.incr.return_value = 2
    res2 = await middleware(mock_handler, mock_event, {})
    assert res2 == "handler_called"
    
    # 3rd request: incr returns 3 (breaches limit of 2)
    mock_redis.incr.return_value = 3
    
    # Use object.__setattr__ to set the mock method on the frozen Message instance
    mock_answer = AsyncMock()
    object.__setattr__(mock_event, "answer", mock_answer)
    
    res3 = await middleware(mock_handler, mock_event, {})
    assert res3 is None  # Swallowed!
    mock_answer.assert_called_with("⚠️ Too fast! Please wait a moment before searching again.")
    
    # Restore original redis client
    redis_manager.client = original_client
    print("✓ Throttling middleware limits requests successfully at >2 queries/second!")

async def main():
    try:
        await test_catalog_sync()
    except Exception as e:
        print(f"✗ Catalog sync test failed: {e}")
        import traceback; traceback.print_exc()
        
    try:
        await test_throttling_middleware()
    except Exception as e:
        print(f"✗ Throttling middleware test failed: {e}")
        import traceback; traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
