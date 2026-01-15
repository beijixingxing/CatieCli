from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings
from app.database import get_db
from app.models.user import User, APIKey
from app.cache import cache, CACHE_KEYS, cached

security = HTTPBearer(auto_error=False)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


async def get_user_by_username(db: AsyncSession, username: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_user_by_api_key(db: AsyncSession, api_key: str) -> Optional[User]:
    """通过API Key获取用户 - 带缓存"""
    # 生成缓存键
    cache_key = f"{CACHE_KEYS['user']}:api_key:{api_key}"
    
    # 尝试从缓存获取
    cached_user_dict = cache.get(cache_key)
    if cached_user_dict:
        # 检查缓存值是否为协程对象，如果是则跳过缓存
        if callable(getattr(cached_user_dict, "__await__", None)):
            # 清除无效的协程对象缓存
            cache.delete(cache_key)
        else:
            try:
                # 从缓存重建User对象
                user = User(
                    id=cached_user_dict["id"],
                    username=cached_user_dict["username"],
                    email=cached_user_dict["email"],
                    hashed_password=cached_user_dict["hashed_password"],
                    discord_id=cached_user_dict["discord_id"],
                    discord_name=cached_user_dict["discord_name"],
                    is_active=cached_user_dict["is_active"],
                    is_admin=cached_user_dict["is_admin"],
                    daily_quota=cached_user_dict["daily_quota"],
                    bonus_quota=cached_user_dict["bonus_quota"],
                    quota_flash=cached_user_dict["quota_flash"],
                    quota_25pro=cached_user_dict["quota_25pro"],
                    quota_30pro=cached_user_dict["quota_30pro"],
                    created_at=datetime.fromisoformat(cached_user_dict["created_at"])
                )
                return user
            except (TypeError, KeyError, ValueError):
                # 清除无效的缓存值
                cache.delete(cache_key)
    
    # 缓存中没有，查询数据库
    result = await db.execute(
        select(APIKey).where(APIKey.key == api_key, APIKey.is_active == True)
    )
    key_obj = result.scalar_one_or_none()
    if key_obj:
        # 更新最后使用时间
        key_obj.last_used_at = datetime.utcnow()
        await db.commit()
        
        result = await db.execute(select(User).where(User.id == key_obj.user_id))
        user = result.scalar_one_or_none()
        
        if user:
            # 将用户对象转换为字典并存入缓存（缓存1小时）
            user_dict = {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "hashed_password": user.hashed_password,
                "discord_id": user.discord_id,
                "discord_name": user.discord_name,
                "is_active": user.is_active,
                "is_admin": user.is_admin,
                "daily_quota": user.daily_quota,
                "bonus_quota": user.bonus_quota,
                "quota_flash": user.quota_flash,
                "quota_25pro": user.quota_25pro,
                "quota_30pro": user.quota_30pro,
                "created_at": user.created_at.isoformat()
            }
            cache.set(cache_key, user_dict, ttl=3600)  # 缓存1小时
        
        return user
    return None


async def authenticate_user(db: AsyncSession, username: str, password: str) -> Optional[User]:
    user = await get_user_by_username(db, username)
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """获取当前用户 (JWT认证)"""
    if not credentials:
        print("JWT认证失败: 未提供认证信息", flush=True)
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="无效的认证令牌")
    except JWTError:
        raise HTTPException(status_code=401, detail="无效的认证令牌")
    
    user = await get_user_by_username(db, username)
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="用户已被禁用")
    return user


async def get_current_admin(user: User = Depends(get_current_user)) -> User:
    """获取管理员用户"""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
