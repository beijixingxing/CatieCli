"""
Antigravity 凭证管理路由
独立的凭证管理系统，与 GeminiCLI 凭证完全分离
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from typing import List, Optional
from datetime import datetime, timedelta
import json
import io
import zipfile

from app.database import get_db
from app.models.user import User, Credential, UsageLog
from app.services.auth import get_current_user, get_current_admin
from app.services.crypto import encrypt_credential, decrypt_credential
from app.services.credential_pool import (
    CredentialPool, 
    fetch_project_id,
    ANTIGRAVITY_USER_AGENT
)
from app.config import settings


router = APIRouter(prefix="/api/antigravity", tags=["Antigravity凭证管理"])

# 凭证类型常量
MODE = "antigravity"


# ===== 用户凭证管理 =====

@router.post("/credentials/upload")
async def upload_antigravity_credentials(
    files: List[UploadFile] = File(...),
    is_public: bool = Form(default=False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    上传 Antigravity JSON 凭证文件（支持多文件和ZIP压缩包）
    
    凭证会使用 Antigravity User-Agent 获取 project_id
    """
    if not files:
        raise HTTPException(status_code=400, detail="请选择要上传的文件")
    
    # 强制捐赠模式
    if settings.force_donate:
        is_public = True
    
    results = []
    success_count = 0
    
    # 预处理：解压ZIP文件，收集所有JSON文件
    json_files = []  # [(filename, content_bytes), ...]
    
    for file in files:
        if file.filename.endswith('.zip'):
            try:
                zip_content = await file.read()
                with zipfile.ZipFile(io.BytesIO(zip_content), 'r') as zf:
                    for name in zf.namelist():
                        if name.endswith('.json') and not name.startswith('__MACOSX'):
                            json_files.append((name, zf.read(name)))
                results.append({
                    "filename": file.filename, 
                    "status": "info", 
                    "message": f"已解压 {len([n for n in zf.namelist() if n.endswith('.json')])} 个JSON文件"
                })
            except zipfile.BadZipFile:
                results.append({"filename": file.filename, "status": "error", "message": "无效的ZIP文件"})
            except Exception as e:
                results.append({"filename": file.filename, "status": "error", "message": f"解压失败: {str(e)[:50]}"})
        elif file.filename.endswith('.json'):
            content = await file.read()
            json_files.append((file.filename, content))
        else:
            results.append({"filename": file.filename, "status": "error", "message": "只支持 JSON 或 ZIP 文件"})
    
    # 处理所有JSON文件
    for filename, content in json_files:
        try:
            cred_data = json.loads(content.decode('utf-8') if isinstance(content, bytes) else content)
            
            # 验证必要字段
            required_fields = ["refresh_token"]
            missing = [f for f in required_fields if f not in cred_data]
            if missing:
                results.append({"filename": filename, "status": "error", "message": f"缺少字段: {', '.join(missing)}"})
                continue
            
            # 创建凭证（加密存储）
            email = cred_data.get("email") or filename
            refresh_token = cred_data.get("refresh_token")
            
            # 去重检查：根据 email 判断是否已存在（仅在 antigravity 凭证中）
            existing = await db.execute(
                select(Credential)
                .where(Credential.email == email)
                .where(Credential.api_type == MODE)
            )
            if existing.scalar_one_or_none():
                results.append({"filename": filename, "status": "skip", "message": f"凭证已存在: {email}"})
                continue
            
            # 也检查 refresh_token 是否重复
            encrypted_token = encrypt_credential(refresh_token)
            existing_token = await db.execute(
                select(Credential)
                .where(Credential.refresh_token == encrypted_token)
                .where(Credential.api_type == MODE)
            )
            if existing_token.scalar_one_or_none():
                results.append({"filename": filename, "status": "skip", "message": f"凭证token已存在: {email}"})
                continue
            
            # 获取 access_token 并验证
            is_valid = False
            project_id = cred_data.get("project_id", "")
            verify_msg = ""
            
            try:
                import httpx
                
                # 创建临时凭证对象用于获取 token
                temp_cred = Credential(
                    api_key=encrypt_credential(cred_data.get("token") or cred_data.get("access_token", "")),
                    refresh_token=encrypt_credential(refresh_token),
                    client_id=encrypt_credential(cred_data.get("client_id")) if cred_data.get("client_id") else None,
                    client_secret=encrypt_credential(cred_data.get("client_secret")) if cred_data.get("client_secret") else None,
                    credential_type="oauth"
                )
                
                access_token = await CredentialPool.get_access_token(temp_cred, db)
                if access_token:
                    # 如果没有 project_id，使用 Antigravity 方式获取
                    if not project_id:
                        print(f"[Antigravity上传] 正在获取 project_id: {email}", flush=True)
                        project_id = await fetch_project_id(
                            access_token=access_token,
                            user_agent=ANTIGRAVITY_USER_AGENT,
                            api_base_url=settings.antigravity_api_base
                        )
                        if project_id:
                            print(f"[Antigravity上传] 获取到 project_id: {project_id}", flush=True)
                    
                    # 测试 API 是否可用
                    if project_id:
                        async with httpx.AsyncClient(timeout=15) as client:
                            test_url = f"{settings.antigravity_api_base}/v1internal:generateContent"
                            headers = {
                                "Authorization": f"Bearer {access_token}", 
                                "Content-Type": "application/json",
                                "User-Agent": ANTIGRAVITY_USER_AGENT
                            }
                            test_payload = {
                                "model": "gemini-2.0-flash-exp",
                                "project": project_id,
                                "request": {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}
                            }
                            resp = await client.post(test_url, headers=headers, json=test_payload)
                            
                            if resp.status_code in [200, 429]:
                                is_valid = True
                                verify_msg = f"✅ 有效 (project: {project_id[:20]}...)"
                            else:
                                verify_msg = f"❌ API测试失败 ({resp.status_code})"
                    else:
                        verify_msg = "❌ 无法获取 project_id"
                else:
                    verify_msg = "❌ 无法获取 access_token"
            except Exception as e:
                verify_msg = f"⚠️ 验证失败: {str(e)[:30]}"
            
            # 如果要捐赠但凭证无效，不允许
            actual_public = is_public and is_valid
            
            credential = Credential(
                user_id=user.id,
                name=f"Antigravity - {email}",
                api_key=encrypt_credential(cred_data.get("token") or cred_data.get("access_token", "")),
                refresh_token=encrypt_credential(refresh_token),
                client_id=encrypt_credential(cred_data.get("client_id")) if cred_data.get("client_id") else None,
                client_secret=encrypt_credential(cred_data.get("client_secret")) if cred_data.get("client_secret") else None,
                project_id=project_id,
                credential_type="oauth",
                email=email,
                is_public=actual_public,
                is_active=is_valid,
                api_type=MODE,  # 标记为 Antigravity 凭证
                model_tier="2.5"  # Antigravity 暂时都算 2.5
            )
            db.add(credential)
            
            status_msg = f"上传成功 {verify_msg}"
            if is_public and not is_valid:
                status_msg += " (无效凭证不会上传到公共池)"
            results.append({
                "filename": filename, 
                "status": "success" if is_valid else "warning", 
                "message": status_msg
            })
            success_count += 1
            
            # 每50个凭证提交一次
            if success_count % 50 == 0:
                try:
                    await db.commit()
                    print(f"[Antigravity批量上传] 已提交 {success_count} 个凭证", flush=True)
                except Exception as commit_err:
                    print(f"[Antigravity批量上传] 提交失败: {commit_err}", flush=True)
            
        except json.JSONDecodeError:
            results.append({"filename": filename, "status": "error", "message": "JSON 格式错误"})
        except Exception as e:
            results.append({"filename": filename, "status": "error", "message": str(e)})
    
    # 最终提交
    try:
        await db.commit()
        print(f"[Antigravity批量上传] 最终提交完成，共 {success_count} 个凭证", flush=True)
    except Exception as final_err:
        print(f"[Antigravity批量上传] 最终提交失败: {final_err}", flush=True)
        try:
            await db.rollback()
            await db.commit()
        except:
            pass
    
    return {"uploaded_count": success_count, "total_count": len(json_files), "results": results}


@router.get("/credentials")
async def list_my_antigravity_credentials(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取我的 Antigravity 凭证列表"""
    result = await db.execute(
        select(Credential)
        .where(Credential.user_id == user.id)
        .where(Credential.api_type == MODE)
        .order_by(Credential.created_at.desc())
    )
    creds = result.scalars().all()
    
    now = datetime.utcnow()
    
    def get_cd_remaining(last_used, cd_seconds):
        """计算 CD 剩余秒数"""
        if not last_used or cd_seconds <= 0:
            return 0
        cd_end = last_used + timedelta(seconds=cd_seconds)
        remaining = (cd_end - now).total_seconds()
        return max(0, int(remaining))
    
    return [
        {
            "id": c.id,
            "name": c.name,
            "email": c.email,
            "project_id": c.project_id,
            "is_public": c.is_public,
            "is_active": c.is_active,
            "total_requests": c.total_requests or 0,
            "failed_requests": c.failed_requests or 0,
            "last_error": c.last_error,
            "last_used_at": (c.last_used_at.isoformat() + "Z") if c.last_used_at else None,
            "created_at": (c.created_at.isoformat() + "Z") if c.created_at else None,
            # Antigravity 暂时没有模型级 CD
            "cd_flash": 0,
            "cd_pro": 0,
            "cd_30": 0,
        }
        for c in creds
    ]


@router.patch("/credentials/{cred_id}")
async def update_my_antigravity_credential(
    cred_id: int,
    is_public: bool = None,
    is_active: bool = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """更新我的 Antigravity 凭证（公开/启用状态）"""
    result = await db.execute(
        select(Credential)
        .where(Credential.id == cred_id)
        .where(Credential.user_id == user.id)
        .where(Credential.api_type == MODE)
    )
    cred = result.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="凭证不存在")
    
    if is_public is not None:
        if is_public:
            if not cred.is_active:
                raise HTTPException(status_code=400, detail="无效凭证不能捐赠，请先检测")
            if cred.last_error and ('403' in cred.last_error or '401' in cred.last_error):
                raise HTTPException(status_code=400, detail="凭证存在认证错误，不能捐赠")
        cred.is_public = is_public
    
    if is_active is not None:
        cred.is_active = is_active
    
    await db.commit()
    return {"message": "更新成功", "is_public": cred.is_public, "is_active": cred.is_active}


@router.delete("/credentials/{cred_id}")
async def delete_my_antigravity_credential(
    cred_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """删除我的 Antigravity 凭证"""
    result = await db.execute(
        select(Credential)
        .where(Credential.id == cred_id)
        .where(Credential.user_id == user.id)
        .where(Credential.api_type == MODE)
    )
    cred = result.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="凭证不存在")
    
    # 先解除使用记录的外键引用
    await db.execute(
        update(UsageLog).where(UsageLog.credential_id == cred_id).values(credential_id=None)
    )
    await db.delete(cred)
    await db.commit()
    return {"message": "删除成功"}


@router.delete("/credentials/inactive/batch")
async def delete_my_inactive_antigravity_credentials(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """批量删除我的所有失效 Antigravity 凭证"""
    result = await db.execute(
        select(Credential).where(
            Credential.user_id == user.id,
            Credential.api_type == MODE,
            Credential.is_active == False
        )
    )
    inactive_creds = result.scalars().all()
    
    if not inactive_creds:
        return {"message": "没有失效凭证需要删除", "deleted_count": 0}
    
    cred_ids = [c.id for c in inactive_creds]
    await db.execute(
        update(UsageLog).where(UsageLog.credential_id.in_(cred_ids)).values(credential_id=None)
    )
    
    deleted_count = 0
    for cred in inactive_creds:
        await db.delete(cred)
        deleted_count += 1
        
        if deleted_count % 100 == 0:
            try:
                await db.commit()
            except Exception as e:
                print(f"[Antigravity批量删除] 提交失败: {e}", flush=True)
                await db.rollback()
    
    try:
        await db.commit()
    except Exception as e:
        print(f"[Antigravity批量删除] 最终提交失败: {e}", flush=True)
        await db.rollback()
    
    return {"message": f"已删除 {deleted_count} 个失效凭证", "deleted_count": deleted_count}


@router.post("/credentials/{cred_id}/verify")
async def verify_my_antigravity_credential(
    cred_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """验证我的 Antigravity 凭证有效性并更新 project_id"""
    import httpx
    
    try:
        result = await db.execute(
            select(Credential)
            .where(Credential.id == cred_id)
            .where(Credential.user_id == user.id)
            .where(Credential.api_type == MODE)
        )
        cred = result.scalar_one_or_none()
        if not cred:
            return {"is_valid": False, "error": "凭证不存在"}
        
        # 获取 access token
        try:
            access_token = await CredentialPool.get_access_token(cred, db)
        except Exception as e:
            cred.is_active = False
            cred.last_error = f"获取 token 异常: {str(e)[:50]}"
            await db.commit()
            return {"is_valid": False, "error": f"获取 token 异常: {str(e)[:50]}"}
        
        if not access_token:
            cred.is_active = False
            cred.last_error = "无法获取 access token"
            await db.commit()
            return {"is_valid": False, "error": "无法获取 access token"}
        
        # 使用 Antigravity 方式重新获取 project_id
        new_project_id = await fetch_project_id(
            access_token=access_token,
            user_agent=ANTIGRAVITY_USER_AGENT,
            api_base_url=settings.antigravity_api_base
        )
        
        if new_project_id:
            cred.project_id = new_project_id
            print(f"[Antigravity检测] 更新 project_id: {new_project_id}", flush=True)
        
        # 测试 API 是否可用
        is_valid = False
        error_msg = None
        
        if cred.project_id:
            async with httpx.AsyncClient(timeout=15) as client:
                test_url = f"{settings.antigravity_api_base}/v1internal:generateContent"
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "User-Agent": ANTIGRAVITY_USER_AGENT
                }
                test_payload = {
                    "model": "gemini-2.0-flash-exp",
                    "project": cred.project_id,
                    "request": {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}
                }
                
                try:
                    resp = await client.post(test_url, headers=headers, json=test_payload)
                    if resp.status_code in [200, 429]:
                        is_valid = True
                    elif resp.status_code in [401, 403]:
                        error_msg = f"认证失败 ({resp.status_code})"
                    else:
                        error_msg = f"API 返回 {resp.status_code}"
                except Exception as e:
                    error_msg = f"请求异常: {str(e)[:30]}"
        else:
            error_msg = "无 project_id"
        
        # 更新凭证状态
        cred.is_active = is_valid
        cred.last_error = error_msg if error_msg else None
        await db.commit()
        
        return {
            "is_valid": is_valid,
            "project_id": cred.project_id,
            "error": error_msg
        }
    except Exception as e:
        print(f"[Antigravity检测] 严重异常: {e}", flush=True)
        return {"is_valid": False, "error": f"检测异常: {str(e)[:50]}"}


@router.post("/credentials/{cred_id}/refresh-project-id")
async def refresh_antigravity_project_id(
    cred_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """刷新 Antigravity 凭证的 project_id"""
    try:
        result = await db.execute(
            select(Credential)
            .where(Credential.id == cred_id)
            .where(Credential.user_id == user.id)
            .where(Credential.api_type == MODE)
        )
        cred = result.scalar_one_or_none()
        if not cred:
            return {"success": False, "error": "凭证不存在", "project_id": None}
        
        # 获取 access token
        try:
            access_token = await CredentialPool.get_access_token(cred, db)
        except Exception as e:
            return {"success": False, "error": f"获取 token 失败: {str(e)[:50]}", "project_id": cred.project_id}
        
        if not access_token:
            return {"success": False, "error": "无法获取 access token", "project_id": cred.project_id}
        
        # 使用 Antigravity 方式获取 project_id
        new_project_id = await fetch_project_id(
            access_token=access_token,
            user_agent=ANTIGRAVITY_USER_AGENT,
            api_base_url=settings.antigravity_api_base
        )
        
        if not new_project_id:
            return {"success": False, "error": "无法获取 project_id", "project_id": cred.project_id}
        
        # 更新数据库
        old_project_id = cred.project_id
        cred.project_id = new_project_id
        await db.commit()
        
        return {
            "success": True,
            "project_id": new_project_id,
            "old_project_id": old_project_id,
            "message": f"项目ID已更新: {new_project_id}"
        }
        
    except Exception as e:
        return {"success": False, "error": f"刷新异常: {str(e)[:50]}", "project_id": None}


@router.get("/credentials/{cred_id}/export")
async def export_my_antigravity_credential(
    cred_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """导出我的 Antigravity 凭证为 JSON 格式"""
    result = await db.execute(
        select(Credential)
        .where(Credential.id == cred_id)
        .where(Credential.user_id == user.id)
        .where(Credential.api_type == MODE)
    )
    cred = result.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="凭证不存在")
    
    # 构建 JSON 格式
    cred_data = {
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "refresh_token": decrypt_credential(cred.refresh_token) if cred.refresh_token else "",
        "token": decrypt_credential(cred.api_key) if cred.api_key else "",
        "project_id": cred.project_id or "",
        "email": cred.email or "",
        "type": "authorized_user"
    }
    
    return cred_data


@router.get("/credentials/{cred_id}/quota")
async def get_antigravity_credential_quota(
    cred_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取 Antigravity 凭证的额度信息（各模型的剩余配额和重置时间）"""
    from datetime import timedelta
    
    result = await db.execute(
        select(Credential)
        .where(Credential.id == cred_id)
        .where(Credential.user_id == user.id)
        .where(Credential.api_type == MODE)
    )
    cred = result.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="凭证不存在")
    
    # 获取 access token
    try:
        access_token = await CredentialPool.get_access_token(cred, db)
    except Exception as e:
        return {"success": False, "error": f"获取 token 失败: {str(e)[:50]}", "models": {}}
    
    if not access_token:
        return {"success": False, "error": "无法获取 access token", "models": {}}
    
    # 使用 AntigravityClient 获取配额信息
    from app.services.antigravity_client import AntigravityClient
    client = AntigravityClient(access_token, cred.project_id)
    
    try:
        quota_result = await client.fetch_quota_info()
        
        if quota_result.get("success"):
            # 转换重置时间为北京时间格式
            models = {}
            for model_id, quota_data in quota_result.get("models", {}).items():
                remaining = quota_data.get("remaining", 0)
                reset_time_raw = quota_data.get("resetTime", "")
                
                # 转换为北京时间
                reset_time_beijing = "N/A"
                if reset_time_raw:
                    try:
                        from datetime import datetime, timezone
                        if reset_time_raw.endswith("Z"):
                            utc_date = datetime.fromisoformat(reset_time_raw.replace("Z", "+00:00"))
                        else:
                            utc_date = datetime.fromisoformat(reset_time_raw)
                        # 转换为北京时间 (UTC+8)
                        beijing_date = utc_date + timedelta(hours=8)
                        reset_time_beijing = beijing_date.strftime("%m-%d %H:%M")
                    except Exception as e:
                        print(f"[Antigravity额度] 解析重置时间失败: {e}", flush=True)
                
                models[model_id] = {
                    "remaining": round(remaining * 100, 1),  # 转换为百分比
                    "resetTime": reset_time_beijing,
                    "resetTimeRaw": reset_time_raw
                }
            
            return {
                "success": True,
                "filename": cred.email or f"credential-{cred.id}",
                "models": models
            }
        else:
            return {
                "success": False,
                "error": quota_result.get("error", "获取配额失败"),
                "models": {}
            }
    except Exception as e:
        print(f"[Antigravity额度] 异常: {e}", flush=True)
        return {"success": False, "error": f"获取配额异常: {str(e)[:50]}", "models": {}}


# ===== 管理员功能 =====

@router.get("/manage/credentials/status")
async def get_antigravity_credentials_status(
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """获取所有 Antigravity 凭证的详细状态（管理员）"""
    result = await db.execute(
        select(Credential)
        .where(Credential.api_type == MODE)
        .order_by(Credential.created_at.desc())
    )
    credentials = result.scalars().all()
    
    return {
        "total": len(credentials),
        "active": sum(1 for c in credentials if c.is_active),
        "public": sum(1 for c in credentials if c.is_public),
        "credentials": [
            {
                "id": c.id,
                "name": c.name,
                "email": c.email,
                "project_id": c.project_id,
                "is_active": c.is_active,
                "is_public": c.is_public,
                "total_requests": c.total_requests,
                "failed_requests": c.failed_requests,
                "last_used_at": (c.last_used_at.isoformat() + "Z") if c.last_used_at else None,
                "last_error": c.last_error,
                "created_at": (c.created_at.isoformat() + "Z") if c.created_at else None,
            }
            for c in credentials
        ]
    }


@router.post("/manage/credentials/batch-action")
async def batch_antigravity_credential_action(
    action: str = Form(...),
    credential_ids: str = Form(...),
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """批量操作 Antigravity 凭证（管理员）"""
    ids = [int(x.strip()) for x in credential_ids.split(",") if x.strip()]
    
    if not ids:
        raise HTTPException(status_code=400, detail="未选择凭证")
    
    # 确保只操作 Antigravity 凭证
    if action == "enable":
        await db.execute(
            update(Credential)
            .where(Credential.id.in_(ids))
            .where(Credential.api_type == MODE)
            .values(is_active=True)
        )
    elif action == "disable":
        await db.execute(
            update(Credential)
            .where(Credential.id.in_(ids))
            .where(Credential.api_type == MODE)
            .values(is_active=False)
        )
    elif action == "delete":
        result = await db.execute(
            select(Credential)
            .where(Credential.id.in_(ids))
            .where(Credential.api_type == MODE)
        )
        for cred in result.scalars().all():
            await db.execute(
                update(UsageLog).where(UsageLog.credential_id == cred.id).values(credential_id=None)
            )
            await db.delete(cred)
    else:
        raise HTTPException(status_code=400, detail="无效的操作")
    
    await db.commit()
    return {"message": f"已对 {len(ids)} 个凭证执行 {action} 操作"}


@router.delete("/manage/credentials/inactive")
async def delete_inactive_antigravity_credentials(
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """一键删除所有无效 Antigravity 凭证（管理员）"""
    result = await db.execute(
        select(Credential)
        .where(Credential.api_type == MODE)
        .where(Credential.is_active == False)
    )
    inactive_creds = result.scalars().all()
    
    if not inactive_creds:
        return {"message": "没有无效凭证", "deleted_count": 0}
    
    deleted_count = len(inactive_creds)
    cred_ids = [c.id for c in inactive_creds]
    
    await db.execute(
        update(UsageLog).where(UsageLog.credential_id.in_(cred_ids)).values(credential_id=None)
    )
    for cred in inactive_creds:
        await db.delete(cred)
    
    await db.commit()
    return {"message": f"已删除 {deleted_count} 个无效凭证", "deleted_count": deleted_count}


@router.get("/manage/credentials/export")
async def export_antigravity_credentials(
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """导出所有 Antigravity 凭证为 ZIP 文件（管理员）"""
    result = await db.execute(
        select(Credential).where(Credential.api_type == MODE)
    )
    credentials = result.scalars().all()
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for cred in credentials:
            cred_data = {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": decrypt_credential(cred.refresh_token) if cred.refresh_token else "",
                "token": decrypt_credential(cred.api_key) if cred.api_key else "",
                "project_id": cred.project_id or "",
                "email": cred.email or "",
            }
            filename = f"{cred.email or cred.id}.json"
            zf.writestr(filename, json.dumps(cred_data, indent=2))
    
    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=antigravity_credentials.zip"}
    )


@router.post("/manage/credentials/{credential_id}/toggle")
async def toggle_antigravity_credential(
    credential_id: int,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """切换 Antigravity 凭证启用/禁用状态（管理员）"""
    result = await db.execute(
        select(Credential)
        .where(Credential.id == credential_id)
        .where(Credential.api_type == MODE)
    )
    cred = result.scalar_one_or_none()
    
    if not cred:
        raise HTTPException(status_code=404, detail="凭证不存在")
    
    cred.is_active = not cred.is_active
    await db.commit()
    
    return {"message": f"凭证已{'启用' if cred.is_active else '禁用'}", "is_active": cred.is_active}


@router.post("/manage/credentials/{credential_id}/verify")
async def admin_verify_antigravity_credential(
    credential_id: int,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """验证 Antigravity 凭证有效性（管理员）"""
    import httpx
    
    result = await db.execute(
        select(Credential)
        .where(Credential.id == credential_id)
        .where(Credential.api_type == MODE)
    )
    cred = result.scalar_one_or_none()
    
    if not cred:
        raise HTTPException(status_code=404, detail="凭证不存在")
    
    # 获取 access token
    access_token = await CredentialPool.get_access_token(cred, db)
    if not access_token:
        cred.is_active = False
        cred.last_error = "无法获取 access token"
        await db.commit()
        return {"is_valid": False, "error": "无法获取 access token"}
    
    # 使用 Antigravity 方式重新获取 project_id
    new_project_id = await fetch_project_id(
        access_token=access_token,
        user_agent=ANTIGRAVITY_USER_AGENT,
        api_base_url=settings.antigravity_api_base
    )
    
    if new_project_id:
        cred.project_id = new_project_id
    
    # 测试 API
    is_valid = False
    error_msg = None
    
    if cred.project_id:
        async with httpx.AsyncClient(timeout=15) as client:
            test_url = f"{settings.antigravity_api_base}/v1internal:generateContent"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "User-Agent": ANTIGRAVITY_USER_AGENT
            }
            test_payload = {
                "model": "gemini-2.0-flash-exp",
                "project": cred.project_id,
                "request": {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}
            }
            
            try:
                resp = await client.post(test_url, headers=headers, json=test_payload)
                if resp.status_code in [200, 429]:
                    is_valid = True
                elif resp.status_code in [401, 403]:
                    error_msg = f"认证失败 ({resp.status_code})"
                else:
                    error_msg = f"API 返回 {resp.status_code}"
            except Exception as e:
                error_msg = f"请求异常: {str(e)[:30]}"
    else:
        error_msg = "无 project_id"
    
    cred.is_active = is_valid
    cred.last_error = error_msg if error_msg else None
    await db.commit()
    
    return {
        "is_valid": is_valid,
        "project_id": cred.project_id,
        "error": error_msg
    }


@router.post("/manage/credentials/verify-all")
async def verify_all_antigravity_credentials(
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """一键检测所有 Antigravity 凭证（后台任务，立即返回）"""
    import asyncio
    import httpx
    from app.database import async_session
    
    result = await db.execute(
        select(Credential).where(Credential.api_type == MODE)
    )
    creds = result.scalars().all()
    total = len(creds)
    
    # 提取凭证数据
    cred_data = [{
        "id": c.id,
        "email": c.email,
        "refresh_token": c.refresh_token,
        "client_id": c.client_id,
        "client_secret": c.client_secret,
        "project_id": c.project_id,
        "api_key": c.api_key,
    } for c in creds]
    
    task_id = f"antigravity_verify_{datetime.utcnow().timestamp()}"
    
    async def run_in_background():
        """后台执行检测"""
        semaphore = asyncio.Semaphore(30)  # 限制并发
        valid = 0
        invalid = 0
        
        async def verify_single(data):
            nonlocal valid, invalid
            async with semaphore:
                try:
                    # 获取 access_token
                    temp_cred = Credential(
                        id=data["id"],
                        refresh_token=data["refresh_token"],
                        client_id=data["client_id"],
                        client_secret=data["client_secret"],
                        project_id=data["project_id"],
                        api_key=data["api_key"],
                        credential_type="oauth"
                    )
                    access_token = await CredentialPool.refresh_access_token(temp_cred) if temp_cred.refresh_token else None
                    if not access_token:
                        return {"id": data["id"], "is_valid": False}
                    
                    # 获取 project_id
                    project_id = data["project_id"]
                    if not project_id:
                        project_id = await fetch_project_id(
                            access_token=access_token,
                            user_agent=ANTIGRAVITY_USER_AGENT,
                            api_base_url=settings.antigravity_api_base
                        )
                    
                    is_valid = False
                    if project_id:
                        async with httpx.AsyncClient(timeout=10) as client:
                            test_url = f"{settings.antigravity_api_base}/v1internal:generateContent"
                            headers = {
                                "Authorization": f"Bearer {access_token}",
                                "Content-Type": "application/json",
                                "User-Agent": ANTIGRAVITY_USER_AGENT
                            }
                            test_payload = {
                                "model": "gemini-2.0-flash-exp",
                                "project": project_id,
                                "request": {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}
                            }
                            resp = await client.post(test_url, headers=headers, json=test_payload)
                            is_valid = resp.status_code in [200, 429]
                    
                    return {"id": data["id"], "is_valid": is_valid, "project_id": project_id, "token": access_token}
                except Exception as e:
                    print(f"[Antigravity检测] ❌ {data['email']} 异常: {e}", flush=True)
                    return {"id": data["id"], "is_valid": False}
        
        print(f"[Antigravity检测] 后台开始检测 {total} 个凭证...", flush=True)
        results = await asyncio.gather(*[verify_single(d) for d in cred_data])
        
        # 批量更新数据库
        async with async_session() as session:
            for res in results:
                update_vals = {"is_active": res["is_valid"]}
                if res.get("project_id"):
                    update_vals["project_id"] = res["project_id"]
                if res.get("token"):
                    update_vals["api_key"] = encrypt_credential(res["token"])
                
                await session.execute(
                    update(Credential).where(Credential.id == res["id"]).values(**update_vals)
                )
                
                if res["is_valid"]:
                    valid += 1
                else:
                    invalid += 1
            
            await session.commit()
        
        print(f"[Antigravity检测] 完成: 有效 {valid}, 无效 {invalid}", flush=True)
    
    asyncio.create_task(run_in_background())
    
    return {"message": "后台任务已启动", "task_id": task_id, "total": total}


@router.post("/manage/credentials/start-all")
async def start_all_antigravity_credentials(
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """一键启动所有 Antigravity 凭证（刷新 token 并启用）"""
    import asyncio
    from app.database import async_session
    
    result = await db.execute(
        select(Credential).where(
            Credential.api_type == MODE,
            Credential.refresh_token.isnot(None)
        )
    )
    creds = result.scalars().all()
    total = len(creds)
    
    cred_data = [{
        "id": c.id,
        "email": c.email,
        "refresh_token": c.refresh_token,
        "client_id": c.client_id,
        "client_secret": c.client_secret,
    } for c in creds]
    
    task_id = f"antigravity_start_{datetime.utcnow().timestamp()}"
    
    async def run_in_background():
        semaphore = asyncio.Semaphore(50)
        success = 0
        failed = 0
        
        async def refresh_single(data):
            nonlocal success, failed
            async with semaphore:
                try:
                    temp_cred = Credential(
                        id=data["id"],
                        refresh_token=data["refresh_token"],
                        client_id=data["client_id"],
                        client_secret=data["client_secret"]
                    )
                    access_token = await CredentialPool.refresh_access_token(temp_cred)
                    return {"id": data["id"], "email": data["email"], "token": access_token}
                except Exception as e:
                    print(f"[Antigravity启动] ❌ {data['email']} 异常: {e}", flush=True)
                    return {"id": data["id"], "email": data["email"], "token": None}
        
        print(f"[Antigravity启动] 后台开始刷新 {total} 个凭证...", flush=True)
        results = await asyncio.gather(*[refresh_single(d) for d in cred_data])
        
        async with async_session() as session:
            for res in results:
                if res["token"]:
                    result = await session.execute(
                        update(Credential)
                        .where(Credential.id == res["id"])
                        .values(
                            api_key=encrypt_credential(res["token"]),
                            is_active=True,
                            last_error=None
                        )
                    )
                    if result.rowcount > 0:
                        success += 1
                else:
                    failed += 1
            await session.commit()
        
        print(f"[Antigravity启动] 完成: 成功 {success}, 失败 {failed}", flush=True)
    
    asyncio.create_task(run_in_background())
    
    return {"message": "后台任务已启动", "task_id": task_id, "total": total}


# ===== 统计信息 =====

@router.get("/stats")
async def get_antigravity_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取 Antigravity 凭证统计信息"""
    # 总凭证数
    total_result = await db.execute(
        select(func.count(Credential.id)).where(Credential.api_type == MODE)
    )
    total = total_result.scalar() or 0
    
    # 活跃凭证数
    active_result = await db.execute(
        select(func.count(Credential.id))
        .where(Credential.api_type == MODE)
        .where(Credential.is_active == True)
    )
    active = active_result.scalar() or 0
    
    # 公开凭证数
    public_result = await db.execute(
        select(func.count(Credential.id))
        .where(Credential.api_type == MODE)
        .where(Credential.is_public == True)
        .where(Credential.is_active == True)
    )
    public = public_result.scalar() or 0
    
    # 用户凭证数
    user_creds_result = await db.execute(
        select(func.count(Credential.id))
        .where(Credential.api_type == MODE)
        .where(Credential.user_id == user.id)
    )
    user_creds = user_creds_result.scalar() or 0
    
    user_active_result = await db.execute(
        select(func.count(Credential.id))
        .where(Credential.api_type == MODE)
        .where(Credential.user_id == user.id)
        .where(Credential.is_active == True)
    )
    user_active = user_active_result.scalar() or 0
    
    return {
        "total": total,
        "active": active,
        "public": public,
        "user_credentials": user_creds,
        "user_active": user_active,
        "enabled": settings.antigravity_enabled
    }