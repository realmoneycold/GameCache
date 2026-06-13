import httpx
import time
import asyncio
from typing import Optional
from config import settings
from services.redis_manager import redis_manager

class WholesaleAPIClient:
    def __init__(self, base_url: str, client_id: str, client_secret: str):
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self._local_token: Optional[str] = None
        self._local_token_expiry: float = 0.0  # Unix timestamp
        self._lock = None

    async def _get_access_token(self) -> str:
        if self._lock is None:
            self._lock = asyncio.Lock()

        async with self._lock:
            # 1. Try Redis cache
            if redis_manager.client:
                try:
                    cached_token = await redis_manager.client.get("wholesale_auth_token")
                    if cached_token:
                        return cached_token
                except Exception as e:
                    # Non-fatal: proceed to check local memory
                    pass

            # 2. Try Local Memory cache
            now = time.time()
            if self._local_token and now < self._local_token_expiry:
                return self._local_token

            # 3. Perform OAuth2 handshake POST request
            print(f"[WholesaleAPIClient] Handshaking with CodesWholesale Sandbox OAuth2...")
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/oauth/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret
                    }
                )
                
                if response.status_code not in (200, 201):
                    raise httpx.HTTPStatusError(
                        f"OAuth2 authentication failed with status: {response.status_code}",
                        request=response.request,
                        response=response
                    )
                    
                data = response.json()
                access_token = data["access_token"]
                expires_in = data.get("expires_in", 3600)
                
                # Cache parameters (with 60-second safety buffer)
                buffer = 60
                ttl = max(1, expires_in - buffer)
                
                # Update Redis
                if redis_manager.client:
                    try:
                        await redis_manager.client.set("wholesale_auth_token", access_token, ex=ttl)
                    except Exception as e:
                        pass
                
                # Update Local Memory
                self._local_token = access_token
                self._local_token_expiry = time.time() + ttl
                
                print("[WholesaleAPIClient] OAuth2 token refreshed and cached successfully.")
                return access_token

    async def purchase_key(self, api_product_id: str, quantity: int = 1) -> str:
        """
        Executes a live asynchronous HTTP POST request to the wholesale distributor's API.
        Extracts and returns the raw game activation key (serial) on success.
        Raises exception if status code is not success or response structure is unexpected.
        """
        token = await self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        payload = {
            "productId": api_product_id,
            "quantity": quantity
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{self.base_url}/v3/orders",
                json=payload,
                headers=headers
            )
            
            # Raise exception if B2B supplier returns error status (e.g. 400, 402, 500)
            if response.status_code not in (200, 201):
                raise httpx.HTTPStatusError(
                    f"B2B supplier returned error status: {response.status_code}",
                    request=response.request,
                    response=response
                )
                
            data = response.json()
            try:
                # Expected structure: {"products": [{"keys": [{"serial": "XXXX-XXXX-XXXX"}]}]}
                serial = data["products"][0]["keys"][0]["serial"]
                return serial
            except (KeyError, IndexError) as e:
                raise ValueError(f"Unexpected B2B response format: {data}") from e

    async def fetch_catalog(self) -> list[dict]:
        """
        Fetches the full active game catalog from the B2B distributor API.
        Returns a list of product dicts with keys: productId, name, platform, price.
        Raises on HTTP errors or unexpected response structure.
        """
        token = await self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.base_url}/v3/products",
                headers=headers
            )

            if response.status_code not in (200, 201):
                raise httpx.HTTPStatusError(
                    f"B2B supplier catalog returned error status: {response.status_code}",
                    request=response.request,
                    response=response
                )

            data = response.json()
            try:
                # CodesWholesale Sandbox uses 'items', while some specs/mocks use 'products'
                products = data.get("items") or data.get("products")
                if products is None:
                    raise KeyError("Neither 'items' nor 'products' key found in B2B catalog response.")
                return products
            except (KeyError, TypeError) as e:
                raise ValueError(f"Unexpected B2B catalog response format: {data}") from e

# Export global instance using loaded settings
wholesale_client = WholesaleAPIClient(
    base_url=settings.WHOLESALE_API_BASE_URL if settings else "https://sandbox.codeswholesale.com",
    client_id=settings.WHOLESALE_API_CLIENT_ID if settings else "",
    client_secret=settings.WHOLESALE_API_CLIENT_SECRET if settings else ""
)
