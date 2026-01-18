"""
自定义错误消息配置 API

管理员可以配置不同错误类型返回给客户端的友好消息。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from app.database import get_db
from app.models.user import User, ErrorMessageConfig, SystemConfig
from app.routers.auth import get_current_user
from app.services.error_classifier import ErrorType, ERROR_TYPE_NAMES

router = APIRouter(prefix="/api/admin/error-messages", tags=["错误消息配置"])


# ===== Pydantic 模型 =====

class ErrorMessageCreate(BaseModel):
    error_type: Optional[str] = None
    keyword: Optional[str] = None
    custom_message: str
    priority: int = 0
    is_active: bool = True


class ErrorMessageUpdate(BaseModel):
    error_type: Optional[str] = None
    keyword: Optional[str] = None
    custom_message: Optional[str] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None


class ErrorMessageResponse(BaseModel):
    id: int
    error_type: Optional[str]
    keyword: Optional[str]
    custom_message: str
    priority: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TestMatchRequest(BaseModel):
    error_type: str
    error_text: str


class TestMatchResponse(BaseModel):
    matched: bool
    config_id: Optional[int] = None
    custom_message: Optional[str] = None


# ===== 辅助函数 =====

async def require_admin(user: User = Depends(get_current_user)):
    """要求管理员权限"""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


async def get_feature_enabled(db: AsyncSession) -> bool:
    """检查自定义错误消息功能是否启用"""
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.key == "custom_error_messages_enabled")
    )
    config = result.scalar_one_or_none()
    return config is not None and config.value == "true"


async def set_feature_enabled(db: AsyncSession, enabled: bool):
    """设置自定义错误消息功能开关"""
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.key == "custom_error_messages_enabled")
    )
    config = result.scalar_one_or_none()
    
    if config:
        config.value = "true" if enabled else "false"
    else:
        config = SystemConfig(
            key="custom_error_messages_enabled",
            value="true" if enabled else "false"
        )
        db.add(config)
    
    await db.commit()


# ===== API 端点 =====

@router.get("/status")
async def get_status(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """获取功能状态和错误类型列表"""
    enabled = await get_feature_enabled(db)
    
    # 错误类型对应的典型 HTTP 状态码
    ERROR_TYPE_CODES = {
        "AUTH_ERROR": "401/403",
        "RATE_LIMIT": "429",
        "QUOTA_EXHAUSTED": "429/403",
        "INVALID_REQUEST": "400",
        "MODEL_ERROR": "404",
        "CONTENT_FILTER": "400",
        "NETWORK_ERROR": "500",
        "UPSTREAM_ERROR": "500/502/503/504",
        "TIMEOUT": "超时",
        "TOKEN_ERROR": "503",
        "UNKNOWN": "其他",
    }
    
    return {
        "enabled": enabled,
        "error_types": [
            {
                "value": k, 
                "label": f"{v} ({ERROR_TYPE_CODES.get(k, '')})"
            }
            for k, v in ERROR_TYPE_NAMES.items()
        ]
    }


@router.post("/toggle")
async def toggle_feature(
    enabled: bool,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """开启/关闭自定义错误消息功能"""
    await set_feature_enabled(db, enabled)
    return {"enabled": enabled, "message": f"自定义错误消息功能已{'开启' if enabled else '关闭'}"}


@router.get("", response_model=List[ErrorMessageResponse])
async def list_error_messages(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """获取所有错误消息配置"""
    result = await db.execute(
        select(ErrorMessageConfig).order_by(
            ErrorMessageConfig.priority.desc(),
            ErrorMessageConfig.id.asc()
        )
    )
    return result.scalars().all()


@router.post("", response_model=ErrorMessageResponse)
async def create_error_message(
    data: ErrorMessageCreate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """创建错误消息配置"""
    if not data.error_type and not data.keyword:
        raise HTTPException(status_code=400, detail="error_type 和 keyword 至少需要填写一个")
    
    config = ErrorMessageConfig(
        error_type=data.error_type,
        keyword=data.keyword,
        custom_message=data.custom_message,
        priority=data.priority,
        is_active=data.is_active
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return config


@router.put("/{config_id}", response_model=ErrorMessageResponse)
async def update_error_message(
    config_id: int,
    data: ErrorMessageUpdate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """更新错误消息配置"""
    result = await db.execute(
        select(ErrorMessageConfig).where(ErrorMessageConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")
    
    if data.error_type is not None:
        config.error_type = data.error_type
    if data.keyword is not None:
        config.keyword = data.keyword
    if data.custom_message is not None:
        config.custom_message = data.custom_message
    if data.priority is not None:
        config.priority = data.priority
    if data.is_active is not None:
        config.is_active = data.is_active
    
    await db.commit()
    await db.refresh(config)
    return config


@router.delete("/{config_id}")
async def delete_error_message(
    config_id: int,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """删除错误消息配置"""
    result = await db.execute(
        select(ErrorMessageConfig).where(ErrorMessageConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")
    
    await db.delete(config)
    await db.commit()
    return {"message": "删除成功"}


@router.post("/test", response_model=TestMatchResponse)
async def test_match(
    data: TestMatchRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """测试错误匹配
    
    输入错误类型和错误文本，返回匹配的自定义消息（如果有）
    """
    from app.services.error_message_service import get_custom_error_message
    
    result = await get_custom_error_message(db, data.error_type, data.error_text)
    
    if result:
        return TestMatchResponse(
            matched=True,
            config_id=result["id"],
            custom_message=result["message"]
        )
    return TestMatchResponse(matched=False)
