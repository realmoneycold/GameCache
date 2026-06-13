import httpx
from config import settings

class WholesaleAPIClient:
    def __init__(self, base_url: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token

    async def purchase_key(self, api_product_id: str, quantity: int = 1) -> str:
        """
        Executes a live asynchronous HTTP POST request to the wholesale distributor's API.
        Extracts and returns the raw game activation key (serial) on success.
        Raises exception if status code is not success or response structure is unexpected.
        """
        headers = {
            "Authorization": f"Bearer {self.api_token}",
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
        headers = {
            "Authorization": f"Bearer {self.api_token}",
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
                return data["products"]
            except (KeyError, TypeError) as e:
                raise ValueError(f"Unexpected B2B catalog response format: {data}") from e

# Export global instance using loaded settings
wholesale_client = WholesaleAPIClient(
    base_url=settings.WHOLESALE_API_BASE_URL if settings else "https://api.codeswholesale.com",
    api_token=settings.WHOLESALE_API_TOKEN if settings else ""
)
