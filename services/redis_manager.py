import json
from decimal import Decimal
from typing import Optional
import redis.asyncio as aioredis
from config import settings

class RedisManager:
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.client: Optional[aioredis.Redis] = None

    async def connect(self):
        if not self.client:
            self.client = aioredis.from_url(self.redis_url, decode_responses=True)

    async def close(self):
        if self.client:
            await self.client.close()
            self.client = None

    async def reserve_unique_price(
        self, base_price: Decimal, user_id: int, product_id: int, order_id: str
    ) -> Decimal:
        """
        Attempts to reserve a unique price by appending a fractional tiyin suffix (.00 to .99)
        to the base price. Performs an atomic SET nx=True, ex=900 (15 min TTL) inside Redis.
        If a collision is found, it increments the suffix and retries.
        """
        if not self.client:
            await self.connect()
        
        payload = json.dumps({
            "user_id": user_id,
            "order_id": str(order_id),
            "product_id": product_id
        })
        
        # Try tiyin suffixes from 0 to 99
        for suffix in range(100):
            exact_amount_uzs = base_price + Decimal(suffix) / Decimal(100)
            key = f"payment_amount:{exact_amount_uzs:.2f}"
            
            # Set atomically with nx=True and ex=900 (15 minutes)
            success = await self.client.set(key, payload, ex=900, nx=True)
            if success:
                return exact_amount_uzs
                
        raise RuntimeError("No unique payment amount available (tiyin suffixes exhausted)")

    async def consume_payment_lock(self, amount: Decimal) -> Optional[dict]:
        """
        Atomically retrieves the payload for the specified payment amount and deletes the key.
        Uses a Lua script to ensure atomicity and avoid race conditions or double consumption.
        """
        if not self.client:
            await self.connect()
            
        key = f"payment_amount:{amount:.2f}"
        
        # Lua script for atomic GET and DEL
        lua_script = """
        local val = redis.call('GET', KEYS[1])
        if val then
            redis.call('DEL', KEYS[1])
        end
        return val
        """
        val = await self.client.eval(lua_script, 1, key)
        
        if val:
            return json.loads(val)
        return None

# Export global instance
redis_manager = RedisManager(settings.REDIS_URL if settings else "redis://localhost:6379/0")
