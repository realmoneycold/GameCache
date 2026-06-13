"""
Redis-Backed Anti-Spam Throttling Middleware for Aiogram 3.x
Implements a sliding-window rate limiter using Redis INCR + EXPIRE.
Limits users to MAX_REQUESTS_PER_SECOND interactions per 1-second window.
Fail-open: if Redis is unavailable, the event passes through.
"""
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from services.redis_manager import redis_manager

# Rate limit: max interactions per 1-second sliding window
MAX_REQUESTS_PER_SECOND = 2
WINDOW_SECONDS = 1
RATE_KEY_PREFIX = "user_spam_lock"

WARNING_TEXT = "⚠️ Too fast! Please wait a moment before searching again."


class ThrottlingMiddleware(BaseMiddleware):
    """
    Outer middleware that intercepts every Message and CallbackQuery.
    Uses a Redis sliding-window counter to enforce rate limits.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Extract user ID from the event
        user_id = self._get_user_id(event)
        if user_id is None:
            # Can't identify user — pass through
            return await handler(event, data)

        # Check rate limit
        if await self._is_rate_limited(user_id):
            # Block the event and send a warning
            await self._send_warning(event)
            return  # Do NOT call handler — event is swallowed

        # Within limits — proceed normally
        return await handler(event, data)

    @staticmethod
    def _get_user_id(event: TelegramObject) -> int | None:
        """Extract the Telegram user ID from a Message or CallbackQuery."""
        if isinstance(event, Message) and event.from_user:
            return event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            return event.from_user.id
        return None

    @staticmethod
    async def _is_rate_limited(user_id: int) -> bool:
        """
        Increment a per-user counter in Redis with a 1-second TTL.
        Returns True if the user has exceeded the limit.
        """
        if not redis_manager.client:
            return False  # Fail-open: if Redis is down, allow the event

        key = f"{RATE_KEY_PREFIX}:{user_id}"
        try:
            # Atomic INCR — creates the key with value 1 if it doesn't exist
            current_count = await redis_manager.client.incr(key)

            if current_count == 1:
                # First request in this window — set the 1-second expiry
                await redis_manager.client.expire(key, WINDOW_SECONDS)

            return current_count > MAX_REQUESTS_PER_SECOND

        except Exception as e:
            # Fail-open: Redis error should not block users
            print(f"[Throttle] ⚠ Redis error during rate check: {e}")
            return False

    @staticmethod
    async def _send_warning(event: TelegramObject) -> None:
        """Send a throttle warning to the user."""
        try:
            if isinstance(event, Message):
                await event.answer(WARNING_TEXT)
            elif isinstance(event, CallbackQuery):
                await event.answer(WARNING_TEXT, show_alert=True)
        except Exception:
            pass  # Silently ignore send failures
