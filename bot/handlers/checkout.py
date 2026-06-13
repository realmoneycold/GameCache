from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from decimal import Decimal
import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from database.db import async_session, engine
from database.models import User, Product, Order, OrderStatus
from services.redis_manager import redis_manager
from services.pricing import calculate_local_price
from services import currency_sync
from config import settings

router = Router(name="checkout_router")

@router.callback_query(F.data.startswith("prod_select:"))
async def product_details(callback: CallbackQuery):
    product_id = int(callback.data.split(":")[1])
    
    async with async_session() as session:
        stmt = select(Product).where(Product.id == product_id)
        result = await session.execute(stmt)
        product = result.scalar_one_or_none()
        
    if not product:
        await callback.answer("Product not found.", show_alert=True)
        return
        
    usd_price = product.base_usd_price
    uzs_price = await calculate_local_price(usd_price, "USD")
    live_rate = await currency_sync.get_rate("USD")
    
    msg = (
        f"🎮 <b>{product.title}</b>\n\n"
        f"Platform: <code>{product.platform}</code>\n"
        f"Base Price: <b>${usd_price:.2f}</b>\n"
        f"Rate: <code>1 USD = {live_rate:,.2f} UZS</code> (+{settings.PROFIT_MARGIN_PERCENT}% margin)\n"
        f"Final Price: <b>{uzs_price:,.0f} UZS</b>\n\n"
        "Do you want to proceed to checkout for this game key?"
    )
    
    keyboard = [
        [InlineKeyboardButton(text="💳 Buy via Card (P2P)", callback_data=f"prod_buy:{product.id}")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="btn_search")]
    ]
    await callback.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()

@router.callback_query(F.data.startswith("prod_buy:"))
async def product_checkout(callback: CallbackQuery):
    product_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    username = callback.from_user.username
    
    async with async_session() as session:
        stmt = select(Product).where(Product.id == product_id)
        result = await session.execute(stmt)
        product = result.scalar_one_or_none()
        
    if not product:
        await callback.answer("Product not found.", show_alert=True)
        return
        
    usd_price = product.base_usd_price
    base_price_uzs = await calculate_local_price(usd_price, "USD")
    
    order_id = uuid.uuid4()
    
    try:
        # 1. Reserve unique price in Redis (tiyin collision solver)
        reserved_price = await redis_manager.reserve_unique_price(
            base_price=base_price_uzs,
            user_id=user_id,
            product_id=product_id,
            order_id=str(order_id)
        )
        
        # Calculate suffix (tiyins)
        suffix = int(round((reserved_price % 1) * 100))
        
        # 2. Persist user and order in database
        is_sqlite = "sqlite" in str(engine.url)
        if is_sqlite:
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert
            insert_func = sqlite_insert
        else:
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            insert_func = pg_insert

        async with async_session() as session:
            async with session.begin():
                # Upsert User to prevent foreign key errors for first-time users
                stmt_user = (
                    insert_func(User)
                    .values(
                        telegram_id=user_id,
                        username=username,
                        created_at=datetime.now(timezone.utc)
                    )
                    .on_conflict_do_update(
                        index_elements=[User.telegram_id],
                        set_={User.username: username}
                    )
                )
                await session.execute(stmt_user)
                
                # Insert pending Order
                pending_order = Order(
                    id=order_id,
                    user_id=user_id,
                    product_id=product_id,
                    exact_amount_uzs=reserved_price,
                    tiyin_suffix=suffix,
                    status=OrderStatus.PENDING
                )
                session.add(pending_order)
            await session.commit()
            
        checkout_msg = (
            f"🛒 <b>Invoice Created!</b>\n\n"
            f"Please transfer <u>exactly</u> <b>{reserved_price:,.2f} UZS</b> to card:\n"
            f"💳 <code>0000-0000-0000-0000</code>\n\n"
            f"<b>⚠️ IMPORTANT:</b> You must transfer the exact amount including the tiyins (<b>.{suffix:02d}</b>) so our system can uniquely identify your payment. "
            f"You have <b>15 minutes</b>. Our system will automatically deliver your key the instant the transfer clears."
        )
        
        keyboard = [[InlineKeyboardButton(text="🔙 Back to Menu", callback_data="btn_menu")]]
        await callback.message.edit_text(checkout_msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
        
    except Exception as e:
        print(f"[Bot Checkout] Error: {e}")
        await callback.answer("❌ Failed to create reservation. Please try again later.", show_alert=True)
