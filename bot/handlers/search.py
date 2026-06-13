from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from database.db import async_session
from database.models import Product

router = Router(name="search_router")

class GameSearchSGM(StatesGroup):
    waiting_for_query = State()

@router.callback_query(F.data == "btn_search")
async def start_search(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameSearchSGM.waiting_for_query)
    keyboard = [[InlineKeyboardButton(text="🔙 Cancel", callback_data="btn_menu")]]
    await callback.message.edit_text(
        "🔍 <b>Search Games</b>\n\n"
        "Please enter the game title you want to search for (e.g. <i>Steam</i> or <i>GTA</i>):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()

@router.message(GameSearchSGM.waiting_for_query)
async def process_search_query(message: Message, state: FSMContext):
    query = message.text.strip()
    if len(query) < 2:
        await message.answer("⚠️ Search query must be at least 2 characters long. Please try again:")
        return
        
    async with async_session() as session:
        stmt = (
            select(Product)
            .where(Product.title.ilike(f"%{query}%"))
            .where(Product.is_available == True)
            .limit(10)
        )
        result = await session.execute(stmt)
        products = result.scalars().all()
        
    if not products:
        keyboard = [[InlineKeyboardButton(text="🔙 Back to Menu", callback_data="btn_menu")]]
        await message.answer(
            f"❌ No games found matching <b>'{query}'</b>.\nPlease try another search:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        return
        
    # Build inline results list
    keyboard = []
    for p in products:
        keyboard.append([InlineKeyboardButton(
            text=f"🎮 {p.title} ({p.platform}) - ${p.base_usd_price:.2f}",
            callback_data=f"prod_select:{p.id}"
        )])
    keyboard.append([InlineKeyboardButton(text="🔙 Back to Menu", callback_data="btn_menu")])
    
    await message.answer(
        f"🔍 <b>Search Results for '{query}':</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    # Reset FSM state
    await state.clear()
