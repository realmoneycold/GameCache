import uuid
import asyncio
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update

from config import settings
from database.db import get_async_session
from database.models import Order, OrderStatus, UnmappedPayment, AuditLog, Product, User
from services.redis_manager import redis_manager
from services.wholesale_client import wholesale_client

router = APIRouter(prefix="/api/v1", tags=["webhook"])

class PaymentCallbackPayload(BaseModel):
    amount: Decimal = Field(..., description="The exact transaction amount in UZS", ge=0)

async def verify_payment_token(x_payment_token: str = Header(..., alias="X-Payment-Token")):
    if x_payment_token != settings.INTERNAL_API_SECRET_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid security token."
        )

async def process_jit_key_delivery(order_id: str):
    """
    Asynchronous JIT background task to acquire game key from wholesaler,
    update order status in Postgres, send direct Telegram updates to the user,
    and log audits.
    """
    from database.db import async_session
    from sqlalchemy import select
    from bot.bot_instance import bot
    
    order_uuid = uuid.UUID(order_id)
    
    async with async_session() as session:
        # Step 1: Retrieve order, product, and user details
        stmt = (
            select(Order.id, Product.api_product_id, Order.user_id, User.username)
            .join(Product, Order.product_id == Product.id)
            .join(User, Order.user_id == User.telegram_id)
            .where(Order.id == order_uuid)
        )
        result = await session.execute(stmt)
        row = result.first()
        if not row:
            print(f"[JIT Worker] Order {order_id} or associated product/user not found.")
            return
            
        order_db_id, api_product_id, user_id, username = row
        
        # Step 2: Make the wholesale purchase request
        try:
            print(f"[JIT Worker] Procuring key for product '{api_product_id}' (Order: {order_id})")
            serial = await wholesale_client.purchase_key(api_product_id)
            
            # Step 3: Success updates (completed, resolved_at, audit log)
            # Update order to COMPLETED
            stmt_update = (
                update(Order)
                .where(Order.id == order_uuid)
                .values(status=OrderStatus.COMPLETED, resolved_at=datetime.now(timezone.utc))
            )
            await session.execute(stmt_update)
            
            # Add Audit Log
            audit = AuditLog(
                order_id=order_uuid,
                action="wholesale_purchase_success",
                message=f"Key successfully acquired: {serial}"
            )
            session.add(audit)
            
            await session.commit()
            print(f"[JIT Worker] Fulfillment success for Order {order_id}. Serial: {serial}")
            
            # Asynchronously dispatch key to the user's Telegram ID
            try:
                msg_text = (
                    "🎉 <b>Payment verified! Your game key is ready!</b>\n\n"
                    "Here is your activation serial:\n"
                    f"<code>{serial}</code>\n\n"
                    "<i>Tap the key code above to copy it instantly. Thank you for purchasing from GameHub!</i>"
                )
                await bot.send_message(chat_id=user_id, text=msg_text)
            except Exception as tg_err:
                print(f"[JIT Worker] Telegram success delivery failed for user {user_id}: {tg_err}")
            
        except Exception as e:
            # Step 4: Failure updates (failed, resolved_at, audit log)
            print(f"[JIT Worker] Fulfillment failure for Order {order_id}: {e}")
            # Update order to FAILED
            stmt_update = (
                update(Order)
                .where(Order.id == order_uuid)
                .values(status=OrderStatus.FAILED, resolved_at=datetime.now(timezone.utc))
            )
            await session.execute(stmt_update)
            
            # Add Audit Log for manual admin intervention
            audit = AuditLog(
                order_id=order_uuid,
                action="wholesale_purchase_failed",
                message=f"Purchase failed: {str(e)}"
            )
            session.add(audit)
            
            await session.commit()
            
            # Asynchronously dispatch failure notifications to user and admin group
            try:
                # Notify User of manual processing
                user_msg = (
                    "💳 <b>Payment verified!</b>\n\n"
                    "Your order is currently being manually processed by our team shortly."
                )
                await bot.send_message(chat_id=user_id, text=user_msg)
                
                # Notify Admins with details
                admin_msg = (
                    f"⚠️ <b>[ADMIN ALERT] JIT Purchase Failure</b>\n\n"
                    f"Order ID: <code>{order_uuid}</code>\n"
                    f"Product: <code>{api_product_id}</code>\n"
                    f"User: @{username or 'N/A'} (ID: {user_id})\n"
                    f"Error Details: <code>{str(e)}</code>"
                )
                await bot.send_message(chat_id=settings.TELEGRAM_ADMIN_CHAT_ID, text=admin_msg)
            except Exception as tg_err:
                print(f"[JIT Worker] Telegram failure delivery failed: {tg_err}")

@router.post("/payment-callback")
async def payment_callback(
    payload: PaymentCallbackPayload,
    background_tasks: BackgroundTasks,
    x_payment_token: str = Depends(verify_payment_token),
    db: AsyncSession = Depends(get_async_session)
):
    # Lookup and consume lock in Redis
    lock_data = await redis_manager.consume_payment_lock(payload.amount)
    
    if lock_data:
        order_id_str = lock_data["order_id"]
        order_uuid = uuid.UUID(order_id_str)
        
        # Atomically update order status in Postgres
        stmt = (
            update(Order)
            .where(Order.id == order_uuid)
            .values(
                status=OrderStatus.COMPLETED,
                resolved_at=datetime.now(timezone.utc)
            )
        )
        await db.execute(stmt)
        await db.commit()
        
        # Enqueue background task to fetch from supplier and deliver game-key
        background_tasks.add_task(process_jit_key_delivery, order_id_str)
        
        return {
            "status": "success",
            "message": "Payment matched, order status updated, and fulfillment task scheduled.",
            "order_id": order_id_str
        }
    else:
        # Save to UnmappedPayment table as audit log
        unmapped = UnmappedPayment(
            received_amount_uzs=payload.amount,
            parsed_timestamp=datetime.now(timezone.utc),
            is_resolved=False
        )
        db.add(unmapped)
        await db.commit()
        
        return {
            "status": "unmapped",
            "message": "No active order matching the payment amount was found. Payment recorded in audit fallback."
        }
