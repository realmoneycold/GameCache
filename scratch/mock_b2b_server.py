from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel

app = FastAPI(title="Mock B2B Wholesaler API")

class OrderRequest(BaseModel):
    productId: str
    quantity: int

@app.post("/v3/orders")
async def create_order(req: OrderRequest, authorization: str = Header(...)):
    print(f"[Mock B2B] Received order request: productId={req.productId}, quantity={req.quantity}")
    
    # Simple token verification matching what we configured in our environment
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header"
        )
        
    if req.productId == "steam_gift_card_10":
        return {
            "products": [
                {
                    "keys": [
                        {"serial": "ABCD-EFGH-IJKL-1234"}
                    ]
                }
            ]
        }
    elif req.productId == "out_of_stock_product":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Insufficient wholesale balance or item out of stock"
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product {req.productId}"
        )

@app.get("/v3/products")
async def get_products(authorization: str = Header(...)):
    print("[Mock B2B] Received catalog products list request")
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header"
        )
    return {
        "products": [
            {
                "productId": "steam_gift_card_10",
                "name": "Steam Gift Card $10",
                "platform": "Steam",
                "price": 10.00
            },
            {
                "productId": "out_of_stock_product",
                "name": "Out Of Stock Game Key",
                "platform": "Origin",
                "price": 15.00
            },
            {
                "productId": "gta_v",
                "name": "Grand Theft Auto V",
                "platform": "Rockstar",
                "price": 20.00
            }
        ]
    }

