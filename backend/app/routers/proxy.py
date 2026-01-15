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
from app.services.gemini_client import GeminiClient
from app.services.websocket import notify_log_update, notify_stats_update
from app.services.error_classifier import classify_error_simple
from app.services.error_message_service import get_custom_error_message
from app.config import settings
import re

router = APIRouter(tags=["API代理"])


def extract_status_code(error_str: str, default: int = 500) -> int:
    """从错误信息中提取HTTP状态码"""
    # 匹配 "API Error 403" 或 "code": 403 或 status_code=403 等模式
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
    api_key = None

    # 1. 从Authorization header获取
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        api_key = auth_header[7:]

    # 2. 从x-api-key header获取
    if not api_key:
        api_key = request.headers.get("x-api-key")

    # 3. 从x-goog-api-key header获取（Gemini原生客户端支持）
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
    
    # GET 请求（如 /v1/models）不需要检查配额
    if request.method == "GET":
        return user
    
    # 检查配额
    # 配额在北京时间 15:00 (UTC 07:00) 重置
    now = datetime.utcnow()
    reset_time_utc = now.replace(hour=7, minute=0, second=0, microsecond=0)
    if now < reset_time_utc:
        start_of_day = reset_time_utc - timedelta(days=1)
    else:
        start_of_day = reset_time_utc

    # 获取请求的模型
    body = await request.json()
    model = body.get("model", "gemini-2.5-flash")
    required_tier = CredentialPool.get_required_tier(model)
    
    # 检查用户凭证情况
    from app.models.user import Credential
    from sqlalchemy import case
    
    # 合并凭证统计查询（2.5和3.0一次性查询）
    cred_stats_result = await db.execute(
        select(
            func.count(Credential.id).label("total"),
            func.sum(case((Credential.model_tier == "3", 1), else_=0)).label("tier_30")
        )
        .where(Credential.user_id == user.id)
        .where(Credential.is_active == True)
    )
    cred_stats = cred_stats_result.one()
    total_cred_count = cred_stats.total or 0
    cred_30_count = cred_stats.tier_30 or 0
    cred_25_count = total_cred_count - cred_30_count
    has_credential = total_cred_count > 0

    # 计算用户各类模型的配额上限
    # 优先使用用户设置的按模型配额，0表示使用系统默认
    if user.quota_flash and user.quota_flash > 0:
        user_quota_flash = user.quota_flash
    elif has_credential:
        user_quota_flash = total_cred_count * settings.quota_flash
    else:
        user_quota_flash = settings.no_cred_quota_flash
    
    # Pro配额（2.5pro和3.0共享）
    # 官方规则：无3.0资格200次2.5pro，有3.0资格100次共享，Pro号250次共享
    if user.quota_25pro and user.quota_25pro > 0:
        user_quota_pro = user.quota_25pro  # 用户手动设置的配额
    elif cred_30_count > 0:
        # 有3.0凭证：使用3.0配额（2.5pro和3.0共享）
        user_quota_pro = cred_30_count * settings.quota_30pro
    elif has_credential:
        # 只有2.5凭证：使用2.5pro配额
        user_quota_pro = total_cred_count * settings.quota_25pro
    else:
        # 无凭证
        user_quota_pro = settings.no_cred_quota_25pro
    
    # 判断用户是否有3.0资格（用于决定是否允许使用3.0模型）
    has_30_access = cred_30_count > 0 or (user.quota_30pro and user.quota_30pro > 0)

    # 确定当前请求的模型类别和对应配额
    if required_tier == "3":
        if not has_30_access:
            raise HTTPException(status_code=403, detail="无 3.0 模型使用配额")
        quota_limit = user_quota_pro
        # 2.5pro和3.0共享配额，统计所有pro模型（含2.5pro和3.0）
        model_filter = or_(UsageLog.model.like('%pro%'), UsageLog.model.like('%3%'))
        quota_name = "Pro模型(2.5pro+3.0共享)"
    elif "pro" in model.lower():
        quota_limit = user_quota_pro
        # 2.5pro和3.0共享配额
        if has_30_access:
            model_filter = or_(UsageLog.model.like('%pro%'), UsageLog.model.like('%3%'))
            quota_name = "Pro模型(2.5pro+3.0共享)"
        else:
            model_filter = UsageLog.model.like('%pro%')
            quota_name = "2.5 Pro模型"
    else:
        quota_limit = user_quota_flash
        # Flash配额：排除pro和3.0模型
        model_filter = and_(UsageLog.model.notlike('%pro%'), UsageLog.model.notlike('%3%'))
        quota_name = "Flash模型"

    # 合并使用量查询（模型类别和总量一次性查询）
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
        
        # 检查该类别模型的使用量
        if quota_limit > 0 and current_usage >= quota_limit:
            raise HTTPException(
                status_code=429, 
                detail=f"已达到{quota_name}每日配额限制 ({current_usage}/{quota_limit})"
            )
        
        # 检查总配额
        if has_credential and total_usage >= user.daily_quota:
            raise HTTPException(status_code=429, detail="已达到今日总配额限制")
    
    return user


# ===== CORS 预检请求处理 =====
# 注意：由于 URL 规范化中间件的存在，用户输入的任意前缀（如 /ABC/v1/...）都会被自动修正
# 因此这里只需要定义标准路径即可

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
    """列出可用模型 (OpenAI兼容) - 同时包含 GeminiCLI 和 Antigravity 模型
    
    模型命名规则：
    - GeminiCLI: 无前缀（向后兼容）或 gcli- 前缀，支持思考/搜索后缀
    - Antigravity: agy- 前缀，只支持流式前缀，无思考/搜索后缀
    """
    from app.models.user import Credential
    from sqlalchemy import or_
    
    # 检查是否有可用的 GeminiCLI 3.0 凭证
    has_cli_tier3 = await CredentialPool.has_tier3_credentials(user, db, mode="geminicli")
    
    # 检查是否有可用的 Antigravity 凭证
    has_agy_creds = await db.execute(
        select(func.count(Credential.id))
        .where(Credential.api_type == "antigravity")
        .where(Credential.is_active == True)
        .where(or_(
            Credential.user_id == user.id,
            Credential.is_public == True
        ))
    )
    has_antigravity = (has_agy_creds.scalar() or 0) > 0
    
    # 检查是否有可用的 Antigravity 3.0 凭证
    has_agy_tier3 = await CredentialPool.has_tier3_credentials(user, db, mode="antigravity") if has_antigravity else False
    
    # 基础模型 (Gemini 2.5+)
    base_models = [
        "gemini-2.5-pro",
        "gemini-2.5-flash",
    ]
    
    tier3_models = ["gemini-3-pro-preview", "gemini-3-flash-preview"]
    
    # Thinking 后缀
    thinking_suffixes = ["-maxthinking", "-nothinking"]
    # Search 后缀
    search_suffix = "-search"
    
    models = []
    
    # === GeminiCLI 模型（无前缀向后兼容 + gcli- 前缀）===
    cli_base_models = base_models.copy()
    if has_cli_tier3:
        cli_base_models.extend(tier3_models)
    
    for base in cli_base_models:
        # 不带前缀的基础模型（向后兼容）
        models.append({"id": base, "object": "model", "owned_by": "google"})
        models.append({"id": f"假流式/{base}", "object": "model", "owned_by": "google"})
        models.append({"id": f"流式抗截断/{base}", "object": "model", "owned_by": "google"})
        
        # 带 gcli- 前缀的模型
        models.append({"id": f"gcli-{base}", "object": "model", "owned_by": "google"})
        models.append({"id": f"假流式/gcli-{base}", "object": "model", "owned_by": "google"})
        models.append({"id": f"流式抗截断/gcli-{base}", "object": "model", "owned_by": "google"})
        
        # thinking 变体（无前缀）
        for suffix in thinking_suffixes:
            models.append({"id": f"{base}{suffix}", "object": "model", "owned_by": "google"})
            models.append({"id": f"假流式/{base}{suffix}", "object": "model", "owned_by": "google"})
            models.append({"id": f"流式抗截断/{base}{suffix}", "object": "model", "owned_by": "google"})
        
        # thinking 变体（gcli- 前缀）
        for suffix in thinking_suffixes:
            models.append({"id": f"gcli-{base}{suffix}", "object": "model", "owned_by": "google"})
            models.append({"id": f"假流式/gcli-{base}{suffix}", "object": "model", "owned_by": "google"})
            models.append({"id": f"流式抗截断/gcli-{base}{suffix}", "object": "model", "owned_by": "google"})
        
        # search 变体（无前缀）
        models.append({"id": f"{base}{search_suffix}", "object": "model", "owned_by": "google"})
        models.append({"id": f"假流式/{base}{search_suffix}", "object": "model", "owned_by": "google"})
        models.append({"id": f"流式抗截断/{base}{search_suffix}", "object": "model", "owned_by": "google"})
        
        # search 变体（gcli- 前缀）
        models.append({"id": f"gcli-{base}{search_suffix}", "object": "model", "owned_by": "google"})
        models.append({"id": f"假流式/gcli-{base}{search_suffix}", "object": "model", "owned_by": "google"})
        models.append({"id": f"流式抗截断/gcli-{base}{search_suffix}", "object": "model", "owned_by": "google"})
        
        # thinking + search 组合（无前缀）
        for suffix in thinking_suffixes:
            combined = f"{suffix}{search_suffix}"
            models.append({"id": f"{base}{combined}", "object": "model", "owned_by": "google"})
            models.append({"id": f"假流式/{base}{combined}", "object": "model", "owned_by": "google"})
            models.append({"id": f"流式抗截断/{base}{combined}", "object": "model", "owned_by": "google"})
        
        # thinking + search 组合（gcli- 前缀）
        for suffix in thinking_suffixes:
            combined = f"{suffix}{search_suffix}"
            models.append({"id": f"gcli-{base}{combined}", "object": "model", "owned_by": "google"})
            models.append({"id": f"假流式/gcli-{base}{combined}", "object": "model", "owned_by": "google"})
            models.append({"id": f"流式抗截断/gcli-{base}{combined}", "object": "model", "owned_by": "google"})
    
    # Image 模型
    models.append({"id": "gemini-2.5-flash-image", "object": "model", "owned_by": "google"})
    models.append({"id": "gcli-gemini-2.5-flash-image", "object": "model", "owned_by": "google"})
    
    # === Antigravity 模型（agy- 前缀，从 API 动态获取，无流式前缀和思考/搜索后缀）===
    if has_antigravity and settings.antigravity_enabled:
        # 尝试从 Antigravity API 动态获取模型列表
        try:
            from app.services.antigravity_client import AntigravityClient
            from sqlalchemy import or_
            
            # 获取一个有效的 Antigravity 凭证
            agy_cred_result = await db.execute(
                select(Credential)
                .where(Credential.api_type == "antigravity")
                .where(Credential.is_active == True)
                .where(or_(
                    Credential.user_id == user.id,
                    Credential.is_public == True
                ))
                .limit(1)
            )
            agy_cred = agy_cred_result.scalar_one_or_none()
            
            if agy_cred:
                access_token = await CredentialPool.get_access_token(agy_cred, db)
                if access_token:
                    client = AntigravityClient(access_token, agy_cred.project_id)
                    api_models = await client.fetch_available_models()
                    
                    # 添加 API 返回的模型（加上 agy- 前缀，无流式前缀）
                    for model_info in api_models:
                        model_id = model_info.get("id", "")
                        if model_id:
                            models.append({
                                "id": f"agy-{model_id}",
                                "object": "model",
                                "owned_by": "google"
                            })
                    
                    # 额外添加 claude-opus-4-5（如果 API 没返回）
                    existing_ids = [m["id"] for m in models]
                    if "agy-claude-opus-4-5" not in existing_ids:
                        models.append({"id": "agy-claude-opus-4-5", "object": "model", "owned_by": "google"})
        except Exception as e:
            print(f"[Models] 获取 Antigravity 模型列表失败: {e}", flush=True)
            # 降级：使用静态模型列表
            fallback_agy_models = [
                "gemini-2.5-flash", "gemini-2.5-pro", "gemini-3-flash", "gemini-3-pro-low",
                "gemini-3-pro-high", "gemini-2.5-flash-thinking", "claude-opus-4-5",
                "claude-opus-4-5-thinking", "claude-sonnet-4-5", "claude-sonnet-4-5-thinking"
            ]
            for base in fallback_agy_models:
                models.append({"id": f"agy-{base}", "object": "model", "owned_by": "google"})
    
    return {"object": "list", "data": models}


@router.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_user_from_api_key),
    db: AsyncSession = Depends(get_db)
):
    """Chat Completions (OpenAI兼容) - 支持 agy- 和 gcli- 前缀
    
    路由规则：
    - agy-xxx 前缀 → Antigravity 代理
    - gcli-xxx 前缀或无前缀 → GeminiCLI 代理
    - 流式前缀（假流式/、流式抗截断/）保留，由对应代理处理
    """
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="无效的JSON请求体")
    
    model = body.get("model", "gemini-2.5-flash")
    
    # 提取流式前缀（如果有）
    stream_prefix = ""
    model_without_stream = model
    if model.startswith("假流式/"):
        stream_prefix = "假流式/"
        model_without_stream = model[4:]  # len("假流式/") = 4
    elif model.startswith("流式抗截断/"):
        stream_prefix = "流式抗截断/"
        model_without_stream = model[6:]  # len("流式抗截断/") = 6
    
    # 检测是否是 Antigravity 请求（模型名包含 agy- 前缀）
    is_antigravity = model_without_stream.startswith("agy-")
    if is_antigravity:
        # 检查 Antigravity 功能是否启用
        if not settings.antigravity_enabled:
            raise HTTPException(status_code=503, detail="Antigravity API 功能已禁用")
        
        # 移除 agy- 前缀，保留流式前缀，传递给 Antigravity 代理
        clean_model = model_without_stream[4:]  # 移除 "agy-"
        body["model"] = stream_prefix + clean_model
        
        # 调用 Antigravity 代理处理
        from app.routers.antigravity_proxy import chat_completions as agy_chat_completions
        
        # 创建一个新的 Request 对象，包含修改后的 body
        # 由于 FastAPI 的 Request 对象不可变，我们需要通过 Starlette 的方式处理
        from starlette.requests import Request as StarletteRequest
        from starlette.datastructures import Headers
        import io
        
        # 将修改后的 body 序列化
        modified_body = json.dumps(body).encode()
        
        # 创建一个新的 scope，复制原有的但修改 body
        async def receive():
            return {"type": "http.request", "body": modified_body}
        
        new_request = StarletteRequest(scope=request.scope, receive=receive)
        
        return await agy_chat_completions(new_request, background_tasks, user, db)
    
    # 移除 gcli- 前缀（如果有），保留流式前缀
    if model_without_stream.startswith("gcli-"):
        clean_model = model_without_stream[5:]  # 移除 "gcli-"
        model = stream_prefix + clean_model
        body["model"] = model
    
    start_time = time.time()
    
    # 获取客户端信息
    client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown").split(",")[0].strip()
    user_agent = request.headers.get("User-Agent", "")[:500]
    
    # 保存请求内容摘要（截断到2000字符）
    request_body_str = json.dumps(body, ensure_ascii=False)[:2000] if body else None
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    
    if not messages:
        raise HTTPException(status_code=400, detail="messages不能为空")
    
    # 检查用户是否参与大锅饭
    user_has_public = await CredentialPool.check_user_has_public_creds(db, user.id)
    
    # 速率限制检查 (RPM) - 管理员豁免
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
                detail=f"速率限制: {max_rpm} 次/分钟。{'上传凭证可提升至 ' + str(settings.contributor_rpm) + ' 次/分钟' if not user_has_public else ''}"
            )
    
    # 立即插入占位记录以计入 RPM（防止 BackgroundTasks 导致 RPM 失效）
    placeholder_log = UsageLog(
        user_id=user.id,
        model=model,
        endpoint="/v1/chat/completions",
        status_code=0,  # 0 表示处理中
        latency_ms=0,
        client_ip=client_ip,
        user_agent=user_agent
    )
    db.add(placeholder_log)
    await db.commit()
    await db.refresh(placeholder_log)  # 获取插入后的 ID
    placeholder_log_id = placeholder_log.id  # 保存ID，后续通过独立会话访问
    
    # 获取首个凭证后立即释放主连接（流式响应将使用独立会话）
    # 重试逻辑：报错时切换凭证重试
    max_retries = settings.error_retry_count
    last_error = None
    tried_credential_ids = set()
    
    # 预先获取第一个凭证和token（使用主db）
    credential = await CredentialPool.get_available_credential(
        db, 
        user_id=user.id,
        user_has_public_creds=user_has_public,
        model=model,
        exclude_ids=tried_credential_ids
    )
    if not credential:
        required_tier = CredentialPool.get_required_tier(model)
        # 更新占位日志为错误状态
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
            placeholder_log.error_message = "用户没有可用凭证"
            await db.commit()
            raise HTTPException(
                status_code=503, 
                detail="您没有可用凭证。请在凭证管理页面上传凭证，或捐赠凭证以使用公共池。"
            )
        placeholder_log.error_message = "暂无可用凭证"
        await db.commit()
        raise HTTPException(status_code=503, detail="暂无可用凭证，请稍后重试")
    
    tried_credential_ids.add(credential.id)
    
    # 获取 access_token（自动刷新）
    access_token = await CredentialPool.get_access_token(credential, db)
    if not access_token:
        await CredentialPool.mark_credential_error(db, credential.id, "Token 刷新失败")
        # 更新占位日志为错误状态
        placeholder_log.status_code = 503
        placeholder_log.latency_ms = (time.time() - start_time) * 1000
        placeholder_log.error_type = "TOKEN_ERROR"
        placeholder_log.error_code = "TOKEN_REFRESH_FAILED"
        placeholder_log.error_message = "Token 刷新失败"
        placeholder_log.credential_id = credential.id
        placeholder_log.credential_email = credential.email
        await db.commit()
        raise HTTPException(status_code=503, detail="Token 刷新失败")
    
    # 获取 project_id
    project_id = credential.project_id or ""
    first_credential_id = credential.id
    first_credential_email = credential.email
    print(f"[Proxy] 使用凭证: {credential.email}, project_id: {project_id}, model: {model}", flush=True)
    
    if not project_id:
        print(f"[Proxy] ⚠️ 凭证 {credential.email} 没有 project_id!", flush=True)
    
    client = GeminiClient(access_token, project_id)
    use_fake_streaming = client.is_fake_streaming(model)
    
    # 主db连接到此处结束使用，流式生成器将使用独立会话
    
    # 非流式模式的处理函数（仍在主请求处理器内，可使用主db）
    async def handle_non_stream():
        """处理非流式请求（使用主db）"""
        nonlocal credential, access_token, project_id, client, tried_credential_ids, last_error
        
        for retry_attempt in range(max_retries + 1):
            try:
                result = await client.chat_completions(
                    model=model,
                    messages=messages,
                    **{k: v for k, v in body.items() if k not in ["model", "messages", "stream"]}
                )
                
                # 成功：更新占位日志
                latency = (time.time() - start_time) * 1000
                error_type = None
                error_code = None
                
                placeholder_log.credential_id = credential.id
                placeholder_log.status_code = 200
                placeholder_log.latency_ms = latency
                placeholder_log.error_type = error_type
                placeholder_log.error_code = error_code
                placeholder_log.credential_email = credential.email
                placeholder_log.retry_count = retry_attempt  # 记录重试次数
                await db.commit()
                
                # 更新凭证使用次数
                credential.total_requests = (credential.total_requests or 0) + 1
                credential.last_used_at = datetime.utcnow()
                await db.commit()
                
                # WebSocket 实时通知
                await notify_log_update({
                    "username": user.username,
                    "model": model,
                    "status_code": 200,
                    "error_type": error_type,
                    "latency_ms": round(latency, 0),
                    "created_at": datetime.utcnow().isoformat()
                })
                await notify_stats_update()
                
                return JSONResponse(content=result)
                
            except Exception as e:
                error_str = str(e)
                await CredentialPool.handle_credential_failure(db, credential.id, error_str)
                last_error = error_str
                
                # 检查是否应该重试
                should_retry = any(code in error_str for code in ["404", "500", "502", "503", "504", "429", "RESOURCE_EXHAUSTED", "NOT_FOUND", "ECONNRESET", "socket hang up", "ConnectionReset", "Connection reset", "ETIMEDOUT", "ECONNREFUSED", "Gateway Timeout", "timeout"])
                
                if should_retry and retry_attempt < max_retries:
                    print(f"[Proxy] ⚠️ 请求失败: {error_str}，切换凭证重试 ({retry_attempt + 2}/{max_retries + 1})", flush=True)
                    
                    # 获取新凭证
                    credential = await CredentialPool.get_available_credential(
                        db, user_id=user.id, user_has_public_creds=user_has_public,
                        model=model, exclude_ids=tried_credential_ids
                    )
                    if not credential:
                        break
                    
                    tried_credential_ids.add(credential.id)
                    access_token = await CredentialPool.get_access_token(credential, db)
                    if not access_token:
                        continue
                    
                    project_id = credential.project_id or ""
                    client = GeminiClient(access_token, project_id)
                    print(f"[Proxy] 🔄 切换到凭证: {credential.email}", flush=True)
                    continue
                
                # 失败：更新占位日志
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
                placeholder_log.retry_count = retry_attempt  # 记录重试次数
                await db.commit()
                
                raise HTTPException(status_code=status_code, detail=f"API调用失败 (已重试 {retry_attempt + 1} 次): {error_str}")
        
        # 所有重试都失败
        raise HTTPException(status_code=503, detail=f"所有凭证都失败了: {last_error}")
    
    # 流式模式的处理
    if not stream:
        return await handle_non_stream()
    
    # 流式响应：使用独立会话，不持有主db连接
    async def save_log_background(log_data: dict):
        """后台任务：更新占位日志记录（使用独立会话）"""
        try:
            async with async_session() as bg_db:
                latency = log_data.get("latency_ms", 0)
                status_code = log_data.get("status_code", 200)
                error_msg = log_data.get("error_message")
                
                # 错误分类
                error_type = None
                error_code = None
                if status_code != 200 and error_msg:
                    error_type, error_code = classify_error_simple(status_code, error_msg)
                
                # 更新占位记录
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
                    log.retry_count = log_data.get("retry_count", 0)  # 记录重试次数
                
                # 更新凭证使用次数
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
                
                # WebSocket 实时通知
                await notify_log_update({
                    "username": user.username,
                    "model": model,
                    "status_code": status_code,
                    "error_type": error_type,
                    "latency_ms": round(latency, 0),
                    "created_at": datetime.utcnow().isoformat()
                })
                await notify_stats_update()
                print(f"[Proxy] ✅ 后台日志已记录: user={user.username}, model={model}, status={status_code}", flush=True)
        except Exception as log_err:
            print(f"[Proxy] ❌ 后台日志记录失败: {log_err}", flush=True)
    
    async def stream_generator_with_retry():
        """流式生成器（使用独立会话进行数据库操作）"""
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
                
                # 成功：记录日志数据
                latency = (time.time() - start_time) * 1000
                await save_log_background({
                    "status_code": 200,
                    "cred_id": current_cred_id,
                    "cred_email": current_cred_email,
                    "latency_ms": latency,
                    "retry_count": stream_retry  # 记录重试次数
                })
                yield "data: [DONE]\n\n"
                return  # 成功，退出
                
            except Exception as e:
                error_str = str(e)
                last_error = error_str
                
                # 使用独立会话处理凭证失败
                try:
                    async with async_session() as stream_db:
                        await CredentialPool.handle_credential_failure(stream_db, current_cred_id, error_str)
                except Exception as db_err:
                    print(f"[Proxy] ⚠️ 标记凭证失败时出错: {db_err}", flush=True)
                
                # 检查是否应该重试
                should_retry = any(code in error_str for code in ["404", "500", "502", "503", "504", "429", "RESOURCE_EXHAUSTED", "NOT_FOUND", "ECONNRESET", "socket hang up", "ConnectionReset", "Connection reset", "ETIMEDOUT", "ECONNREFUSED", "Gateway Timeout", "timeout"])
                
                if should_retry and stream_retry < max_retries:
                    print(f"[Proxy] ⚠️ 流式请求失败: {error_str}，切换凭证重试 ({stream_retry + 2}/{max_retries + 1})", flush=True)
                    
                    # 🚀 使用独立会话获取新凭证
                    try:
                        async with async_session() as stream_db:
                            new_credential = await CredentialPool.get_available_credential(
                                stream_db, user_id=user.id, user_has_public_creds=user_has_public,
                                model=model, exclude_ids=tried_credential_ids
                            )
                            if new_credential:
                                tried_credential_ids.add(new_credential.id)
                                new_token = await CredentialPool.get_access_token(new_credential, stream_db)
                                if new_token:
                                    current_cred_id = new_credential.id
                                    current_cred_email = new_credential.email
                                    access_token = new_token
                                    project_id = new_credential.project_id or ""
                                    client = GeminiClient(access_token, project_id)
                                    print(f"[Proxy] 🔄 切换到凭证: {current_cred_email}", flush=True)
                                    continue
                    except Exception as retry_err:
                        print(f"[Proxy] ⚠️ 获取新凭证失败: {retry_err}", flush=True)
                
                # 无法重试，输出错误并记录日志
                status_code = extract_status_code(error_str)
                latency = (time.time() - start_time) * 1000
                await save_log_background({
                    "status_code": status_code,
                    "cred_id": current_cred_id,
                    "cred_email": current_cred_email,
                    "error_message": error_str,
                    "latency_ms": latency,
                    "retry_count": stream_retry  # 记录重试次数
                })
                yield f"data: {json.dumps({'error': f'API Error (已重试 {stream_retry + 1} 次): {error_str}'})}\n\n"
                return
    
    return StreamingResponse(
        stream_generator_with_retry(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )


# ===== Gemini 原生接口支持 =====
# 注意：由于 URL 规范化中间件的存在，以下路径都会被自动匹配：
# - /v1beta/models/... (标准路径)
# - /v1/v1beta/models/... (SillyTavern 等客户端可能添加 /v1 前缀)
# - /ABC/v1beta/models/... (用户错误添加任意前缀)

@router.options("/v1beta/models/{model:path}:generateContent")
@router.options("/v1beta/models/{model:path}:streamGenerateContent")
async def gemini_options_handler(model: str):
    """Gemini 接口 CORS 预检"""
    return JSONResponse(content={}, headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "*",
    })


@router.get("/v1beta/models")
async def list_gemini_models(request: Request, user: User = Depends(get_user_from_api_key), db: AsyncSession = Depends(get_db)):
    """Gemini 格式模型列表"""
    # 检查是否有可用的 3.0 凭证
    has_tier3 = await CredentialPool.has_tier3_credentials(user, db)
    
    base_models = ["gemini-2.5-pro", "gemini-2.5-flash"]
    if has_tier3:
        base_models.append("gemini-3-pro-preview")
        base_models.append("gemini-3-flash-preview")
    
    models = []
    for base in base_models:
        models.append({
            "name": f"models/{base}",
            "version": "001",
            "displayName": base,
            "description": f"Gemini {base} model",
            "inputTokenLimit": 1000000,
            "outputTokenLimit": 65536,
            "supportedGenerationMethods": ["generateContent", "streamGenerateContent"],
        })
    
    return {"models": models}


@router.post("/v1beta/models/{model:path}:generateContent")
async def gemini_generate_content(
    model: str,
    request: Request,
    user: User = Depends(get_user_from_api_key),
    db: AsyncSession = Depends(get_db)
):
    """Gemini 原生 generateContent 接口（带重试功能）"""
    import httpx
    start_time = time.time()
    
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="无效的JSON请求体")
    
    contents = body.get("contents", [])
    if not contents:
        raise HTTPException(status_code=400, detail="contents不能为空")
    
    # 清理模型名（移除 models/ 前缀）
    if model.startswith("models/"):
        model = model[7:]
    
    # 检查用户是否参与大锅饭
    user_has_public = await CredentialPool.check_user_has_public_creds(db, user.id)
    
    # 速率限制 - 管理员豁免
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
            raise HTTPException(status_code=429, detail=f"速率限制: {max_rpm} 次/分钟")
    
    # 构建请求体（只构建一次）
    url = "https://cloudcode-pa.googleapis.com/v1internal:generateContent"
    request_body = {"contents": contents}
    if "generationConfig" in body:
        gen_config = body["generationConfig"].copy() if isinstance(body["generationConfig"], dict) else body["generationConfig"]
        # 防呆设计：topK 有效范围为 1-64
        if isinstance(gen_config, dict) and "topK" in gen_config:
            if gen_config["topK"] is not None and (gen_config["topK"] < 1 or gen_config["topK"] > 64):
                print(f"[Gemini API] ⚠️ topK={gen_config['topK']} 超出有效范围(1-64)，已自动调整为 64", flush=True)
                gen_config["topK"] = 64
        # 防呆设计：maxOutputTokens 有效范围为 1-65536
        if isinstance(gen_config, dict) and "maxOutputTokens" in gen_config:
            if gen_config["maxOutputTokens"] is not None and (gen_config["maxOutputTokens"] < 1 or gen_config["maxOutputTokens"] > 65536):
                print(f"[Gemini API] ⚠️ maxOutputTokens={gen_config['maxOutputTokens']} 超出有效范围(1-65536)，已自动调整为 65536", flush=True)
                gen_config["maxOutputTokens"] = 65536
        request_body["generationConfig"] = gen_config
    if "systemInstruction" in body:
        request_body["systemInstruction"] = body["systemInstruction"]
    if "safetySettings" in body:
        request_body["safetySettings"] = body["safetySettings"]
    if "tools" in body:
        request_body["tools"] = body["tools"]
    
    # 重试逻辑
    max_retries = settings.error_retry_count
    tried_credential_ids = set()
    last_error = None
    credential = None
    access_token = None
    project_id = ""
    
    for retry_attempt in range(max_retries + 1):
        # 获取凭证
        credential = await CredentialPool.get_available_credential(
            db, user_id=user.id, user_has_public_creds=user_has_public, model=model,
            exclude_ids=tried_credential_ids
        )
        if not credential:
            if retry_attempt == 0:
                raise HTTPException(status_code=503, detail="暂无可用凭证")
            break  # 无更多凭证可用，退出重试
        
        tried_credential_ids.add(credential.id)
        
        access_token = await CredentialPool.get_access_token(credential, db)
        if not access_token:
            print(f"[Gemini API] ⚠️ 凭证 {credential.email} Token 刷新失败，尝试下一个", flush=True)
            continue
        
        project_id = credential.project_id or ""
        print(f"[Gemini API] 使用凭证: {credential.email}, project_id: {project_id}, model: {model}" +
              (f" (重试 {retry_attempt}/{max_retries})" if retry_attempt > 0 else ""), flush=True)
        
        payload = {"model": model, "project": project_id, "request": request_body}
        
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                    json=payload
                )
                
                if response.status_code == 200:
                    # 成功：记录日志
                    latency = (time.time() - start_time) * 1000
                    log = UsageLog(
                        user_id=user.id,
                        credential_id=credential.id,
                        model=model,
                        endpoint="/v1beta/generateContent",
                        status_code=200,
                        latency_ms=latency,
                        credential_email=credential.email
                    )
                    db.add(log)
                    credential.total_requests = (credential.total_requests or 0) + 1
                    credential.last_used_at = datetime.utcnow()
                    await db.commit()
                    
                    # WebSocket 实时通知
                    await notify_log_update({
                        "username": user.username,
                        "model": model,
                        "status_code": 200,
                        "latency_ms": round(latency, 0),
                        "created_at": datetime.utcnow().isoformat()
                    })
                    await notify_stats_update()
                    
                    # 转换响应格式
                    result = response.json()
                    if "response" in result:
                        standard_result = result.get("response", {})
                        if "modelVersion" in result:
                            standard_result["modelVersion"] = result["modelVersion"]
                        return JSONResponse(content=standard_result)
                    return JSONResponse(content=result)
                
                # 请求失败
                error_text = response.text[:500]
                last_error = f"API Error {response.status_code}: {error_text}"
                print(f"[Gemini API] ❌ 错误 {response.status_code}: {error_text}", flush=True)
                
                # 处理凭证失败
                cd_sec = None
                if response.status_code in [401, 403]:
                    await CredentialPool.handle_credential_failure(db, credential.id, last_error)
                elif response.status_code == 429:
                    cd_sec = await CredentialPool.handle_429_rate_limit(
                        db, credential.id, model, error_text, dict(response.headers)
                    )
                
                # ✅ 每次尝试都记录日志（包括中间的重试）
                attempt_latency = (time.time() - start_time) * 1000
                error_type, error_code = classify_error_simple(response.status_code, error_text)
                log = UsageLog(
                    user_id=user.id,
                    credential_id=credential.id,
                    model=model,
                    endpoint="/v1beta/generateContent",
                    status_code=response.status_code,
                    latency_ms=attempt_latency,
                    cd_seconds=cd_sec,
                    error_message=error_text[:2000],
                    error_type=error_type,
                    error_code=error_code,
                    credential_email=credential.email
                )
                db.add(log)
                credential.total_requests = (credential.total_requests or 0) + 1
                credential.last_used_at = datetime.utcnow()
                await db.commit()
                
                # WebSocket 实时通知
                await notify_log_update({
                    "username": user.username,
                    "model": model,
                    "status_code": response.status_code,
                    "error_type": error_type,
                    "latency_ms": round(attempt_latency, 0),
                    "created_at": datetime.utcnow().isoformat()
                })
                await notify_stats_update()
                
                # 检查是否应该重试
                should_retry = response.status_code in [429, 500, 503, 404]
                if should_retry and retry_attempt < max_retries:
                    print(f"[Gemini API] 🔄 切换凭证重试 ({retry_attempt + 2}/{max_retries + 1})", flush=True)
                    continue
                
                # 不重试，返回错误
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"API调用失败 (已重试 {retry_attempt + 1} 次): {response.text}"
                )
                
        except HTTPException:
            raise
        except Exception as e:
            error_str = str(e)
            last_error = error_str
            print(f"[Gemini API] ❌ 异常: {error_str}", flush=True)
            
            if credential:
                await CredentialPool.handle_credential_failure(db, credential.id, error_str)
            
            # ✅ 每次尝试都记录日志（包括中间的重试）
            status_code = extract_status_code(error_str)
            attempt_latency = (time.time() - start_time) * 1000
            error_type, error_code = classify_error_simple(status_code, error_str)
            log = UsageLog(
                user_id=user.id,
                credential_id=credential.id if credential else None,
                model=model,
                endpoint="/v1beta/generateContent",
                status_code=status_code,
                latency_ms=attempt_latency,
                error_message=error_str[:2000],
                error_type=error_type,
                error_code=error_code,
                credential_email=credential.email if credential else None
            )
            db.add(log)
            if credential:
                credential.total_requests = (credential.total_requests or 0) + 1
                credential.last_used_at = datetime.utcnow()
            await db.commit()
            
            # WebSocket 实时通知
            await notify_log_update({
                "username": user.username,
                "model": model,
                "status_code": status_code,
                "error_type": error_type,
                "latency_ms": round(attempt_latency, 0),
                "created_at": datetime.utcnow().isoformat()
            })
            await notify_stats_update()
            
            # 检查是否应该重试
            should_retry = any(code in error_str for code in ["429", "500", "503", "RESOURCE_EXHAUSTED", "ECONNRESET", "ETIMEDOUT"])
            if should_retry and retry_attempt < max_retries:
                print(f"[Gemini API] 🔄 切换凭证重试 ({retry_attempt + 2}/{max_retries + 1})", flush=True)
                continue
            
            # 不重试，返回错误
            raise HTTPException(
                status_code=status_code,
                detail=f"API调用失败 (已重试 {retry_attempt + 1} 次): {error_str}"
            )
    
    # 所有重试都失败
    raise HTTPException(status_code=503, detail=f"所有凭证都失败了: {last_error}")


@router.post("/v1beta/models/{model:path}:streamGenerateContent")
async def gemini_stream_generate_content(
    model: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_user_from_api_key),
    db: AsyncSession = Depends(get_db)
):
    """Gemini 原生 streamGenerateContent 接口（带重试功能）"""
    import httpx
    start_time = time.time()
    
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="无效的JSON请求体")
    
    contents = body.get("contents", [])
    if not contents:
        raise HTTPException(status_code=400, detail="contents不能为空")
    
    # 清理模型名
    if model.startswith("models/"):
        model = model[7:]
    
    # 检查用户是否参与大锅饭
    user_has_public = await CredentialPool.check_user_has_public_creds(db, user.id)
    
    # 速率限制 - 管理员豁免
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
            raise HTTPException(status_code=429, detail=f"速率限制: {max_rpm} 次/分钟")
    
    # 构建请求体（只构建一次）
    url = "https://cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse"
    request_body = {"contents": contents}
    if "generationConfig" in body:
        gen_config = body["generationConfig"].copy() if isinstance(body["generationConfig"], dict) else body["generationConfig"]
        # 防呆设计：topK 有效范围为 1-64
        if isinstance(gen_config, dict) and "topK" in gen_config:
            if gen_config["topK"] is not None and (gen_config["topK"] < 1 or gen_config["topK"] > 64):
                print(f"[Gemini Stream] ⚠️ topK={gen_config['topK']} 超出有效范围(1-64)，已自动调整为 64", flush=True)
                gen_config["topK"] = 64
        # 防呆设计：maxOutputTokens 有效范围为 1-65536
        if isinstance(gen_config, dict) and "maxOutputTokens" in gen_config:
            if gen_config["maxOutputTokens"] is not None and (gen_config["maxOutputTokens"] < 1 or gen_config["maxOutputTokens"] > 65536):
                print(f"[Gemini Stream] ⚠️ maxOutputTokens={gen_config['maxOutputTokens']} 超出有效范围(1-65536)，已自动调整为 65536", flush=True)
                gen_config["maxOutputTokens"] = 65536
        request_body["generationConfig"] = gen_config
    if "systemInstruction" in body:
        request_body["systemInstruction"] = body["systemInstruction"]
    if "safetySettings" in body:
        request_body["safetySettings"] = body["safetySettings"]
    if "tools" in body:
        request_body["tools"] = body["tools"]
    
    # 预先获取第一个凭证（使用主db）
    max_retries = settings.error_retry_count
    tried_credential_ids = set()
    
    credential = await CredentialPool.get_available_credential(
        db, user_id=user.id, user_has_public_creds=user_has_public, model=model,
        exclude_ids=tried_credential_ids
    )
    if not credential:
        raise HTTPException(status_code=503, detail="暂无可用凭证")
    
    tried_credential_ids.add(credential.id)
    
    access_token = await CredentialPool.get_access_token(credential, db)
    if not access_token:
        raise HTTPException(status_code=503, detail="凭证已失效")
    
    project_id = credential.project_id or ""
    first_credential_id = credential.id
    first_credential_email = credential.email
    user_id = user.id
    username = user.username
    print(f"[Gemini Stream] 使用凭证: {credential.email}, project_id: {project_id}, model: {model}", flush=True)
    
    # ✅ 主db连接到此处结束使用，流式生成器将使用独立会话
    
    # 后台任务：记录日志（使用独立会话）
    async def save_log_background(log_data: dict):
        try:
            async with async_session() as bg_db:
                latency = log_data.get("latency_ms", 0)
                status_code = log_data.get("status_code", 200)
                error_msg = log_data.get("error_message")
                cred_id = log_data.get("cred_id")
                cred_email = log_data.get("cred_email")
                
                # 错误分类
                error_type = None
                error_code = None
                if status_code != 200 and error_msg:
                    error_type, error_code = classify_error_simple(status_code, error_msg)
                
                log = UsageLog(
                    user_id=user_id,
                    credential_id=cred_id,
                    model=model,
                    endpoint="/v1beta/streamGenerateContent",
                    status_code=status_code,
                    latency_ms=latency,
                    cd_seconds=log_data.get("cd_seconds"),
                    error_message=error_msg[:2000] if error_msg else None,
                    error_type=error_type,
                    error_code=error_code,
                    credential_email=cred_email
                )
                bg_db.add(log)
                
                # 更新凭证使用次数
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
                
                # WebSocket 实时通知
                await notify_log_update({
                    "username": username,
                    "model": model,
                    "status_code": status_code,
                    "error_type": error_type,
                    "latency_ms": round(latency, 0),
                    "created_at": datetime.utcnow().isoformat()
                })
                await notify_stats_update()
                print(f"[Gemini Stream] ✅ 后台日志已记录: user={username}, model={model}, status={status_code}", flush=True)
        except Exception as log_err:
            print(f"[Gemini Stream] ❌ 后台日志记录失败: {log_err}", flush=True)
    
    async def stream_generator_with_retry():
        """🚀 流式生成器（带重试功能，使用独立会话进行数据库操作）"""
        nonlocal access_token, project_id, tried_credential_ids
        current_cred_id = first_credential_id
        current_cred_email = first_credential_email
        last_error = None
        
        for stream_retry in range(max_retries + 1):
            cd_seconds = None
            payload = {"model": model, "project": project_id, "request": request_body}
            
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    async with client.stream(
                        "POST", url,
                        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                        json=payload
                    ) as response:
                        if response.status_code != 200:
                            # 一开始就报错，可以重试
                            error = await response.aread()
                            error_text = error.decode()[:500]
                            last_error = f"API Error {response.status_code}: {error_text}"
                            print(f"[Gemini Stream] ❌ 错误 {response.status_code}: {error_text}", flush=True)
                            
                            # 使用独立会话处理凭证失败
                            try:
                                async with async_session() as stream_db:
                                    if response.status_code in [401, 403]:
                                        await CredentialPool.handle_credential_failure(stream_db, current_cred_id, last_error)
                                    elif response.status_code == 429:
                                        cd_seconds = await CredentialPool.handle_429_rate_limit(
                                            stream_db, current_cred_id, model, error_text, dict(response.headers)
                                        )
                            except Exception as db_err:
                                print(f"[Gemini Stream] ⚠️ 处理凭证失败时出错: {db_err}", flush=True)
                            
                            # ✅ 每次尝试都记录日志（包括中间的重试）
                            attempt_latency = (time.time() - start_time) * 1000
                            background_tasks.add_task(save_log_background, {
                                "status_code": response.status_code,
                                "error_message": error_text,
                                "latency_ms": attempt_latency,
                                "cd_seconds": cd_seconds,
                                "cred_id": current_cred_id,
                                "cred_email": current_cred_email
                            })
                            
                            # 检查是否应该重试
                            should_retry = response.status_code in [429, 500, 503, 404]
                            if should_retry and stream_retry < max_retries:
                                print(f"[Gemini Stream] 🔄 切换凭证重试 ({stream_retry + 2}/{max_retries + 1})", flush=True)
                                
                                # 使用独立会话获取新凭证
                                try:
                                    async with async_session() as stream_db:
                                        new_credential = await CredentialPool.get_available_credential(
                                            stream_db, user_id=user_id, user_has_public_creds=user_has_public,
                                            model=model, exclude_ids=tried_credential_ids
                                        )
                                        if new_credential:
                                            tried_credential_ids.add(new_credential.id)
                                            new_token = await CredentialPool.get_access_token(new_credential, stream_db)
                                            if new_token:
                                                current_cred_id = new_credential.id
                                                current_cred_email = new_credential.email
                                                access_token = new_token
                                                project_id = new_credential.project_id or ""
                                                print(f"[Gemini Stream] 🔄 切换到凭证: {current_cred_email}", flush=True)
                                                continue
                                except Exception as retry_err:
                                    print(f"[Gemini Stream] ⚠️ 获取新凭证失败: {retry_err}", flush=True)
                            
                            # 无法重试，输出错误（日志已记录）
                            yield f"data: {json.dumps({'error': f'API Error (已重试 {stream_retry + 1} 次): {error.decode()}'})}\n\n"
                            return
                        
                        # 响应成功，开始输出数据（此后无法重试）
                        async for line in response.aiter_lines():
                            if line:
                                # 转换 SSE 数据格式
                                if line.startswith("data: "):
                                    try:
                                        data = json.loads(line[6:])
                                        if "response" in data:
                                            standard_data = data.get("response", {})
                                            if "modelVersion" in data:
                                                standard_data["modelVersion"] = data["modelVersion"]
                                            yield f"data: {json.dumps(standard_data)}\n\n"
                                        else:
                                            yield f"{line}\n"
                                    except:
                                        yield f"{line}\n"
                                else:
                                    yield f"{line}\n"
                
                # 成功：后台记录日志
                latency = (time.time() - start_time) * 1000
                background_tasks.add_task(save_log_background, {
                    "status_code": 200,
                    "latency_ms": latency,
                    "cred_id": current_cred_id,
                    "cred_email": current_cred_email
                })
                return  # 成功，退出
                
            except Exception as e:
                error_str = str(e)
                last_error = error_str
                
                # 使用独立会话处理凭证失败
                try:
                    async with async_session() as stream_db:
                        await CredentialPool.handle_credential_failure(stream_db, current_cred_id, error_str)
                except Exception as db_err:
                    print(f"[Gemini Stream] ⚠️ 标记凭证失败时出错: {db_err}", flush=True)
                
                # ✅ 每次尝试都记录日志（包括中间的重试）
                status_code = extract_status_code(error_str)
                attempt_latency = (time.time() - start_time) * 1000
                background_tasks.add_task(save_log_background, {
                    "status_code": status_code,
                    "error_message": error_str,
                    "latency_ms": attempt_latency,
                    "cred_id": current_cred_id,
                    "cred_email": current_cred_email
                })
                
                # 检查是否应该重试
                should_retry = any(code in error_str for code in ["429", "500", "503", "RESOURCE_EXHAUSTED", "ECONNRESET", "ETIMEDOUT"])
                
                if should_retry and stream_retry < max_retries:
                    print(f"[Gemini Stream] ⚠️ 流式请求失败: {error_str}，切换凭证重试 ({stream_retry + 2}/{max_retries + 1})", flush=True)
                    
                    # 使用独立会话获取新凭证
                    try:
                        async with async_session() as stream_db:
                            new_credential = await CredentialPool.get_available_credential(
                                stream_db, user_id=user_id, user_has_public_creds=user_has_public,
                                model=model, exclude_ids=tried_credential_ids
                            )
                            if new_credential:
                                tried_credential_ids.add(new_credential.id)
                                new_token = await CredentialPool.get_access_token(new_credential, stream_db)
                                if new_token:
                                    current_cred_id = new_credential.id
                                    current_cred_email = new_credential.email
                                    access_token = new_token
                                    project_id = new_credential.project_id or ""
                                    print(f"[Gemini Stream] 🔄 切换到凭证: {current_cred_email}", flush=True)
                                    continue
                    except Exception as retry_err:
                        print(f"[Gemini Stream] ⚠️ 获取新凭证失败: {retry_err}", flush=True)
                
                # 无法重试，输出错误（日志已记录）
                yield f"data: {json.dumps({'error': f'API Error (已重试 {stream_retry + 1} 次): {error_str}'})}\n\n"
                return
    
    return StreamingResponse(
        stream_generator_with_retry(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )


# ===== OpenAI 原生反代 =====

@router.api_route("/openai/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def openai_proxy(
    path: str,
    request: Request,
    user: User = Depends(get_user_from_api_key),
    db: AsyncSession = Depends(get_db)
):
    """OpenAI 原生 API 反代 - 直接转发到 OpenAI"""
    import httpx
    
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="未配置 OpenAI API Key，无法使用 OpenAI 反代")
    
    start_time = time.time()
    
    # 检查速率限制 - 管理员豁免
    user_has_public = await CredentialPool.check_user_has_public_creds(db, user.id)
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
            raise HTTPException(status_code=429, detail=f"速率限制: {max_rpm} 次/分钟")
    
    # 构建目标 URL
    target_url = f"{settings.openai_api_base}/{path}"
    if request.query_params:
        target_url += f"?{request.query_params}"
    
    # 获取请求体
    body = None
    if request.method in ["POST", "PUT", "PATCH"]:
        body = await request.body()
    
    # 构建请求头（替换 Authorization）
    headers = dict(request.headers)
    headers["Authorization"] = f"Bearer {settings.openai_api_key}"
    # 移除 host 头
    headers.pop("host", None)
    headers.pop("Host", None)
    
    # 记录日志
    async def log_usage(status_code: int = 200, error_msg: str = None):
        latency = (time.time() - start_time) * 1000
        
        # 错误分类
        error_type = None
        error_code = None
        if status_code != 200 and error_msg:
            error_type, error_code = classify_error_simple(status_code, error_msg)
        
        log = UsageLog(
            user_id=user.id,
            credential_id=None,
            model="openai",
            endpoint=f"/openai/{path}",
            status_code=status_code,
            latency_ms=latency,
            error_message=error_msg[:2000] if error_msg else None,
            error_type=error_type,
            error_code=error_code
        )
        db.add(log)
        await db.commit()
        await notify_log_update({
            "username": user.username,
            "model": "openai",
            "status_code": status_code,
            "error_type": error_type,
            "latency_ms": round(latency, 0),
            "created_at": datetime.utcnow().isoformat()
        })
        await notify_stats_update()
    
    # 判断是否是流式请求
    is_stream = False
    if body:
        try:
            body_json = json.loads(body)
            is_stream = body_json.get("stream", False)
        except:
            pass
    
    print(f"[OpenAI Proxy] {request.method} {target_url}, stream={is_stream}", flush=True)
    
    try:
        if is_stream:
            # 流式响应
            async def stream_generator():
                try:
                    async with httpx.AsyncClient(timeout=120.0) as client:
                        async with client.stream(
                            request.method, target_url,
                            headers=headers,
                            content=body
                        ) as response:
                            if response.status_code != 200:
                                error = await response.aread()
                                await log_usage(response.status_code, error_msg=error.decode()[:500])
                                yield f"data: {json.dumps({'error': error.decode()})}\n\n"
                                return
                            
                            async for line in response.aiter_lines():
                                if line:
                                    yield f"{line}\n"
                    
                    await log_usage()
                except Exception as e:
                    error_str = str(e)
                    status_code = extract_status_code(error_str)
                    await log_usage(status_code, error_msg=error_str)
                    yield f"data: {json.dumps({'error': error_str})}\n\n"
            
            return StreamingResponse(
                stream_generator(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
            )
        else:
            # 非流式响应
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.request(
                    request.method, target_url,
                    headers=headers,
                    content=body
                )
                
                await log_usage(response.status_code)
                
                # 返回响应
                return JSONResponse(
                    content=response.json() if response.headers.get("content-type", "").startswith("application/json") else {"text": response.text},
                    status_code=response.status_code
                )
    
    except Exception as e:
        error_str = str(e)
        status_code = extract_status_code(error_str)
        await log_usage(status_code, error_msg=error_str)
        raise HTTPException(status_code=status_code, detail=f"OpenAI API 请求失败: {error_str}")
