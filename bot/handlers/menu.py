from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

router = Router(name="menu_router")

def get_main_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="🔍 Search Games", callback_data="btn_search")],
        [InlineKeyboardButton(text="📦 My Orders", callback_data="btn_orders")],
        [InlineKeyboardButton(text="💬 Support", callback_data="btn_support")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@router.message(CommandStart())
async def cmd_start(message: Message):
    welcome_text = (
        "🎮 <b>Welcome to GameHub Digital Store!</b>\n\n"
        "We deliver digital game keys instantly and automatically using secure P2P payments.\n"
        "Use the buttons below to search our catalog or check your order history."
    )
    await message.answer(welcome_text, reply_markup=get_main_menu())

@router.callback_query(F.data == "btn_menu")
async def back_to_menu(callback: CallbackQuery):
    welcome_text = (
        "🎮 <b>Main Menu</b>\n\n"
        "Select an option to proceed:"
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
