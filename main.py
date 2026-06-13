import asyncio
import json
import logging
import logging.config
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database.db import engine
from services.redis_manager import redis_manager
from services import currency_sync
from services import catalog_sync
from api.webhook import router as webhook_router
from bot.bot_instance import bot, dp, setup_routers
from config import settings


# Initialize structured logging configuration
os.makedirs("logs", exist_ok=True)
logging_config_path = os.path.join(os.path.dirname(__file__), "config", "logging.json")
if os.path.exists(logging_config_path):
    with open(logging_config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
        logging.config.dictConfig(config)
    logging.info("Structured logging initialized successfully using %s", logging_config_path)
else:
    logging.basicConfig(level=logging.INFO)
    logging.warning("Logging config file not found at %s. Defaulting to basic config.", logging_config_path)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        # Startup: Initialize database schemas and Redis connection pool
        print("[Lifespan] Initializing database and Redis connection pools...")
        
        # Auto-create tables for the active database engine (SQLite or PostgreSQL)
        from database.db import engine
        from database.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("[Lifespan] Database tables verified/created successfully.")
            
        await redis_manager.connect()
        
        # Launch CBU exchange rate sync loop
        print("[Lifespan] Starting currency exchange rate sync loop...")
        sync_task = asyncio.create_task(currency_sync.start_sync_loop())
        
        # Launch wholesale catalog sync loop
        print("[Lifespan] Starting wholesale catalog sync loop...")
        catalog_task = asyncio.create_task(catalog_sync.start_sync_loop())
        
        # Setup bot routers and run polling in background
        setup_routers()
        
        # Set bot commands list for autocomplete when typing '/'
        from aiogram.types import BotCommand, BotCommandScopeDefault, BotCommandScopeChat
        try:
            # 1. Default commands for everyone (only /start)
            await bot.set_my_commands([
                BotCommand(command="start", description="Start the bot and open main menu")
            ], scope=BotCommandScopeDefault())
            
            # 2. Admin commands for the specific admin user (settings.TELEGRAM_ADMIN_CHAT_ID)
            admin_id = settings.TELEGRAM_ADMIN_CHAT_ID
            if admin_id:
                try:
                    await bot.set_my_commands([
                        BotCommand(command="start", description="Start the bot and open main menu"),
                        BotCommand(command="admin", description="Open admin telemetry dashboard (restricted)")
                    ], scope=BotCommandScopeChat(chat_id=int(admin_id)))
                    print(f"[Lifespan] Admin bot commands set for chat/user {admin_id}.")
                except Exception as admin_err:
                    logging.error("Failed to set admin specific commands: %s", admin_err)
                    
            print("[Lifespan] Bot commands set successfully.")
        except Exception as e:
            logging.error("Failed to set bot commands: %s", e)
            
        print("[Lifespan] Sending startup notification to Telegram ID 6438818927...")
        try:
            await bot.send_message(chat_id=6438818927, text="🚀 GameHub Core Engine has successfully booted and the bot is officially live!")
            logging.info("Sent startup notification to Telegram ID 6438818927.")
        except Exception as e:
            logging.error("Failed to send bot startup notification: %s", e)
            
        print("[Lifespan] Starting Telegram Bot polling...")
        polling_task = asyncio.create_task(dp.start_polling(bot))
        
        yield
    except Exception as lifespan_err:
        logging.critical("Lifespan startup encountered critical crash: %s", lifespan_err, exc_info=True)
        try:
            await bot.send_message(chat_id=6438818927, text=f"🚨 CRITICAL ALERT: GameHub Core Engine crashed on startup!\nError: `{lifespan_err}`")
        except Exception as msg_err:
            logging.error("Failed to send crash notification: %s", msg_err)
        raise lifespan_err
    finally:
        # Shutdown: Clean up connections and database engine pools
        print("[Lifespan] Stopping Telegram Bot polling...")
        try:
            await bot.send_message(chat_id=6438818927, text="⚠️ GameHub Core Engine is shutting down/turning off. The bot is now offline.")
            print("[Lifespan] Shutdown notification sent to Telegram ID 6438818927.")
        except Exception as e:
            logging.error("Failed to send bot shutdown notification: %s", e)
            
        try:
            await dp.stop_polling()
        except Exception:
            pass
        try:
            await bot.session.close()
        except Exception:
            pass
        
        print("[Lifespan] Disposing database and Redis connection pools...")
        try:
            await redis_manager.close()
        except Exception:
            pass
        try:
            from database.db import engine
            await engine.dispose()
        except Exception:
            pass

app = FastAPI(
    title="GameHub API Gateway",
    description="Zero-inventory, JIT digital game-key distribution platform backend engine.",
    version="1.0.0",
    lifespan=lifespan
)

# Middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Set to specific domains in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Core status check route
@app.get("/health", tags=["status"])
async def health_check():
    return {
        "status": "healthy",
        "database_engine": "SQLAlchemy (asyncpg)",
        "cache_store": "Redis (asyncio)"
    }

# Register API endpoint routes
app.include_router(webhook_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8080, reload=False)

