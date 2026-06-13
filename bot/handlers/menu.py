import html
from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from database.db import async_session, engine
from database.models import User, Order, OrderStatus

router = Router(name="menu_router")

def get_main_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="🔍 Scan Catalog", callback_data="btn_search")],
        [InlineKeyboardButton(text="📦 My Vault", callback_data="btn_orders")],
        [InlineKeyboardButton(text="💬 Support Terminal", callback_data="btn_support")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

async def get_and_upsert_user_stats(user_id: int, username: str | None, first_name: str) -> dict:
    is_sqlite = "sqlite" in str(engine.url)
    insert_func = sqlite_insert if is_sqlite else pg_insert

    # Upsert user in the database
    async with async_session() as session:
        async with session.begin():
            stmt_user = (
                insert_func(User)
                .values(
                    telegram_id=user_id,
                    username=username,
                    created_at=datetime.now(timezone.utc)
                )
                .on_conflict_do_update(
                    index_elements=[User.telegram_id],
                    set_={"username": username}
                )
            )
            await session.execute(stmt_user)

        # Retrieve completed order stats
        stmt_stats = (
            select(
                func.count(Order.id).label("total_orders"),
                func.coalesce(func.sum(Order.exact_amount_uzs), 0).label("total_invested")
            )
            .where(Order.user_id == user_id)
            .where(Order.status == OrderStatus.COMPLETED)
        )
        stats_result = await session.execute(stmt_stats)
        stats_row = stats_result.first()
        
        total_orders = stats_row.total_orders if stats_row else 0
        total_invested = float(stats_row.total_invested) if stats_row else 0.0
        
        return {
            "total_orders": total_orders,
            "total_invested": total_invested
        }

def get_loyalty_rank(total_orders: int, total_invested: float) -> tuple:
    """
    5-tier gamified loyalty rank engine.
    Returns (badge, rank_name, tier_number) based on purchase history.
    """
    if total_orders > 10 or total_invested >= 1_000_000:
        return ("💎", "VIP PLATINUM", 5)
    elif total_orders >= 6 or total_invested >= 500_000:
        return ("🥇", "GOLD ELITE", 4)
    elif total_orders >= 3 or total_invested >= 150_000:
        return ("🥈", "SILVER GAMER", 3)
    elif total_orders >= 1:
        return ("🥉", "BRONZE WARRIOR", 2)
    else:
        return ("🆕", "ROOKIE", 1)


def format_dashboard(user_mention: str, telegram_id: int, total_orders: int, total_invested: float) -> str:
    badge, rank_name, tier = get_loyalty_rank(total_orders, total_invested)

    # Format invested amount with thousands separators
    invested_display = f"{total_invested:,.0f}"

    return (
        f"⚡️ <b>WELCOME TO THE VAULT, {user_mention}</b> ⚡️\n\n"
        "Your secure session is encrypted and active.\n\n"
        "┌── 📊 <b>SYSTEM CORE DATA</b> ──────────────────┐\n"
        f"│  🏷️ RANK:      <code>{badge} {rank_name} (Tier {tier})</code>\n"
        f"│  📦 PURCHASES: <code>{total_orders} Successful Dispatches</code>\n"
        f"│  💰 INVESTED:  <code>{invested_display} UZS</code>\n"
        "│  🪙 WALLET:    <code>Automated P2P Gateway</code>\n"
        f"│  🛡️ PROFILE:   <code>Verified · #{telegram_id}</code>\n"
        "└─── • 🛍️ ALL DIGITAL KEYS INSURED • ─────┘\n\n"
        "🚀 All wholesale nodes are operational. Systems functional.\n\n"
        "👇 Tap a terminal engine below to scan our catalog or query your vault:"
    )

@router.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    user_mention = f"@{html.escape(username)}" if username else html.escape(first_name)
    
    # Get stats and ensure user is registered
    stats = await get_and_upsert_user_stats(user_id, username, first_name)
    
    welcome_text = format_dashboard(
        user_mention=user_mention,
        telegram_id=user_id,
        total_orders=stats["total_orders"],
        total_invested=stats["total_invested"]
    )
    
    await message.answer(welcome_text, reply_markup=get_main_menu())

@router.callback_query(F.data == "btn_menu")
async def back_to_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    username = callback.from_user.username
    first_name = callback.from_user.first_name
    
    user_mention = f"@{html.escape(username)}" if username else html.escape(first_name)
    
    # Get stats and ensure user is registered
    stats = await get_and_upsert_user_stats(user_id, username, first_name)
    
    welcome_text = format_dashboard(
        user_mention=user_mention,
        telegram_id=user_id,
        total_orders=stats["total_orders"],
        total_invested=stats["total_invested"]
    )
    
    await callback.message.edit_text(welcome_text, reply_markup=get_main_menu())
    await callback.answer()

@router.callback_query(F.data == "btn_support")
async def support_handler(callback: CallbackQuery):
    support_text = (
        "💬 <b>GameHub Support</b>\n\n"
        "Need help with your purchase? Contact our administrator at @GameHubSupportBot.\n"
        "We are available 24/7 to resolve any manual key fulfillment issues."
    )
    keyboard = [[InlineKeyboardButton(text="🔙 Back to Menu", callback_data="btn_menu")]]
    await callback.message.edit_text(support_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()

@router.callback_query(F.data == "btn_orders")
async def orders_handler(callback: CallbackQuery):
    from database.db import async_session
    from database.models import Order
    from sqlalchemy import select
    
    user_id = callback.from_user.id
    async with async_session() as session:
        stmt = select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc()).limit(5)
        result = await session.execute(stmt)
        orders = result.scalars().all()
        
    if not orders:
        msg = "📦 You have no orders yet. Go search for some games!"
    else:
        msg = "📦 <b>Your Recent Orders:</b>\n\n"
        for o in orders:
            msg += f"• Order: <code>{o.id}</code>\n"
            msg += f"  Amount: {o.exact_amount_uzs:,.2f} UZS\n"
            status_emoji = "⏳" if o.status == "pending" else "✅" if o.status == "completed" else "❌"
            msg += f"  Status: {status_emoji} {o.status.upper()}\n\n"
            
    keyboard = [[InlineKeyboardButton(text="🔙 Back to Menu", callback_data="btn_menu")]]
    await callback.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()
