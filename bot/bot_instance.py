from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from config import settings

# Initialize Bot with HTML default parsing properties
bot = Bot(
    token=settings.TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

# Configure FSM Storage Backend with graceful fallback to MemoryStorage if Redis is offline
storage = None
try:
    import socket
    from urllib.parse import urlparse
    parsed = urlparse(settings.REDIS_URL)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    # Perform a quick 0.5-second socket connect check
    s = socket.create_connection((host, port), timeout=0.5)
    s.close()
    
    storage = RedisStorage.from_url(settings.REDIS_URL)
    print("ℹ️ Redis FSM Storage initialized successfully.")
except Exception:
    from aiogram.fsm.storage.memory import MemoryStorage
    storage = MemoryStorage()
    print("⚠️ Redis is offline/inaccessible! Falling back to MemoryStorage for FSM.")

# Instantiate global dispatcher
dp = Dispatcher(storage=storage)

def setup_routers():
    """Import and register bot routers and middleware cleanly to prevent import cycles."""
    from bot.handlers.menu import router as menu_router
    from bot.handlers.search import router as search_router
    from bot.handlers.checkout import router as checkout_router
    from bot.handlers.admin import router as admin_router
    from bot.middlewares.throttling import ThrottlingMiddleware
    
    # Register anti-spam throttling as outer middleware on all update types
    throttle = ThrottlingMiddleware()
    dp.message.outer_middleware(throttle)
    dp.callback_query.outer_middleware(throttle)
    
    dp.include_router(admin_router)
    dp.include_router(menu_router)
    dp.include_router(search_router)
    dp.include_router(checkout_router)
