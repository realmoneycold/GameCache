import asyncio
import json
import subprocess
import time
import sys
import urllib.request
import urllib.error
from decimal import Decimal
import uuid
from datetime import datetime, timezone
import os
from unittest.mock import AsyncMock

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import settings
from database.db import Base, engine, async_session
from database.models import User, Product, Order, OrderStatus, UnmappedPayment, AuditLog

# Import bot instance and mock send_message
from bot.bot_instance import bot
bot.send_message = AsyncMock()

async def setup_test_data():
    print("[Test DB Setup] Cleaning tables and inserting test records...")
    async with async_session() as session:
        async with session.begin():
            # Clean up existing records
            await session.execute(delete_all(AuditLog))
            await session.execute(delete_all(UnmappedPayment))
            await session.execute(delete_all(Order))
            await session.execute(delete_all(Product))
            await session.execute(delete_all(User))
            
            # Create a test user
            test_gamer = User(telegram_id=12345678, username="test_gamer")
            session.add(test_gamer)
            
            # Create success product
            prod_success = Product(
                id=1,
                api_product_id="steam_gift_card_10",
                title="Steam Gift Card $10",
                platform="Steam",
                base_usd_price=Decimal("10.00"),
                is_available=True
            )
            session.add(prod_success)
            
            # Create failure product (out of stock/insufficient balance)
            prod_fail = Product(
                id=2,
                api_product_id="out_of_stock_product",
                title="Out Of Stock Game Key",
                platform="Origin",
                base_usd_price=Decimal("15.00"),
                is_available=True
            )
            session.add(prod_fail)
            
        await session.commit()
    print("[Test DB Setup] Test data populated successfully.")

# Helper function to delete all rows from a table using sqlalchemy 2.0 delete()
def delete_all(model):
    from sqlalchemy import delete
    return delete(model)

async def verify_db_state(order_id: uuid.UUID):
    async with async_session() as session:
        # Check order
        result = await session.execute(select_order(order_id))
        order = result.scalar_one_or_none()
        
        # Check audit logs for this order
        result_audit = await session.execute(
            select_audit(order_id)
        )
        audit_logs = result_audit.scalars().all()
        
        # Check unmapped payments
        result_unmapped = await session.execute(select_unmapped())
        unmapped_payments = result_unmapped.scalars().all()
        
        return order, audit_logs, unmapped_payments

def select_order(order_id: uuid.UUID):
    from sqlalchemy import select
    return select(Order).where(Order.id == order_id)

def select_audit(order_id: uuid.UUID):
    from sqlalchemy import select
    return select(AuditLog).where(AuditLog.order_id == order_id)

def select_unmapped():
    from sqlalchemy import select
    return select(UnmappedPayment)

def make_post_request(url: str, headers: dict, data: dict):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, body

async def test_suite():
    # Setup test schema and data
    from services.redis_manager import redis_manager
    await setup_test_data()
    
    # Reset mock calls
    bot.send_message.reset_mock()
    
    # 1. Start Mock B2B Wholesaler Server on Port 8081
    print("\nStarting Mock B2B Server on Port 8081...")
    b2b_proc = subprocess.Popen(
        ["venv/bin/uvicorn", "scratch.mock_b2b_server:app", "--host", "127.0.0.1", "--port", "8081"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # 2. Start main FastAPI Application on Port 8080 (configuring base URL env variable)
    print("Starting GameHub FastAPI Gateway on Port 8080...")
    env = os.environ.copy()
    env["WHOLESALE_API_BASE_URL"] = "http://127.0.0.1:8081"
    env["WHOLESALE_API_TOKEN"] = "your_wholesale_api_token_here"
    
    app_proc = subprocess.Popen(
        ["venv/bin/uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8080"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    time.sleep(3)  # Allow servers to bind and start up
    
    webhook_url = "http://127.0.0.1:8080/api/v1/payment-callback"
    headers_valid = {
        "Content-Type": "application/json",
        "X-Payment-Token": settings.INTERNAL_API_SECRET_TOKEN
    }
    
    try:
        # --- TEST Case 1: Success Path JIT Procurement ---
        print("\n--- Test Case 1: JIT Procurement SUCCESS ---")
        base_price_1 = Decimal("150000.00")
        order_id_1 = uuid.uuid4()
        
        # Reserve price via Redis
        reserved_price_1 = await redis_manager.reserve_unique_price(
            base_price=base_price_1,
            user_id=12345678,
            product_id=1,  # steam_gift_card_10
            order_id=str(order_id_1)
        )
        print(f"Reserved unique price: {reserved_price_1}")
        
        # Insert pending order into DB
        async with async_session() as session:
            async with session.begin():
                pending_order_1 = Order(
                    id=order_id_1,
                    user_id=12345678,
                    product_id=1,
                    exact_amount_uzs=reserved_price_1,
                    tiyin_suffix=0,
                    status=OrderStatus.PENDING
                )
                session.add(pending_order_1)
            await session.commit()
            
        # Trigger webhook payment alert
        print(f"Sending webhook callback for success amount: {reserved_price_1}")
        status_code, response_data = make_post_request(
            webhook_url, headers_valid, {"amount": float(reserved_price_1)}
        )
        print(f"Callback response status: {status_code}, data: {response_data}")
        assert status_code == 200
        assert response_data["status"] == "success"
        
        # Wait a moment for async background task to execute
        time.sleep(1.5)
        
        # Verify Database and Redis State
        order, audit_logs, _ = await verify_db_state(order_id_1)
        print(f"Completed Order Status in Postgres: {order.status}")
        assert order.status == OrderStatus.COMPLETED
        assert len(audit_logs) == 1
        print(f"Completed Order Audit Log details: Action={audit_logs[0].action}, Message={audit_logs[0].message}")
        assert audit_logs[0].action == "wholesale_purchase_success"
        assert "ABCD-EFGH" in audit_logs[0].message
        
        # Verify Telegram Dispatch on Success
        print(f"Bot send_message call count: {bot.send_message.call_count}")
        assert bot.send_message.call_count >= 1
        called_args = bot.send_message.call_args_list[-1]
        print(f"Direct message sent to user: {called_args[1]}")
        assert called_args[1]["chat_id"] == 12345678
        assert "ABCD-EFGH" in called_args[1]["text"]
        
        # Verify redis lock was consumed
        redis_val = await redis_manager.consume_payment_lock(reserved_price_1)
        assert redis_val is None
        
        # --- TEST Case 2: Failure Path (Out of Stock / 402 Payment Required) ---
        print("\n--- Test Case 2: JIT Procurement FAILURE (Error Isolation) ---")
        base_price_2 = Decimal("180000.00")
        order_id_2 = uuid.uuid4()
        
        # Reset mock
        bot.send_message.reset_mock()
        
        # Reserve price via Redis
        reserved_price_2 = await redis_manager.reserve_unique_price(
            base_price=base_price_2,
            user_id=12345678,
            product_id=2,  # out_of_stock_product
            order_id=str(order_id_2)
        )
        print(f"Reserved unique price: {reserved_price_2}")
        
        # Insert pending order into DB
        async with async_session() as session:
            async with session.begin():
                pending_order_2 = Order(
                    id=order_id_2,
                    user_id=12345678,
                    product_id=2,
                    exact_amount_uzs=reserved_price_2,
                    tiyin_suffix=0,
                    status=OrderStatus.PENDING
                )
                session.add(pending_order_2)
            await session.commit()
            
        # Trigger webhook payment alert
        print(f"Sending webhook callback for failure amount: {reserved_price_2}")
        status_code, response_data = make_post_request(
            webhook_url, headers_valid, {"amount": float(reserved_price_2)}
        )
        print(f"Callback response status: {status_code}, data: {response_data}")
        assert status_code == 200
        assert response_data["status"] == "success"  # Webhook matches amount successfully and schedules background task
        
        # Wait a moment for async background task to execute
        time.sleep(1.5)
        
        # Verify Database and Redis State
        order_fail, audit_logs_fail, _ = await verify_db_state(order_id_2)
        print(f"Failed Order Status in Postgres: {order_fail.status}")
        assert order_fail.status == OrderStatus.FAILED
        assert len(audit_logs_fail) == 1
        print(f"Failed Order Audit Log details: Action={audit_logs_fail[0].action}, Message={audit_logs_fail[0].message}")
        assert audit_logs_fail[0].action == "wholesale_purchase_failed"
        assert "402" in audit_logs_fail[0].message
        
        # Verify Telegram Dispatches on Failure (User and Admin)
        print(f"Bot send_message call count: {bot.send_message.call_count}")
        assert bot.send_message.call_count == 2
        calls = bot.send_message.call_args_list
        user_notified = any(c[1]["chat_id"] == 12345678 and "manually processed" in c[1]["text"] for c in calls)
        admin_alerted = any(c[1]["chat_id"] == settings.TELEGRAM_ADMIN_CHAT_ID and "JIT Purchase Failure" in c[1]["text"] for c in calls)
        
        print(f"User notified of manual processing: {user_notified}")
        print(f"Admin alerted with details: {admin_alerted}")
        assert user_notified
        assert admin_alerted
        
        print("\n=== ALL TELEGRAM BOT INTERFACE & KEY DISPATCH INTEGRATION TESTS PASSED SUCCESSFULLY! ===")
        
    finally:
        print("\nStopping FastAPI gateway and B2B Mock Server...")
        app_proc.terminate()
        app_proc.wait()
        b2b_proc.terminate()
        b2b_proc.wait()
        print("Servers shut down.")

if __name__ == "__main__":
    asyncio.run(test_suite())
