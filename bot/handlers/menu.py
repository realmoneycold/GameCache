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
        [InlineKeyboardButton(text="🔍 Search Games", callback_data="btn_search")],
        [InlineKeyboardButton(text="📦 My Orders", callback_data="btn_orders")],
        [InlineKeyboardButton(text="💬 Support", callback_data="btn_support")]
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

def format_dashboard(user_mention: str, telegram_id: int, total_orders: int, total_invested: float) -> str:
    # Determine Loyalty Rank based on purchase history
    if total_orders == 0:
        rank = "🥉 BRONZE GAMER"
    elif total_orders >= 10 or total_invested >= 500000:
        rank = "🥇 GOLD GAMER"
    elif total_orders >= 3 or total_invested >= 150000:
        rank = "🥈 SILVER GAMER"
    else:
        rank = "🥉 BRONZE GAMER"

    return (
        "🎮 <b>𝙂𝘼𝙈𝙀𝙃𝙐𝘽 | 𝙋𝙀𝙍𝙎𝙊𝙉𝘼𝙇 𝘿𝘼𝙎𝙃𝘽𝙊𝘼𝙍𝘿</b>\n\n"
        f"Welcome back, Captain {user_mention}! 🚀\n"
        "─────────────────────────\n"
        "👤 <b>USER METRICS</b>\n"
        "• Account Status: 🟢 ACTIVE\n"
        f"• Loyalty Rank:   <b>{rank}</b>\n"
        f"• User Reference:  <code>#{telegram_id}</code>\n\n"
        "📊 <b>YOUR SHOPPING STATS</b>\n"
        f"• Completed Orders: <b>{total_orders} Completed</b>\n"
        f"• Total Invested:   <b>{total_invested:,.0f} UZS</b>\n"
        f"• Keys Claimed:     <b>{total_orders} Digital Assets</b>\n\n"
        "🔥 PROMO CODE ACTIVE:  Coming soon!\n"
        "─────────────────────────\n"
        "👇 Select an action from the control console below:"
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
