from pydantic import BaseModel
from typing import Optional

class Product(BaseModel):
    product: str
    cost: float
    stock: Optional[int] = None
