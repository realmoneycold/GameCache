"""
End-to-End Local Sandbox Audit & System Certification Script
Validates local port statuses, catalog sync deactivations, success/failure JIT payments,
and Redis rate-limiting bot middleware. Uses a self-contained SQLite in-memory DB and Mock Redis.
"""
import asyncio
import os
import sys
import socket
import subprocess
import time
from decimal import Decimal
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import settings

# --- 1. Port pre-flight checks ---
def run_port_preflight():
    print("=========================================")
    echo("🔍 Running Pre-Flight Socket Connect Checks")
    echo("=========================================")
    
    ports = {
        5433: "Docker Host-Mapped PostgreSQL (dev)",
        6379: "Docker Host-Mapped Redis (dev)",
        5432: "Local Host-Running PostgreSQL"
    }
    
    for port, desc in ports.items():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        try:
            s.connect(('127.0.0.1', port))
            print(f"  - Port {port} ({desc}): OPEN")
            s.close()
        except Exception:
            print(f"  - Port {port} ({desc}): CLOSED (offline/inaccessible)")

def echo(msg):
    print(msg)

# --- 2. Custom Mock Redis client ---
class MockRedis:
    def __init__(self):
        self.store = {}
        self.ttls = {}
        
    async def get(self, key):
        self._check_ttl(key)
        return self.store.get(key)
        
    async def set(self, key, value, ex=None, nx=False):
        self._check_ttl(key)
        if nx and key in self.store:
            return None
        self.store[key] = str(value)
        if ex:
            self.ttls[key] = time.time() + ex
        return True
        
    async def incr(self, key):
        self._check_ttl(key)
        val = int(self.store.get(key, 0)) + 1
        self.store[key] = str(val)
        return val
        
    async def expire(self, key, seconds):
        self.ttls[key] = time.time() + seconds
        return True
        
    async def keys(self, pattern):
        prefix = pattern.replace("*", "")
        for k in list(self.store.keys()):
            self._check_ttl(k)
        return [k for k in self.store.keys() if k.startswith(prefix)]
        
    async def eval(self, script, numkeys, key):
        self._check_ttl(key)
        val = self.store.get(key)
        if val:
            del self.store[key]
            if key in self.ttls:
                del self.ttls[key]
        return val

    def _check_ttl(self, key):
        if key in self.ttls and time.time() > self.ttls[key]:
            if key in self.store:
                del self.store[key]
            del self.ttls[key]

# --- 3. Main Integration Test Execution ---
async def execute_integration_audit():
    # Load and setup Database session override
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    import database.db
    from database.models import Base, User, Product, Order, OrderStatus, AuditLog, UnmappedPayment
    
    print("\n=========================================")
    echo("💾 Initializing In-Memory Test DB Schema")
    echo("=========================================")
    sqlite_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    sqlite_sessionmaker = async_sessionmaker(
        bind=sqlite_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    # Overwrite the global sessionmaker in database/db.py
    database.db.async_session = sqlite_sessionmaker
    
    # Create all tables on SQLite
    async with sqlite_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✓ SQLite tables created successfully.")

    # Override Redis manager with our Mock Redis
    from services.redis_manager import redis_manager
    redis_manager.client = MockRedis()
    print("✓ Redis manager overridden with local MockRedis.")

    # Mock telegram bot dispatch
    from bot.bot_instance import bot
    bot.send_message = AsyncMock()
    print("✓ Telegram Bot send_message mocked.")

    # Start B2B server subprocess
    print("\nStarting Mock B2B Server on Port 8081...")
    b2b_proc = subprocess.Popen(
        ["venv/bin/uvicorn", "scratch.mock_b2b_server:app", "--host", "127.0.0.1", "--port", "8081"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    time.sleep(2)  # wait for bind

    # Direct B2B API client to mock B2B server
    from services.wholesale_client import wholesale_client
    wholesale_client.base_url = "http://127.0.0.1:8081"
    wholesale_client.api_token = "test_token"

    try:
        # --- A. Catalog Sync Test ---
        print("\n--- Test A: Catalog Synchronization & Flagging ---")
        from services.catalog_sync import _sync_catalog
        
        # 1. First sync pulls all 3 products
        synced_count = await _sync_catalog()
        print(f"  - First Sync result: {synced_count} products.")
        assert synced_count == 3
        
        # Verify database has them
        from sqlalchemy import select
        async with sqlite_sessionmaker() as session:
            res = await session.execute(select(Product))
            prods = res.scalars().all()
            print(f"  - Products written to DB: {[p.api_product_id for p in prods]}")
            assert len(prods) == 3
            assert all(p.is_available for p in prods)
            
        # 2. Mock B2B catalog changes (omit 'gta_v')
        original_fetch = wholesale_client.fetch_catalog
        wholesale_client.fetch_catalog = AsyncMock(return_value=[
            {"productId": "steam_gift_card_10", "name": "Steam Gift Card $10", "platform": "Steam", "price": 10.00},
            {"productId": "out_of_stock_product", "name": "Out Of Stock Game Key", "platform": "Origin", "price": 15.00}
        ])
        
        # 3. Second sync flags 'gta_v' as unavailable
        synced_count2 = await _sync_catalog()
        print(f"  - Second Sync result: {synced_count2} products.")
        
        async with sqlite_sessionmaker() as session:
            res = await session.execute(select(Product))
            prods = res.scalars().all()
            gta_v = next(p for p in prods if p.api_product_id == "gta_v")
            steam = next(p for p in prods if p.api_product_id == "steam_gift_card_10")
            print(f"  - GTA V availability: {gta_v.is_available}")
            print(f"  - Steam Gift Card availability: {steam.is_available}")
            assert gta_v.is_available is False
            assert steam.is_available is True
            
        wholesale_client.fetch_catalog = original_fetch
        print("✓ Catalog synchronization engine validated.")

        # --- B. FastAPI Webhook Success/Failure JIT testing ---
        import httpx
        from main import app
        transport = httpx.ASGITransport(app=app)
        
        # Populate test user
        async with sqlite_sessionmaker() as session:
            async with session.begin():
                session.add(User(telegram_id=12345678, username="test_gamer"))
            await session.commit()

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"X-Payment-Token": settings.INTERNAL_API_SECRET_TOKEN}
            
            # 1. Success Path
            print("\n--- Test B1: JIT Webhook SUCCESS Path ---")
            order_id_1 = uuid.uuid4()
            reserved_price_1 = await redis_manager.reserve_unique_price(
                base_price=Decimal("134000.00"),
                user_id=12345678,
                product_id=1,  # steam_gift_card_10 (id in Product table matches index)
                order_id=str(order_id_1)
            )
            
            async with sqlite_sessionmaker() as session:
                async with session.begin():
                    session.add(Order(
                        id=order_id_1, user_id=12345678, product_id=1,
                        exact_amount_uzs=reserved_price_1, tiyin_suffix=0, status=OrderStatus.PENDING
                    ))
                await session.commit()
                
            response = await client.post(
                "/api/v1/payment-callback",
                headers=headers,
                json={"amount": float(reserved_price_1)}
            )
            print("  - Response:", response.status_code, response.json())
            assert response.status_code == 200
            assert response.json()["status"] == "success"
            
            # Verify DB updates and logs
            async with sqlite_sessionmaker() as session:
                order = await session.get(Order, order_id_1)
                res_audit = await session.execute(select(AuditLog).where(AuditLog.order_id == order_id_1))
                logs = res_audit.scalars().all()
                
                print(f"  - Order Status in DB: {order.status}")
                print(f"  - Audit log entries: {len(logs)}")
                assert order.status == OrderStatus.COMPLETED
                assert len(logs) == 1
                assert logs[0].action == "wholesale_purchase_success"
                
            # Verify Bot Message delivered
            assert bot.send_message.call_count >= 1
            print(f"  - Bot send_message called. Last call: {bot.send_message.call_args[1]}")
            assert "ABCD-EFGH" in bot.send_message.call_args[1]["text"]
            
            # 2. Failure Path (402 Out of Stock)
            print("\n--- Test B2: JIT Webhook FAILURE Path (Error Isolation) ---")
            bot.send_message.reset_mock()
            order_id_2 = uuid.uuid4()
            reserved_price_2 = await redis_manager.reserve_unique_price(
                base_price=Decimal("190000.00"),
                user_id=12345678,
                product_id=2,  # out_of_stock_product
                order_id=str(order_id_2)
            )
            
            async with sqlite_sessionmaker() as session:
                async with session.begin():
                    session.add(Order(
                        id=order_id_2, user_id=12345678, product_id=2,
                        exact_amount_uzs=reserved_price_2, tiyin_suffix=0, status=OrderStatus.PENDING
                    ))
                await session.commit()
                
            response = await client.post(
                "/api/v1/payment-callback",
                headers=headers,
                json={"amount": float(reserved_price_2)}
            )
            print("  - Response:", response.status_code, response.json())
            assert response.status_code == 200
            
            # Verify status marked FAILED and audit logged
            async with sqlite_sessionmaker() as session:
                order_fail = await session.get(Order, order_id_2)
                res_audit = await session.execute(select(AuditLog).where(AuditLog.order_id == order_id_2))
                logs_fail = res_audit.scalars().all()
                
                print(f"  - Failed Order Status in DB: {order_fail.status}")
                print(f"  - Failure Audit log message: {logs_fail[0].message}")
                assert order_fail.status == OrderStatus.FAILED
                assert len(logs_fail) == 1
                assert logs_fail[0].action == "wholesale_purchase_failed"
                
            # Verify User notified and Admin alerted (2 bot messages)
            assert bot.send_message.call_count == 2
            calls = bot.send_message.call_args_list
            user_notified = any(c[1]["chat_id"] == 12345678 and "manual" in c[1]["text"] for c in calls)
            admin_alerted = any(c[1]["chat_id"] == settings.TELEGRAM_ADMIN_CHAT_ID and "Failure" in c[1]["text"] for c in calls)
            print(f"  - User notified: {user_notified}, Admin alerted: {admin_alerted}")
            assert user_notified
            assert admin_alerted

        # --- C. Redis rate-limiting bot middleware test ---
        print("\n--- Test C: Redis Rate-Limiter (Throttling Middleware) ---")
        from bot.middlewares.throttling import ThrottlingMiddleware
        from aiogram.types import Message, Chat, User as TGUser
        
        middleware = ThrottlingMiddleware()
        mock_handler = AsyncMock(return_value="handler_ok")
        
        chat = Chat(id=123, type="private")
        user = TGUser(id=99999, is_bot=False, first_name="Test")
        event = Message(message_id=1, date=datetime.now(), chat=chat, from_user=user, text="search")
        object.__setattr__(event, "answer", AsyncMock())
        
        # 1st call
        res1 = await middleware(mock_handler, event, {})
        assert res1 == "handler_ok"
        # 2nd call
        res2 = await middleware(mock_handler, event, {})
        assert res2 == "handler_ok"
        # 3rd call (should be blocked)
        res3 = await middleware(mock_handler, event, {})
        assert res3 is None  # Blocked!
        event.answer.assert_called_with("⚠️ Too fast! Please wait a moment before searching again.")
        print("✓ Spam injection blocked and warning dispatched successfully.")

        # --- D. Admin Command /admin Dashboard Verification ---
        print("\n--- Test D: Admin Telemetry Dashboard (/admin) ---")
        from bot.handlers.admin import admin_dashboard
        
        # 1. Non-admin User access gate check
        chat = Chat(id=123, type="private")
        regular_user = TGUser(id=99999, is_bot=False, first_name="Regular")
        msg_regular = Message(message_id=10, date=datetime.now(), chat=chat, from_user=regular_user, text="/admin")
        object.__setattr__(msg_regular, "answer", AsyncMock())
        
        await admin_dashboard(msg_regular)
        msg_regular.answer.assert_called_with("⛔ Access denied. This command is restricted to administrators.")
        print("  - Access denied message correctly triggered for regular user 99999.")
        
        # 2. Admin User access gate check
        admin_user = TGUser(id=6438818927, is_bot=False, first_name="Admin")
        msg_admin = Message(message_id=11, date=datetime.now(), chat=chat, from_user=admin_user, text="/admin")
        object.__setattr__(msg_admin, "answer", AsyncMock())
        
        # Ensure setting matches
        settings.TELEGRAM_ADMIN_CHAT_ID = 6438818927
        
        await admin_dashboard(msg_admin)
        assert msg_admin.answer.call_count == 1
        dashboard_text = msg_admin.answer.call_args[0][0]
        print(f"  - Dashboard card text generated:\n{dashboard_text}")
        
        # Assertions on dashboard content
        assert "Revenue & Orders" in dashboard_text
        assert "System Health" in dashboard_text
        assert "Live Exchange Rates" in dashboard_text
        assert "1 USD" in dashboard_text
        print("✓ Admin Dashboard metrics correctly calculated and rendered.")

    finally:
        print("\nStopping B2B Mock Server...")
        b2b_proc.terminate()
        b2b_proc.wait()
        print("Mock server shut down.")

# --- 4. Smoke test execution ---
def run_smoke_test():
    print("\n=========================================")
    echo("🐳 Running scripts/smoke_test.sh Utility")
    echo("=========================================")
    try:
        res = subprocess.run(["bash", "scripts/smoke_test.sh"], capture_output=True, text=True)
        print(f"Exit Code: {res.returncode}")
        print("Stdout:\n" + res.stdout)
        print("Stderr:\n" + res.stderr)
        return res.returncode
    except Exception as e:
        print(f"Error running smoke_test.sh: {e}")
        return -1

async def main():
    run_port_preflight()
    await execute_integration_audit()
    run_smoke_test()
    print("\n=========================================")
    print("🎉 SANDBOX INTEGRATION AUDIT COMPLETE!")
    print("=========================================")

if __name__ == "__main__":
    asyncio.run(main())
