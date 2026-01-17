from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, delete, or_
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, date, timedelta

from app.database import get_db
from app.models.user import User, APIKey, UsageLog, Credential
from app.services.auth import get_current_admin, get_password_hash
from app.services.credential_pool import CredentialPool
from app.services.websocket import notify_user_update, notify_credential_update
from app.services.error_classifier import ErrorType, ERROR_TYPE_NAMES, get_error_type_name

router = APIRouter(prefix="/api/admin", tags=["管理后台"])


# ===== 用户管理 =====
class UserUpdate(BaseModel):
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None
    daily_quota: Optional[int] = None
    quota_flash: Optional[int] = None
    quota_25pro: Optional[int] = None
    quota_30pro: Optional[int] = None


class UserPasswordUpdate(BaseModel):
    new_password: str


@router.get("/users")
async def list_users(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """获取所有用户（优化版：批量查询）"""
    from app.config import settings
    
    # 1. 获取所有用户
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    
    if not users:
        return {"users": [], "total": 0}
    
    user_ids = [u.id for u in users]
    today = date.today()
    
    # 2. 批量查询今日使用量
    usage_result = await db.execute(
        select(UsageLog.user_id, func.count(UsageLog.id))
        .where(UsageLog.user_id.in_(user_ids))
        .where(func.date(UsageLog.created_at) == today)
        .group_by(UsageLog.user_id)
    )
    usage_map = {row[0]: row[1] for row in usage_result.fetchall()}
    
    # 3. 批量查询凭证数量
    cred_result = await db.execute(
        select(Credential.user_id, func.count(Credential.id))
        .where(Credential.user_id.in_(user_ids))
        .where(Credential.is_active == True)
        .group_by(Credential.user_id)
    )
    cred_map = {row[0]: row[1] for row in cred_result.fetchall()}
    
    # 3.5 批量查询3.0凭证数量
    from sqlalchemy import case
    cred_30_result = await db.execute(
        select(Credential.user_id, func.count(Credential.id))
        .where(Credential.user_id.in_(user_ids))
        .where(Credential.is_active == True)
        .where(Credential.model_tier == "3")
        .group_by(Credential.user_id)
    )
    cred_30_map = {row[0]: row[1] for row in cred_30_result.fetchall()}
    
    # 4. 构建用户列表
    user_list = []
    for u in users:
        today_usage = usage_map.get(u.id, 0)
        credential_count = cred_map.get(u.id, 0)
        cred_30_count = cred_30_map.get(u.id, 0)
        
        # 计算真实配额
        if u.quota_flash and u.quota_flash > 0:
            quota_flash = u.quota_flash
        elif credential_count > 0:
            quota_flash = credential_count * settings.quota_flash
        else:
            quota_flash = settings.no_cred_quota_flash
        
        if u.quota_25pro and u.quota_25pro > 0:
            quota_25pro = u.quota_25pro
        elif credential_count > 0:
            quota_25pro = credential_count * settings.quota_25pro
        else:
            quota_25pro = settings.no_cred_quota_25pro
        
        if u.quota_30pro and u.quota_30pro > 0:
            quota_30pro = u.quota_30pro
        elif cred_30_count > 0:
            quota_30pro = cred_30_count * settings.quota_30pro
        elif credential_count > 0:
            quota_30pro = settings.cred25_quota_30pro
        else:
            quota_30pro = settings.no_cred_quota_30pro
        
        total_quota = quota_flash + quota_25pro + quota_30pro
        
        user_list.append({
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "is_active": u.is_active,
            "is_admin": u.is_admin,
            "daily_quota": total_quota,
            "quota_flash": quota_flash,
            "quota_25pro": quota_25pro,
            "quota_30pro": quota_30pro,
            "today_usage": today_usage,
            "credential_count": credential_count,
            "discord_id": u.discord_id,
            "discord_name": u.discord_name,
            "created_at": u.created_at
        })
    
    return {"users": user_list, "total": len(user_list)}


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    data: UserUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """更新用户"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.is_admin is not None:
        user.is_admin = data.is_admin
    if data.daily_quota is not None:
        user.daily_quota = data.daily_quota
    if data.quota_flash is not None:
        user.quota_flash = data.quota_flash
    if data.quota_25pro is not None:
        user.quota_25pro = data.quota_25pro
    if data.quota_30pro is not None:
        user.quota_30pro = data.quota_30pro
    
    await db.commit()
    await notify_user_update()
    return {"message": "更新成功"}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """删除用户（同时删除其关联的凭证）"""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # 先删除用户的凭证（解除使用记录的外键引用）
    user_cred_result = await db.execute(
        select(Credential.id).where(Credential.user_id == user_id)
    )
    user_cred_ids = [row[0] for row in user_cred_result.fetchall()]
    if user_cred_ids:
        await db.execute(
            update(UsageLog).where(UsageLog.credential_id.in_(user_cred_ids)).values(credential_id=None)
        )
        await db.execute(
            delete(Credential).where(Credential.user_id == user_id)
        )
    
    await db.delete(user)
    await db.commit()
    await notify_user_update()
    await notify_credential_update()
    return {"message": "删除成功（已同时删除关联凭证）"}


@router.put("/users/{user_id}/password")
async def update_user_password(
    user_id: int,
    data: UserPasswordUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """管理员修改用户密码"""
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少6位")
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    user.hashed_password = get_password_hash(data.new_password)
    await db.commit()
    return {"message": f"用户 {user.username} 的密码已重置"}


# ===== 凭证管理 =====
class CredentialCreate(BaseModel):
    name: str
    api_key: str


class CredentialUpdate(BaseModel):
    name: Optional[str] = None
    api_key: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/credentials")
async def list_credentials(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """获取所有凭证"""
    from datetime import datetime, timedelta
    from app.config import settings
    
    credentials = await CredentialPool.get_all_credentials(db)
    now = datetime.utcnow()
    
    def get_cd_remaining(last_used, cd_seconds):
        if not last_used or cd_seconds <= 0:
            return 0
        cd_end = last_used + timedelta(seconds=cd_seconds)
        remaining = (cd_end - now).total_seconds()
        return max(0, int(remaining))
    
    return {
        "credentials": [
            {
                "id": c.id,
                "name": c.name,
                "email": c.email,
                "api_key": c.api_key[:20] + "..." if c.api_key and len(c.api_key) > 20 else (c.api_key or ""),
                "api_type": c.api_type or "geminicli",  # 默认为geminicli
                "model_tier": c.model_tier,
                "is_active": c.is_active,
                "total_requests": c.total_requests or 0,
                "failed_requests": c.failed_requests or 0,
                "last_used_at": (c.last_used_at.isoformat() + "Z") if c.last_used_at else None,
                "last_error": c.last_error,
                "created_at": (c.created_at.isoformat() + "Z") if c.created_at else None,
                "cd_flash": get_cd_remaining(c.last_used_flash, settings.cd_flash),
                "cd_pro": get_cd_remaining(c.last_used_pro, settings.cd_pro),
                "cd_30": get_cd_remaining(c.last_used_30, settings.cd_30),
            }
            for c in credentials
        ],
        "total": len(credentials)
    }


@router.post("/credentials")
async def add_credential(
    data: CredentialCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """添加凭证"""
    credential = await CredentialPool.add_credential(db, data.name, data.api_key)
    await notify_credential_update()
    return {"message": "添加成功", "id": credential.id}


@router.put("/credentials/{credential_id}")
async def update_credential(
    credential_id: int,
    data: CredentialUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """更新凭证"""
    result = await db.execute(select(Credential).where(Credential.id == credential_id))
    credential = result.scalar_one_or_none()
    if not credential:
        raise HTTPException(status_code=404, detail="凭证不存在")
    
    if data.name is not None:
        credential.name = data.name
    if data.api_key is not None:
        credential.api_key = data.api_key
    if data.is_active is not None:
        credential.is_active = data.is_active
    
    await db.commit()
    await notify_credential_update()
    return {"message": "更新成功"}


@router.delete("/credentials/{credential_id}")
async def delete_credential(
    credential_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """删除凭证"""
    result = await db.execute(select(Credential).where(Credential.id == credential_id))
    credential = result.scalar_one_or_none()
    if not credential:
        raise HTTPException(status_code=404, detail="凭证不存在")
    
    # 先解除使用记录的外键引用，避免外键约束导致删除失败
    await db.execute(
        update(UsageLog).where(UsageLog.credential_id == credential_id).values(credential_id=None)
    )
    await db.delete(credential)
    await db.commit()
    await notify_credential_update()
    return {"message": "删除成功"}


@router.get("/credentials/{credential_id}/detail")
async def get_credential_detail(
    credential_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """查看凭证详情（解密后返回，用于debug）"""
    from app.services.crypto import decrypt_credential
    
    result = await db.execute(
        select(Credential, User.username)
        .outerjoin(User, Credential.user_id == User.id)
        .where(Credential.id == credential_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="凭证不存在")
    
    c = row[0]
    username = row[1]
    
    return {
        "id": c.id,
        "email": c.email,
        "name": c.name,
        "username": username,
        "credential_type": c.credential_type,
        "refresh_token": decrypt_credential(c.refresh_token) if c.refresh_token else None,
        "access_token": decrypt_credential(c.api_key) if c.api_key else None,
        "client_id": decrypt_credential(c.client_id) if c.client_id else None,
        "client_secret": decrypt_credential(c.client_secret) if c.client_secret else None,
        "project_id": c.project_id,
        "model_tier": c.model_tier,
        "account_type": c.account_type,
        "is_active": c.is_active,
        "is_public": c.is_public,
        "total_requests": c.total_requests,
        "failed_requests": c.failed_requests,
        "last_used_at": c.last_used_at.isoformat() + "Z" if c.last_used_at else None,
        "last_error": c.last_error,
        "created_at": c.created_at.isoformat() + "Z" if c.created_at else None
    }


@router.get("/credentials/export")
async def export_all_credentials(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """导出所有凭证（包含 refresh_token，解密后导出）"""
    from app.services.crypto import decrypt_credential
    
    try:
        # 关联查询用户名
        result = await db.execute(
            select(Credential, User.username)
            .outerjoin(User, Credential.user_id == User.id)
            .order_by(Credential.created_at.desc())
        )
        rows = result.all()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")
    
    export_data = []
    for row in rows:
        try:
            c = row[0]  # Credential
            username = row[1]  # username (可能为 None)
            
            # 安全获取属性，避免 AttributeError
            cred_data = {
                "id": getattr(c, 'id', None),
                "email": getattr(c, 'email', None),
                "name": getattr(c, 'name', None),
                "username": username,
                "project_id": getattr(c, 'project_id', None),
                "model_tier": getattr(c, 'model_tier', None),
                "is_active": getattr(c, 'is_active', None),
                "is_public": getattr(c, 'is_public', None),
                "user_id": getattr(c, 'user_id', None),
                "created_at": c.created_at.isoformat() if getattr(c, 'created_at', None) else None
            }
            
            # 解密敏感字段
            try:
                cred_data["refresh_token"] = decrypt_credential(c.refresh_token) if getattr(c, 'refresh_token', None) else None
                cred_data["access_token"] = decrypt_credential(c.api_key) if getattr(c, 'api_key', None) else None
                cred_data["client_id"] = decrypt_credential(c.client_id) if getattr(c, 'client_id', None) else None
                cred_data["client_secret"] = decrypt_credential(c.client_secret) if getattr(c, 'client_secret', None) else None
            except Exception as decrypt_err:
                cred_data["decrypt_error"] = str(decrypt_err)[:100]
            
            export_data.append(cred_data)
        except Exception as e:
            # 单条凭证处理失败不影响其他
            export_data.append({
                "error": f"处理失败: {str(e)[:100]}",
                "row_index": rows.index(row)
            })
    
    return export_data


@router.get("/credential-duplicates")
async def check_duplicate_credentials(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """检测重复凭证（相同邮箱或相同refresh_token）"""
    from app.services.crypto import decrypt_credential
    from collections import defaultdict
    
    # 获取所有凭证
    result = await db.execute(
        select(Credential, User.username)
        .outerjoin(User, Credential.user_id == User.id)
        .order_by(Credential.created_at.asc())
    )
    rows = result.all()
    
    # 按邮箱分组
    email_groups = defaultdict(list)
    # 按 refresh_token 分组
    token_groups = defaultdict(list)
    
    for row in rows:
        c = row[0]
        username = row[1]
        
        cred_info = {
            "id": c.id,
            "email": c.email,
            "name": c.name,
            "username": username or "系统",
            "user_id": c.user_id,
            "is_active": c.is_active,
            "is_public": c.is_public,
            "model_tier": c.model_tier,
            "total_requests": c.total_requests,
            "created_at": c.created_at.isoformat() if c.created_at else None
        }
        
        # 按邮箱分组
        if c.email:
            email_groups[c.email].append(cred_info)
        
        # 按 refresh_token 分组（解密后比较）
        if c.refresh_token:
            try:
                token = decrypt_credential(c.refresh_token)
                # 只取前50字符作为key，避免太长
                token_key = token[:50] if token else None
                if token_key:
                    token_groups[token_key].append(cred_info)
            except:
                pass
    
    # 找出重复的
    duplicate_emails = {k: v for k, v in email_groups.items() if len(v) > 1}
    duplicate_tokens = {k: v for k, v in token_groups.items() if len(v) > 1}
    
    # 合并结果，去重
    all_duplicate_ids = set()
    duplicates = []
    
    for email, creds in duplicate_emails.items():
        for cred in creds:
            if cred["id"] not in all_duplicate_ids:
                all_duplicate_ids.add(cred["id"])
        duplicates.append({
            "type": "email",
            "key": email,
            "credentials": creds
        })
    
    for token_key, creds in duplicate_tokens.items():
        # 检查是否已经被邮箱重复覆盖
        ids = [c["id"] for c in creds]
        if not all(id in all_duplicate_ids for id in ids):
            for cred in creds:
                all_duplicate_ids.add(cred["id"])
            duplicates.append({
                "type": "token",
                "key": f"{token_key[:20]}...",
                "credentials": creds
            })
    
    return {
        "total_credentials": len(rows),
        "duplicate_count": len(all_duplicate_ids),
        "duplicates": duplicates
    }


@router.delete("/credential-duplicates")
async def delete_duplicate_credentials(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """删除重复凭证（优先保留有效凭证，如果都有效或都无效则保留最早的）"""
    from app.services.crypto import decrypt_credential
    from collections import defaultdict
    
    # 获取所有凭证，按创建时间升序
    result = await db.execute(
        select(Credential).order_by(Credential.created_at.asc())
    )
    credentials = result.scalars().all()
    
    # 按邮箱分组（存储完整凭证对象以便判断is_active）
    email_groups = defaultdict(list)
    # 按 refresh_token 分组
    token_groups = defaultdict(list)
    
    for c in credentials:
        # 按邮箱分组
        if c.email:
            email_groups[c.email].append(c)
        
        # 按 refresh_token 分组
        if c.refresh_token:
            try:
                token = decrypt_credential(c.refresh_token)
                token_key = token[:50] if token else None
                if token_key:
                    token_groups[token_key].append(c)
            except:
                pass
    
    def select_best_credential(creds):
        """选择最佳凭证：优先有效的，其次最早的"""
        # 分离有效和无效凭证
        active_creds = [c for c in creds if c.is_active]
        if active_creds:
            # 有有效凭证，保留最早的有效凭证
            return active_creds[0].id
        else:
            # 都无效，保留最早的
            return creds[0].id
    
    # 找出需要删除的ID
    ids_to_delete = set()
    ids_to_keep = set()
    
    for email, creds in email_groups.items():
        if len(creds) > 1:
            keep_id = select_best_credential(creds)
            ids_to_keep.add(keep_id)
            for c in creds:
                if c.id != keep_id:
                    ids_to_delete.add(c.id)
    
    for token_key, creds in token_groups.items():
        if len(creds) > 1:
            keep_id = select_best_credential(creds)
            ids_to_keep.add(keep_id)
            for c in creds:
                if c.id != keep_id and c.id not in ids_to_keep:
                    ids_to_delete.add(c.id)
    
    if not ids_to_delete:
        return {"deleted_count": 0, "message": "没有需要删除的重复凭证"}
    
    # 先解除使用记录的外键引用，避免外键约束导致删除失败
    await db.execute(
        update(UsageLog).where(UsageLog.credential_id.in_(ids_to_delete)).values(credential_id=None)
    )
    # 批量删除
    await db.execute(
        delete(Credential).where(Credential.id.in_(ids_to_delete))
    )
    await db.commit()
    
    return {
        "deleted_count": len(ids_to_delete),
        "message": f"已删除 {len(ids_to_delete)} 个重复凭证"
    }


# ===== 统计 =====
@router.get("/stats")
async def get_stats(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """获取系统统计"""
    # 用户数
    user_count = (await db.execute(select(func.count(User.id)))).scalar() or 0
    
    # 凭证数
    credential_count = (await db.execute(select(func.count(Credential.id)))).scalar() or 0
    active_credential_count = (await db.execute(
        select(func.count(Credential.id)).where(Credential.is_active == True)
    )).scalar() or 0
    
    # 今日请求数
    today = date.today()
    today_requests = (await db.execute(
        select(func.count(UsageLog.id)).where(func.date(UsageLog.created_at) == today)
    )).scalar() or 0
    
    # 总请求数
    total_requests = (await db.execute(select(func.count(UsageLog.id)))).scalar() or 0
    
    # 最近7天请求趋势
    daily_stats = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        count = (await db.execute(
            select(func.count(UsageLog.id)).where(func.date(UsageLog.created_at) == day)
        )).scalar() or 0
        daily_stats.append({"date": day.isoformat(), "count": count})
    
    return {
        "user_count": user_count,
        "credential_count": credential_count,
        "active_credential_count": active_credential_count,
        "today_requests": today_requests,
        "total_requests": total_requests,
        "daily_stats": daily_stats
    }


@router.get("/logs")
async def get_logs(
    limit: int = 100,
    page: int = 1,
    start_date: str = None,  # YYYY-MM-DD
    end_date: str = None,    # YYYY-MM-DD
    username: str = None,
    model: str = None,
    status: str = None,      # success, error, all
    error_type: str = None,  # 按错误类型筛选
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """获取使用日志（支持分页和筛选）"""
    from datetime import datetime
    
    query = select(UsageLog, User.username).join(User, UsageLog.user_id == User.id)
    count_query = select(func.count(UsageLog.id)).select_from(UsageLog).join(User, UsageLog.user_id == User.id)
    
    # 时间范围筛选
    if start_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            query = query.where(UsageLog.created_at >= start_dt)
            count_query = count_query.where(UsageLog.created_at >= start_dt)
        except: pass
    
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            query = query.where(UsageLog.created_at < end_dt)
            count_query = count_query.where(UsageLog.created_at < end_dt)
        except: pass
    
    # 用户名筛选
    if username:
        query = query.where(User.username.ilike(f"%{username}%"))
        count_query = count_query.where(User.username.ilike(f"%{username}%"))
    
    # 模型筛选
    if model:
        query = query.where(UsageLog.model.ilike(f"%{model}%"))
        count_query = count_query.where(UsageLog.model.ilike(f"%{model}%"))
    
    # 状态筛选
    if status == "success":
        query = query.where(UsageLog.status_code == 200)
        count_query = count_query.where(UsageLog.status_code == 200)
    elif status == "error":
        query = query.where(UsageLog.status_code != 200)
        count_query = count_query.where(UsageLog.status_code != 200)
    
    # 错误类型筛选
    if error_type:
        query = query.where(UsageLog.error_type == error_type)
        count_query = count_query.where(UsageLog.error_type == error_type)
    
    # 获取总数
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # 分页
    offset = (page - 1) * limit
    query = query.order_by(UsageLog.created_at.desc()).offset(offset).limit(limit)
    
    result = await db.execute(query)
    logs = result.all()
    
    return {
        "logs": [
            {
                "id": log.UsageLog.id,
                "username": log.username,
                "model": log.UsageLog.model,
                "endpoint": log.UsageLog.endpoint,
                "status_code": log.UsageLog.status_code,
                "error_type": log.UsageLog.error_type,
                "error_type_name": get_error_type_name(log.UsageLog.error_type) if log.UsageLog.error_type else None,
                "error_code": log.UsageLog.error_code,
                "credential_email": log.UsageLog.credential_email,
                "latency_ms": log.UsageLog.latency_ms,
                "cd_seconds": log.UsageLog.cd_seconds,
                "created_at": log.UsageLog.created_at.isoformat() + "Z"
            }
            for log in logs
        ],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if limit > 0 else 1
    }


@router.get("/logs/{log_id}/detail")
async def get_log_detail(
    log_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """获取单条日志详情（包含完整错误信息）"""
    result = await db.execute(
        select(UsageLog, User.username, Credential.email.label("cred_email"))
        .join(User, UsageLog.user_id == User.id)
        .outerjoin(Credential, UsageLog.credential_id == Credential.id)
        .where(UsageLog.id == log_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="日志不存在")
    
    log = row.UsageLog
    username = row.username
    cred_email = row.cred_email
    
    return {
        "id": log.id,
        "username": username,
        "credential_id": log.credential_id,
        "credential_email": cred_email or log.credential_email,
        "model": log.model,
        "endpoint": log.endpoint,
        "status_code": log.status_code,
        "error_type": log.error_type,
        "error_type_name": get_error_type_name(log.error_type) if log.error_type else None,
        "error_code": log.error_code,
        "error_message": log.error_message,  # 完整错误信息
        "request_body": log.request_body,
        "client_ip": log.client_ip,
        "user_agent": log.user_agent,
        "latency_ms": log.latency_ms,
        "cd_seconds": log.cd_seconds,
        "created_at": log.created_at.isoformat() + "Z"
    }


@router.delete("/logs")
async def clear_logs(
    before_date: str = None,  # YYYY-MM-DD, 清除此日期之前的日志
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """清除使用日志（支持按日期清除或全部清除）"""
    query = delete(UsageLog)
    
    if before_date:
        try:
            cutoff = datetime.strptime(before_date, "%Y-%m-%d")
            query = query.where(UsageLog.created_at < cutoff)
            result = await db.execute(query)
            deleted_count = result.rowcount
            await db.commit()
            return {"message": f"已清除 {before_date} 之前的 {deleted_count} 条日志"}
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式无效，应为 YYYY-MM-DD")
    else:
        # 清除所有日志
        result = await db.execute(query)
        deleted_count = result.rowcount
        await db.commit()
        return {"message": f"已清除所有日志，共 {deleted_count} 条"}


@router.get("/error-stats")
async def get_error_stats(
    days: int = 7,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """报错统计分析"""
    start_date = date.today() - timedelta(days=days-1)
    
    # 1. 按错误类型统计
    type_stats_result = await db.execute(
        select(
            UsageLog.error_type,
            func.count(UsageLog.id).label("count")
        )
        .where(func.date(UsageLog.created_at) >= start_date)
        .where(UsageLog.status_code != 200)
        .where(UsageLog.error_type != None)
        .group_by(UsageLog.error_type)
        .order_by(func.count(UsageLog.id).desc())
    )
    type_stats = [
        {
            "type": row[0],
            "type_name": get_error_type_name(row[0]),
            "count": row[1]
        }
        for row in type_stats_result.fetchall()
    ]
    
    # 2. 按凭证统计（问题凭证排行）
    cred_stats_result = await db.execute(
        select(
            Credential.email,
            Credential.id,
            func.count(UsageLog.id).filter(UsageLog.status_code != 200).label("error_count"),
            func.count(UsageLog.id).filter(UsageLog.status_code == 200).label("success_count")
        )
        .join(Credential, UsageLog.credential_id == Credential.id)
        .where(func.date(UsageLog.created_at) >= start_date)
        .group_by(Credential.email, Credential.id)
        .having(func.count(UsageLog.id).filter(UsageLog.status_code != 200) > 0)
        .order_by(func.count(UsageLog.id).filter(UsageLog.status_code != 200).desc())
        .limit(10)
    )
    cred_stats = []
    for row in cred_stats_result.fetchall():
        total = row[2] + row[3]
        error_rate = round(row[2] / total * 100, 1) if total > 0 else 0
        cred_stats.append({
            "credential_id": row[1],
            "email": row[0],
            "errors": row[2],
            "successes": row[3],
            "error_rate": error_rate
        })
    
    # 3. 按状态码统计
    code_stats_result = await db.execute(
        select(
            UsageLog.status_code,
            func.count(UsageLog.id).label("count")
        )
        .where(func.date(UsageLog.created_at) >= start_date)
        .where(UsageLog.status_code != 200)
        .group_by(UsageLog.status_code)
        .order_by(func.count(UsageLog.id).desc())
    )
    code_stats = [{"code": row[0], "count": row[1]} for row in code_stats_result.fetchall()]
    
    # 4. 按日期的错误趋势
    daily_trend = []
    for i in range(days-1, -1, -1):
        day = date.today() - timedelta(days=i)
        
        # 当天总请求数
        total_result = await db.execute(
            select(func.count(UsageLog.id))
            .where(func.date(UsageLog.created_at) == day)
        )
        total = total_result.scalar() or 0
        
        # 当天错误数
        error_result = await db.execute(
            select(func.count(UsageLog.id))
            .where(func.date(UsageLog.created_at) == day)
            .where(UsageLog.status_code != 200)
        )
        errors = error_result.scalar() or 0
        
        daily_trend.append({
            "date": day.isoformat(),
            "total": total,
            "errors": errors,
            "error_rate": round(errors / total * 100, 1) if total > 0 else 0
        })
    
    # 5. 今日概况
    today = date.today()
    today_total_result = await db.execute(
        select(func.count(UsageLog.id))
        .where(func.date(UsageLog.created_at) == today)
    )
    today_total = today_total_result.scalar() or 0
    
    today_errors_result = await db.execute(
        select(func.count(UsageLog.id))
        .where(func.date(UsageLog.created_at) == today)
        .where(UsageLog.status_code != 200)
    )
    today_errors = today_errors_result.scalar() or 0
    
    return {
        "period_days": days,
        "today_total": today_total,
        "today_errors": today_errors,
        "today_error_rate": round(today_errors / today_total * 100, 1) if today_total > 0 else 0,
        "by_type": type_stats,
        "by_status_code": code_stats,
        "by_credential": cred_stats,
        "daily_trend": daily_trend,
        "error_types": ERROR_TYPE_NAMES  # 返回错误类型枚举供前端使用
    }


# ===== 配额设置 =====
class QuotaUpdate(BaseModel):
    quota: int


@router.post("/settings/default-quota")
async def set_default_quota(
    data: QuotaUpdate,
    admin: User = Depends(get_current_admin)
):
    """设置新用户默认配额"""
    from app.config import settings
    settings.default_daily_quota = data.quota
    return {"message": "默认配额已更新", "quota": data.quota}


@router.post("/settings/batch-quota")
async def batch_update_quota(
    data: QuotaUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """批量更新所有用户配额"""
    await db.execute(
        update(User).values(daily_quota=data.quota)
    )
    await db.commit()
    await notify_user_update()
    return {"message": f"已将所有用户配额设为 {data.quota}"}
