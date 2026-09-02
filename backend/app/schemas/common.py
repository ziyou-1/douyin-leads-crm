from typing import Any
from pydantic import BaseModel, Field


class ResponseModel(BaseModel):
    code: int = 200
    message: str = "success"
    data: Any = None


class PageResponse(BaseModel):
    code: int = 200
    message: str = "success"
    data: Any = None
    total: int = 0
    page: int = 1
    page_size: int = 20


class BatchDeleteRequest(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=100)
