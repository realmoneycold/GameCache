"""
Admin Telemetry Dashboard
Protected Aiogram router with aggregate metrics for operational oversight.
Access is restricted to the configured TELEGRAM_ADMIN_CHAT_ID.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from decimal import Decimal
from sqlalchemy import select, func

from database.db import async_session
from database.models import Order, OrderStatus, UnmappedPayment, AuditLog
from services.redis_manager import redis_manager
from services import currency_sync
from config import settings

router = Router(name="admin_router")


def is_admin(user_id: int) -> bool:
    """Check if the user is an authorized admin."""
    admin_id = settings.TELEGRAM_ADMIN_CHAT_ID
    # Support both positive user IDs and negative group IDs
    return user_id == admin_id or user_id == abs(admin_id)


@router.message(Command("admin"))
async def admin_dashboard(message: Message):
    # Gate: reject non-admin users silently
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Access denied. This command is restricted to administrators.")
        return

    # ---- Aggregate Database Metrics ----
    async with async_session() as session:
        # Total revenue from completed orders
        result = await session.execute(
            select(func.coalesce(func.sum(Order.exact_amount_uzs), 0))
            .where(Order.status == OrderStatus.COMPLETED)
        )
        total_revenue = result.scalar() or Decimal("0")

        # Order counts by status
        result = await session.execute(
            select(func.count()).where(Order.status == OrderStatus.COMPLETED)
        )
        completed_count = result.scalar() or 0

        result = await session.execute(
            select(func.count()).where(Order.status == OrderStatus.FAILED)
        )
        failed_count = result.scalar() or 0

        result = await session.execute(
            select(func.count()).where(Order.status == OrderStatus.PENDING)
        )
        pending_count = result.scalar() or 0

        # Unmapped payments
        result = await session.execute(
            select(func.count()).select_from(UnmappedPayment)
        )
        unmapped_count = result.scalar() or 0

        # Audit failure logs
        result = await session.execute(
            select(func.count()).where(AuditLog.action == "wholesale_purchase_failed")
        )
        audit_failures = result.scalar() or 0

    # ---- Redis Metrics ----
    active_locks = 0
    if redis_manager.client:
        try:
            lock_keys = await redis_manager.client.keys("payment_amount:*")
            active_locks = len(lock_keys)
        except Exception:
            active_locks = -1  # Error indicator

    # ---- Live Exchange Rates ----
    usd_rate = await currency_sync.get_rate("USD")
    eur_rate = await currency_sync.get_rate("EUR")

    # ---- Build Dashboard Card ----
    dashboard = (
        "📊 <b>GameHub Admin Telemetry Dashboard</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "💰 <b>Revenue & Orders</b>\n"
        f"  Total Revenue: <b>{total_revenue:,.0f} UZS</b>\n"
        f"  ✅ Completed: <b>{completed_count}</b>\n"
        f"  ❌ Failed: <b>{failed_count}</b>\n"
        f"  ⏳ Pending: <b>{pending_count}</b>\n\n"
        
        "🔍 <b>System Health</b>\n"
        f"  Unmapped Payments: <b>{unmapped_count}</b>\n"
        f"  Audit Failures: <b>{audit_failures}</b>\n"
        f"  Active Redis Locks: <b>{active_locks}</b>\n\n"
        
        "💱 <b>Live Exchange Rates (CBU)</b>\n"
        f"  1 USD = <code>{usd_rate:,.2f} UZS</code>\n"
        f"  1 EUR = <code>{eur_rate:,.2f} UZS</code>\n"
        f"  Profit Margin: <code>{settings.PROFIT_MARGIN_PERCENT}%</code>\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Powered by GameHub Engine v1.0</i>"
    )

    await message.answer(dashboard)
