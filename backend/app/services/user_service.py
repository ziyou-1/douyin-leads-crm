"""User service — business logic separated from route handlers."""

from typing import Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import (
    ALL_ROLES,
    ADMIN_CREATABLE_ROLES,
    CS_ADMIN_MANAGEABLE_ROLES,
    ROLE_ADMIN,
    ROLE_CUSTOMER_SERVICE,
    ROLE_CUSTOMER_SERVICE_ADMIN,
    can_manage_users,
    cs_admin_can_manage_user,
)
from app.core.security import verify_password, get_password_hash
from app.models.user import User
from app.schemas.user import UserCreate


def _validate_role_for_operator(operator_role: str, target_role: str) -> None:
    if target_role not in ALL_ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效的角色")
    if operator_role == ROLE_ADMIN:
        if target_role not in ADMIN_CREATABLE_ROLES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效的角色")
        return
    if operator_role == ROLE_CUSTOMER_SERVICE_ADMIN:
        if target_role not in CS_ADMIN_MANAGEABLE_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能管理客服用户")
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")


def _ensure_can_access_user(operator: User, target: User) -> None:
    if operator.role == ROLE_ADMIN:
        return
    if operator.role == ROLE_CUSTOMER_SERVICE_ADMIN:
        if not cs_admin_can_manage_user(target.role):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能管理客服用户")
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")


def _roles_filter_for_operator(operator_role: str) -> Optional[list[str]]:
    if operator_role == ROLE_ADMIN:
        return None
    if operator_role == ROLE_CUSTOMER_SERVICE_ADMIN:
        return [ROLE_CUSTOMER_SERVICE]
    return []


async def authenticate_user(
    db: AsyncSession, username: str, password: str
) -> Optional[User]:
    """Return the user if credentials are valid, else None."""
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user


async def create_user(db: AsyncSession, data: UserCreate, operator: User) -> User:
    """Create a new user and return it."""
    if not can_manage_users(operator.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    _validate_role_for_operator(operator.role, data.role)

    user = User(
        username=data.username,
        password_hash=get_password_hash(data.password),
        role=data.role,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_username(db: AsyncSession, username: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_users(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    search: Optional[str] = None,
    operator: Optional[User] = None,
) -> Tuple[list, int]:
    """Return (list_of_users, total_count) with pagination and optional search."""
    query = select(User)
    count_query = select(sa_func.count()).select_from(User)

    if operator is not None:
        role_filter = _roles_filter_for_operator(operator.role)
        if role_filter is not None:
            if not role_filter:
                return [], 0
            query = query.where(User.role.in_(role_filter))
            count_query = count_query.where(User.role.in_(role_filter))

    if search:
        like_pattern = f"%{search}%"
        query = query.where(User.username.ilike(like_pattern))
        count_query = count_query.where(User.username.ilike(like_pattern))

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(User.id.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    users = list(result.scalars().all())

    return users, total


async def update_user(
    db: AsyncSession,
    user_id: int,
    operator: User,
    role: Optional[str] = None,
    status: Optional[str] = None,
) -> Optional[User]:
    user = await get_user_by_id(db, user_id)
    if user is None:
        return None
    _ensure_can_access_user(operator, user)
    if role is not None:
        _validate_role_for_operator(operator.role, role)
        user.role = role
    if status is not None:
        user.status = status
    await db.flush()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user_id: int, operator: User) -> bool:
    user = await get_user_by_id(db, user_id)
    if user is None:
        return False
    _ensure_can_access_user(operator, user)
    await db.delete(user)
    await db.flush()
    return True


async def reset_user_password(
    db: AsyncSession, user_id: int, new_password: str, operator: User
) -> Optional[User]:
    user = await get_user_by_id(db, user_id)
    if user is None:
        return None
    _ensure_can_access_user(operator, user)
    user.password_hash = get_password_hash(new_password)
    await db.flush()
    await db.refresh(user)
    return user
