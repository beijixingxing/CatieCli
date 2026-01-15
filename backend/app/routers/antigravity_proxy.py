from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_
from datetime import datetime, timedelta
import json
import time

from app.database import get_db, async_session
from app.models.user import User, UsageLog
from app.services.auth import get_user_by_api_key
from app.services.credential_pool import CredentialPool
from app.services.antigravity_client import AntigravityClient
from app.services.websocket import notify_log_update, notify_stats_update
from app.services.error_classifier import classify_error_simple
from app.services.error_message_service import get_custom_error_message
from app.config import settings
import re

router = APIRouter(prefix="/antigravity", tags=["Antigravity API代理"])


def extract_status_code(error_str: str, default: int = 500) -> int:
    """从错误信息中提取HTTP状态码"""
    patterns = [
        r'API Error (\d{3})',
        r'"code":\s*(\d{3})',
        r'status_code[=:]\s*(\d{3})',
        r'HTTP (\d{3})',
        r'Error (\d{3}):',
    ]
    for pattern in patterns:
        match = re.search(pattern, error_str)
        if match:
            code = int(match.group(1))
            if 400 <= code < 600:
                return code
    return default


async def get_user_from_api_key(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """从请求中提取API Key并验证用户"""
    # 检查 Antigravity 功能是否启用
    if not settings.antigravity_enabled:
        raise HTTPException(status_code=503, detail="Antigravity API 功能已禁用")
    
    api_key = None

    # 1. 从Authorization header获取
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        api_key = auth_header[7:]

    # 2. 从x-api-key header获取
    if not api_key:
        api_key = request.headers.get("x-api-key")

    # 3. 从x-goog-api-key header获取
    if not api_key:
        api_key = request.headers.get("x-goog-api-key")

    # 4. 从查询参数获取
    if not api_key:
        api_key = request.query_params.get("key")
    
    if not api_key:
        raise HTTPException(status_code=401, detail="未提供API Key")
    
    user = await get_user_by_api_key(db, api_key)
    if not user:
        raise HTTPException(status_code=401, detail="无效的API Key")
    
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账户已被禁用")
    
    # GET 请求不需要检查配额
    if request.method == "GET":
        return user
    
    # 检查配额 (复用原有逻辑)
    now = datetime.utcnow()
    reset_time_utc = now.replace(hour=7, minute=0, second=0, microsecond=0)
    if now < reset_time_utc:
        start_of_day = reset_time_utc - timedelta(days=1)
    else:
        start_of_day = reset_time_utc

    body = await request.json()
    model = body.get("model", "gemini-2.5-flash")
    required_tier = CredentialPool.get_required_tier(model)
    
    from app.models.user import Credential
    from sqlalchemy import case
    
    # 只统计 Antigravity 类型的凭证
    cred_stats_result = await db.execute(
        select(
            func.count(Credential.id).label("total"),
            func.sum(case((Credential.model_tier == "3", 1), else_=0)).label("tier_30")
        )
        .where(Credential.user_id == user.id)
        .where(Credential.api_type == "antigravity")  # 只统计 Antigravity 凭证
        .where(Credential.is_active == True)
    )
    cred_stats = cred_stats_result.one()
    total_cred_count = cred_stats.total or 0
    cred_30_count = cred_stats.tier_30 or 0
    cred_25_count = total_cred_count - cred_30_count
    has_credential = total_cred_count > 0

    if user.quota_flash and user.quota_flash > 0:
        user_quota_flash = user.quota_flash
    elif has_credential:
        user_quota_flash = total_cred_count * settings.quota_flash
    else:
        user_quota_flash = settings.no_cred_quota_flash
    
    if user.quota_25pro and user.quota_25pro > 0:
        user_quota_pro = user.quota_25pro
    elif cred_30_count > 0:
        user_quota_pro = cred_30_count * settings.quota_30pro
    elif has_credential:
        user_quota_pro = total_cred_count * settings.quota_25pro
    else:
        user_quota_pro = settings.no_cred_quota_25pro
    
    has_30_access = cred_30_count > 0 or (user.quota_30pro and user.quota_30pro > 0)

    if required_tier == "3":
        if not has_30_access:
            raise HTTPException(status_code=403, detail="无 3.0 模型使用配额")
        quota_limit = user_quota_pro
        model_filter = or_(UsageLog.model.like('%pro%'), UsageLog.model.like('%3%'))
        quota_name = "Pro模型(2.5pro+3.0共享)"
    elif "pro" in model.lower():
        quota_limit = user_quota_pro
        if has_30_access:
            model_filter = or_(UsageLog.model.like('%pro%'), UsageLog.model.like('%3%'))
            quota_name = "Pro模型(2.5pro+3.0共享)"
        else:
            model_filter = UsageLog.model.like('%pro%')
            quota_name = "2.5 Pro模型"
    else:
        quota_limit = user_quota_flash
        model_filter = and_(UsageLog.model.notlike('%pro%'), UsageLog.model.notlike('%3%'))
        quota_name = "Flash模型"

    if quota_limit > 0 or has_credential:
        usage_stats_result = await db.execute(
            select(
                func.sum(case((model_filter, 1), else_=0)).label("model_usage"),
                func.count(UsageLog.id).label("total_usage")
            )
            .where(UsageLog.user_id == user.id)
            .where(UsageLog.created_at >= start_of_day)
        )
        usage_stats = usage_stats_result.one()
        current_usage = usage_stats.model_usage or 0
        total_usage = usage_stats.total_usage or 0
        
        if quota_limit > 0 and current_usage >= quota_limit:
            raise HTTPException(
                status_code=429, 
                detail=f"已达到{quota_name}每日配额限制 ({current_usage}/{quota_limit})"
            )
        
        if has_credential and total_usage >= user.daily_quota:
            raise HTTPException(status_code=429, detail="已达到今日总配额限制")
    
    return user


# ===== CORS 预检请求处理 =====

@router.options("/v1/chat/completions")
@router.options("/v1/models")
async def options_handler():
    """处理 CORS 预检请求"""
    return JSONResponse(content={}, headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "*",
    })


@router.get("/v1/models")
async def list_models(request: Request, user: User = Depends(get_user_from_api_key), db: AsyncSession = Depends(get_db)):
    """列出可用模型 (OpenAI兼容) - Antigravity"""
    from app.models.user import Credential
    
    # 检查是否有可用的 3.0 Antigravity 凭证
    has_tier3 = await CredentialPool.has_tier3_credentials(user, db, mode="antigravity")
    
    # 尝试从 Antigravity API 获取动态模型列表
    user_has_public = await CredentialPool.check_user_has_public_creds(db, user.id, mode="antigravity")
    credential = await CredentialPool.get_available_credential(
        db, user_id=user.id, user_has_public_creds=user_has_public, model="gemini-2.5-flash",
        mode="antigravity"  # 使用 Antigravity 凭证
    )
    
    if credential:
        access_token = await CredentialPool.get_access_token(credential, db)
        if access_token:
            project_id = credential.project_id or ""
            client = AntigravityClient(access_token, project_id)
            try:
                dynamic_models = await client.fetch_available_models()
                if dynamic_models:
                    # 添加假流式和抗截断变体
                    models = []
                    for m in dynamic_models:
                        model_id = m.get("id", "")
                        models.append({"id": model_id, "object": "model", "owned_by": "google"})
                        models.append({"id": f"假流式/{model_id}", "object": "model", "owned_by": "google"})
                        models.append({"id": f"流式抗截断/{model_id}", "object": "model", "owned_by": "google"})
                    return {"object": "list", "data": models}
            except Exception as e:
                print(f"[Antigravity] 获取动态模型列表失败: {e}", flush=True)
    
    # 回退到静态模型列表
    base_models = [
        "gemini-2.5-pro",
        "gemini-2.5-flash",
    ]
    
    if has_tier3:
        base_models.append("gemini-3-pro-preview")
        base_models.append("gemini-3-flash-preview")
    
    thinking_suffixes = ["-maxthinking", "-nothinking"]
    search_suffix = "-search"
    
    models = []
    for base in base_models:
        models.append({"id": base, "object": "model", "owned_by": "google"})
        models.append({"id": f"假流式/{base}", "object": "model", "owned_by": "google"})
        models.append({"id": f"流式抗截断/{base}", "object": "model", "owned_by": "google"})
        
        for suffix in thinking_suffixes:
            models.append({"id": f"{base}{suffix}", "object": "model", "owned_by": "google"})
            models.append({"id": f"假流式/{base}{suffix}", "object": "model", "owned_by": "google"})
            models.append({"id": f"流式抗截断/{base}{suffix}", "object": "model", "owned_by": "google"})
        
        models.append({"id": f"{base}{search_suffix}", "object": "model", "owned_by": "google"})
        models.append({"id": f"假流式/{base}{search_suffix}", "object": "model", "owned_by": "google"})
        models.append({"id": f"流式抗截断/{base}{search_suffix}", "object": "model", "owned_by": "google"})
        
        for suffix in thinking_suffixes:
            combined = f"{suffix}{search_suffix}"
            models.append({"id": f"{base}{combined}", "object": "model", "owned_by": "google"})
            models.append({"id": f"假流式/{base}{combined}", "object": "model", "owned_by": "google"})
            models.append({"id": f"流式抗截断/{base}{combined}", "object": "model", "owned_by": "google"})
    
    return {"object": "list", "data": models}


@router.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_user_from_api_key),
    db: AsyncSession = Depends(get_db)
):
    """Chat Completions (OpenAI兼容) - Antigravity"""
    start_time = time.time()
    
    client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown").split(",")[0].strip()
    user_agent = request.headers.get("User-Agent", "")[:500]
    
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="无效的JSON请求体")
    
    request_body_str = json.dumps(body, ensure_ascii=False)[:2000] if body else None
    
    model = body.get("model", "gemini-2.5-flash")
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    
    if not messages:
        raise HTTPException(status_code=400, detail="messages不能为空")
    
    # 检查用户是否有公开的 Antigravity 凭证
    user_has_public = await CredentialPool.check_user_has_public_creds(db, user.id, mode="antigravity")
    
    # 速率限制检查
    if not user.is_admin:
        one_minute_ago = datetime.utcnow() - timedelta(minutes=1)
        rpm_result = await db.execute(
            select(func.count(UsageLog.id))
            .where(UsageLog.user_id == user.id)
            .where(UsageLog.created_at >= one_minute_ago)
        )
        current_rpm = rpm_result.scalar() or 0
        max_rpm = settings.contributor_rpm if user_has_public else settings.base_rpm
        
        if current_rpm >= max_rpm:
            raise HTTPException(
                status_code=429, 
                detail=f"速率限制: {max_rpm} 次/分钟"
            )
    
    # 插入占位记录
    placeholder_log = UsageLog(
        user_id=user.id,
        model=f"antigravity/{model}",  # 标记为 Antigravity 请求
        endpoint="/antigravity/v1/chat/completions",
        status_code=0,
        latency_ms=0,
        client_ip=client_ip,
        user_agent=user_agent
    )
    db.add(placeholder_log)
    await db.commit()
    await db.refresh(placeholder_log)
    placeholder_log_id = placeholder_log.id
    
    # 获取 Antigravity 凭证
    max_retries = settings.error_retry_count
    tried_credential_ids = set()
    
    credential = await CredentialPool.get_available_credential(
        db,
        user_id=user.id,
        user_has_public_creds=user_has_public,
        model=model,
        exclude_ids=tried_credential_ids,
        mode="antigravity"  # 使用 Antigravity 凭证
    )
    if not credential:
        required_tier = CredentialPool.get_required_tier(model)
        placeholder_log.status_code = 503
        placeholder_log.latency_ms = (time.time() - start_time) * 1000
        placeholder_log.error_type = "NO_CREDENTIAL"
        placeholder_log.error_code = "NO_CREDENTIAL"
        if required_tier == "3":
            placeholder_log.error_message = "没有可用的 Gemini 3 等级凭证"
            await db.commit()
            raise HTTPException(
                status_code=503, 
                detail="没有可用的 Gemini 3 等级凭证。该模型需要有 Gemini 3 资格的凭证。"
            )
        if not user_has_public:
            placeholder_log.error_message = "用户没有可用的 Antigravity 凭证"
            await db.commit()
            raise HTTPException(
                status_code=503,
                detail="您没有可用的 Antigravity 凭证。请在 Antigravity 凭证管理页面上传凭证，或捐赠凭证以使用公共池。"
            )
        placeholder_log.error_message = "暂无可用凭证"
        await db.commit()
        raise HTTPException(status_code=503, detail="暂无可用凭证，请稍后重试")
    
    tried_credential_ids.add(credential.id)
    
    # 使用 Antigravity 模式获取 token 和 project_id
    access_token, project_id = await CredentialPool.get_access_token_and_project(credential, db, mode="antigravity")
    if not access_token:
        await CredentialPool.mark_credential_error(db, credential.id, "Token 刷新失败")
        placeholder_log.status_code = 503
        placeholder_log.latency_ms = (time.time() - start_time) * 1000
        placeholder_log.error_type = "TOKEN_ERROR"
        placeholder_log.error_code = "TOKEN_REFRESH_FAILED"
        placeholder_log.error_message = "Token 刷新失败"
        placeholder_log.credential_id = credential.id
        placeholder_log.credential_email = credential.email
        await db.commit()
        raise HTTPException(status_code=503, detail="Token 刷新失败")
    
    if not project_id:
        await CredentialPool.mark_credential_error(db, credential.id, "无法获取 Antigravity project_id")
        placeholder_log.status_code = 503
        placeholder_log.latency_ms = (time.time() - start_time) * 1000
        placeholder_log.error_type = "CONFIG_ERROR"
        placeholder_log.error_code = "NO_ANTIGRAVITY_PROJECT"
        placeholder_log.error_message = "无法获取 Antigravity project_id"
        placeholder_log.credential_id = credential.id
        placeholder_log.credential_email = credential.email
        await db.commit()
        raise HTTPException(status_code=503, detail="凭证未激活 Antigravity，无法获取 project_id")
    first_credential_id = credential.id
    first_credential_email = credential.email
    print(f"[Antigravity Proxy] 使用凭证: {credential.email}, project_id: {project_id}, model: {model}", flush=True)
    
    client = AntigravityClient(access_token, project_id)
    use_fake_streaming = client.is_fake_streaming(model)
    last_error = None
    
    # 非流式处理
    async def handle_non_stream():
        nonlocal credential, access_token, project_id, client, tried_credential_ids, last_error
        
        for retry_attempt in range(max_retries + 1):
            try:
                result = await client.chat_completions(
                    model=model,
                    messages=messages,
                    **{k: v for k, v in body.items() if k not in ["model", "messages", "stream"]}
                )
                
                latency = (time.time() - start_time) * 1000
                
                placeholder_log.credential_id = credential.id
                placeholder_log.status_code = 200
                placeholder_log.latency_ms = latency
                placeholder_log.credential_email = credential.email
                placeholder_log.retry_count = retry_attempt
                await db.commit()
                
                credential.total_requests = (credential.total_requests or 0) + 1
                credential.last_used_at = datetime.utcnow()
                await db.commit()
                
                await notify_log_update({
                    "username": user.username,
                    "model": f"antigravity/{model}",
                    "status_code": 200,
                    "latency_ms": round(latency, 0),
                    "created_at": datetime.utcnow().isoformat()
                })
                await notify_stats_update()
                
                return JSONResponse(content=result)
                
            except Exception as e:
                error_str = str(e)
                await CredentialPool.handle_credential_failure(db, credential.id, error_str)
                last_error = error_str
                
                should_retry = any(code in error_str for code in ["404", "500", "502", "503", "504", "429", "RESOURCE_EXHAUSTED", "NOT_FOUND", "ECONNRESET", "socket hang up", "ConnectionReset", "Connection reset", "ETIMEDOUT", "ECONNREFUSED", "Gateway Timeout", "timeout"])
                
                if should_retry and retry_attempt < max_retries:
                    print(f"[Antigravity Proxy] ⚠️ 请求失败: {error_str}，切换凭证重试 ({retry_attempt + 2}/{max_retries + 1})", flush=True)
                    
                    credential = await CredentialPool.get_available_credential(
                        db, user_id=user.id, user_has_public_creds=user_has_public,
                        model=model, exclude_ids=tried_credential_ids,
                        mode="antigravity"  # 使用 Antigravity 凭证
                    )
                    if not credential:
                        break
                    
                    tried_credential_ids.add(credential.id)
                    access_token, project_id = await CredentialPool.get_access_token_and_project(credential, db, mode="antigravity")
                    if not access_token or not project_id:
                        continue
                    client = AntigravityClient(access_token, project_id)
                    print(f"[Antigravity Proxy] 🔄 切换到凭证: {credential.email}", flush=True)
                    continue
                
                status_code = extract_status_code(error_str)
                latency = (time.time() - start_time) * 1000
                error_type, error_code = classify_error_simple(status_code, error_str)
                
                placeholder_log.credential_id = credential.id
                placeholder_log.status_code = status_code
                placeholder_log.latency_ms = latency
                placeholder_log.error_message = error_str[:2000]
                placeholder_log.error_type = error_type
                placeholder_log.error_code = error_code
                placeholder_log.credential_email = credential.email
                placeholder_log.request_body = request_body_str
                placeholder_log.retry_count = retry_attempt
                await db.commit()
                
                raise HTTPException(status_code=status_code, detail=f"Antigravity API调用失败 (已重试 {retry_attempt + 1} 次): {error_str}")
        
        raise HTTPException(status_code=503, detail=f"所有凭证都失败了: {last_error}")
    
    if not stream:
        return await handle_non_stream()
    
    # 流式处理
    async def save_log_background(log_data: dict):
        try:
            async with async_session() as bg_db:
                latency = log_data.get("latency_ms", 0)
                status_code = log_data.get("status_code", 200)
                error_msg = log_data.get("error_message")
                
                error_type = None
                error_code = None
                if status_code != 200 and error_msg:
                    error_type, error_code = classify_error_simple(status_code, error_msg)
                
                log_result = await bg_db.execute(
                    select(UsageLog).where(UsageLog.id == placeholder_log_id)
                )
                log = log_result.scalar_one_or_none()
                if log:
                    log.credential_id = log_data.get("cred_id")
                    log.status_code = status_code
                    log.latency_ms = latency
                    log.error_message = error_msg[:2000] if error_msg else None
                    log.error_type = error_type
                    log.error_code = error_code
                    log.credential_email = log_data.get("cred_email")
                    log.request_body = request_body_str if status_code != 200 else None
                    log.retry_count = log_data.get("retry_count", 0)
                
                cred_id = log_data.get("cred_id")
                if cred_id:
                    from app.models.user import Credential
                    cred_result = await bg_db.execute(
                        select(Credential).where(Credential.id == cred_id)
                    )
                    cred = cred_result.scalar_one_or_none()
                    if cred:
                        cred.total_requests = (cred.total_requests or 0) + 1
                        cred.last_used_at = datetime.utcnow()
                
                await bg_db.commit()
                
                await notify_log_update({
                    "username": user.username,
                    "model": f"antigravity/{model}",
                    "status_code": status_code,
                    "error_type": error_type,
                    "latency_ms": round(latency, 0),
                    "created_at": datetime.utcnow().isoformat()
                })
                await notify_stats_update()
                print(f"[Antigravity Proxy] ✅ 后台日志已记录: user={user.username}, model={model}, status={status_code}", flush=True)
        except Exception as log_err:
            print(f"[Antigravity Proxy] ❌ 后台日志记录失败: {log_err}", flush=True)
    
    async def stream_generator_with_retry():
        nonlocal access_token, project_id, client, tried_credential_ids, last_error
        current_cred_id = first_credential_id
        current_cred_email = first_credential_email
        
        for stream_retry in range(max_retries + 1):
            try:
                if use_fake_streaming:
                    async for chunk in client.chat_completions_fake_stream(
                        model=model,
                        messages=messages,
                        **{k: v for k, v in body.items() if k not in ["model", "messages", "stream"]}
                    ):
                        yield chunk
                else:
                    async for chunk in client.chat_completions_stream(
                        model=model,
                        messages=messages,
                        **{k: v for k, v in body.items() if k not in ["model", "messages", "stream"]}
                    ):
                        yield chunk
                
                latency = (time.time() - start_time) * 1000
                await save_log_background({
                    "status_code": 200,
                    "cred_id": current_cred_id,
                    "cred_email": current_cred_email,
                    "latency_ms": latency,
                    "retry_count": stream_retry
                })
                yield "data: [DONE]\n\n"
                return
                
            except Exception as e:
                error_str = str(e)
                last_error = error_str
                
                try:
                    async with async_session() as stream_db:
                        await CredentialPool.handle_credential_failure(stream_db, current_cred_id, error_str)
                except Exception as db_err:
                    print(f"[Antigravity Proxy] ⚠️ 标记凭证失败时出错: {db_err}", flush=True)
                
                should_retry = any(code in error_str for code in ["404", "500", "502", "503", "504", "429", "RESOURCE_EXHAUSTED", "NOT_FOUND", "ECONNRESET", "socket hang up", "ConnectionReset", "Connection reset", "ETIMEDOUT", "ECONNREFUSED", "Gateway Timeout", "timeout"])
                
                if should_retry and stream_retry < max_retries:
                    print(f"[Antigravity Proxy] ⚠️ 流式请求失败: {error_str}，切换凭证重试 ({stream_retry + 2}/{max_retries + 1})", flush=True)
                    
                    try:
                        async with async_session() as stream_db:
                            new_credential = await CredentialPool.get_available_credential(
                                stream_db, user_id=user.id, user_has_public_creds=user_has_public,
                                model=model, exclude_ids=tried_credential_ids,
                                mode="antigravity"  # 使用 Antigravity 凭证
                            )
                            if new_credential:
                                tried_credential_ids.add(new_credential.id)
                                new_token, new_project_id = await CredentialPool.get_access_token_and_project(new_credential, stream_db, mode="antigravity")
                                if new_token and new_project_id:
                                    current_cred_id = new_credential.id
                                    current_cred_email = new_credential.email
                                    access_token = new_token
                                    project_id = new_project_id
                                    client = AntigravityClient(access_token, project_id)
                                    print(f"[Antigravity Proxy] 🔄 切换到凭证: {current_cred_email}", flush=True)
                                    continue
                    except Exception as retry_err:
                        print(f"[Antigravity Proxy] ⚠️ 获取新凭证失败: {retry_err}", flush=True)
                
                status_code = extract_status_code(error_str)
                latency = (time.time() - start_time) * 1000
                await save_log_background({
                    "status_code": status_code,
                    "cred_id": current_cred_id,
                    "cred_email": current_cred_email,
                    "error_message": error_str,
                    "latency_ms": latency,
                    "retry_count": stream_retry
                })
                yield f"data: {json.dumps({'error': f'Antigravity API Error (已重试 {stream_retry + 1} 次): {error_str}'})}\n\n"
                return
    
    return StreamingResponse(
        stream_generator_with_retry(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )

