import datetime
from typing import Literal, Optional
from pydantic import BaseModel, field_validator

from app.core.roles import ALL_ROLES

RoleType = Literal["admin", "customer_service_admin", "customer_service"]


class UserCreate(BaseModel):
    username: str
    password: str
    role: RoleType = "customer_service"

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ALL_ROLES:
            raise ValueError("无效的角色")
        return v


class UserUpdate(BaseModel):
    role: Optional[RoleType] = None
    status: Optional[str] = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ALL_ROLES:
            raise ValueError("无效的角色")
        return v


class PasswordReset(BaseModel):
    new_password: str


class UserLogin(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    status: str
    created_at: datetime.datetime

    class Config:
        from_attributes = True
