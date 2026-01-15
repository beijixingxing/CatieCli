"""Antigravity OAuth 认证路由 - 独立的凭证获取功能"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
import httpx
import secrets
from urllib.parse import urlencode, urlparse, parse_qs

from app.database import get_db
from app.models.user import User, Credential
from app.services.auth import get_current_user
from app.config import settings
from app.services.crypto import encrypt_credential

router = APIRouter(prefix="/api/agy-oauth", tags=["Antigravity OAuth"])

# ===== Antigravity OAuth 配置 =====
# 与 GeminiCLI 不同的 Client ID/Secret
ANTIGRAVITY_CLIENT_ID = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
ANTIGRAVITY_CLIENT_SECRET = "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"

# Antigravity 需要的额外 Scopes
ANTIGRAVITY_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/cclog",
    "https://www.googleapis.com/auth/experimentsandconfigs"
]

# Antigravity API URL
ANTIGRAVITY_API_URL = "https://daily-cloudcode-pa.sandbox.googleapis.com"

# Antigravity User-Agent
ANTIGRAVITY_USER_AGENT = "antigravity/1.11.3 windows/amd64"

# OAuth URLs
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


class CallbackURLRequest(BaseModel):
    callback_url: str
    is_public: bool = False


async def fetch_antigravity_project_id(access_token: str) -> Optional[str]:
    """
    使用 Antigravity API 获取 project_id
    优先使用 loadCodeAssist，失败后回退到 onboardUser
    """
    headers = {
        'User-Agent': ANTIGRAVITY_USER_AGENT,
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept-Encoding': 'gzip'
    }
    
    # 步骤 1: 尝试 loadCodeAssist
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            request_url = f"{ANTIGRAVITY_API_URL}/v1internal:loadCodeAssist"
            request_body = {
                "metadata": {
                    "ideType": "ANTIGRAVITY",
                    "platform": "PLATFORM_UNSPECIFIED",
                    "pluginType": "GEMINI"
                }
            }
            
            print(f"[Antigravity OAuth] 尝试 loadCodeAssist: {request_url}", flush=True)
            response = await client.post(request_url, json=request_body, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                print(f"[Antigravity OAuth] loadCodeAssist 响应: {data}", flush=True)
                
                # 检查是否已激活
                current_tier = data.get("currentTier")
                if current_tier:
                    project_id = data.get("cloudaicompanionProject")
                    if project_id:
                        print(f"[Antigravity OAuth] 成功获取 project_id: {project_id}", flush=True)
                        return project_id
                    print("[Antigravity OAuth] loadCodeAssist 响应中没有 project_id", flush=True)
                else:
                    print("[Antigravity OAuth] 用户未激活，需要 onboardUser", flush=True)
            else:
                print(f"[Antigravity OAuth] loadCodeAssist 失败: {response.status_code}", flush=True)
    except Exception as e:
        print(f"[Antigravity OAuth] loadCodeAssist 异常: {e}", flush=True)
    
    # 步骤 2: 回退到 onboardUser
    try:
        # 先获取 tier 信息
        tier_id = await _get_onboard_tier(access_token, headers)
        if not tier_id:
            print("[Antigravity OAuth] 无法获取 tier 信息", flush=True)
            return None
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            request_url = f"{ANTIGRAVITY_API_URL}/v1internal:onboardUser"
            request_body = {
                "tierId": tier_id,
                "metadata": {
                    "ideType": "ANTIGRAVITY",
                    "platform": "PLATFORM_UNSPECIFIED",
                    "pluginType": "GEMINI"
                }
            }
            
            print(f"[Antigravity OAuth] 尝试 onboardUser (tier={tier_id})", flush=True)
            
            # onboardUser 是长时间运行操作，需要轮询
            for attempt in range(5):
                response = await client.post(request_url, json=request_body, headers=headers)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    if data.get("done"):
                        response_data = data.get("response", {})
                        project_obj = response_data.get("cloudaicompanionProject", {})
                        
                        if isinstance(project_obj, dict):
                            project_id = project_obj.get("id")
                        elif isinstance(project_obj, str):
                            project_id = project_obj
                        else:
                            project_id = None
                        
                        if project_id:
                            print(f"[Antigravity OAuth] onboardUser 成功获取 project_id: {project_id}", flush=True)
                            return project_id
                        break
                    else:
                        print(f"[Antigravity OAuth] onboardUser 进行中... (attempt {attempt + 1})", flush=True)
                        import asyncio
                        await asyncio.sleep(2)
                else:
                    print(f"[Antigravity OAuth] onboardUser 失败: {response.status_code}", flush=True)
                    break
    except Exception as e:
        print(f"[Antigravity OAuth] onboardUser 异常: {e}", flush=True)
    
    return None


async def _get_onboard_tier(access_token: str, headers: dict) -> Optional[str]:
    """从 loadCodeAssist 响应中获取默认 tier"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            request_url = f"{ANTIGRAVITY_API_URL}/v1internal:loadCodeAssist"
            request_body = {
                "metadata": {
                    "ideType": "ANTIGRAVITY",
                    "platform": "PLATFORM_UNSPECIFIED",
                    "pluginType": "GEMINI"
                }
            }
            
            response = await client.post(request_url, json=request_body, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                allowed_tiers = data.get("allowedTiers", [])
                
                for tier in allowed_tiers:
                    if tier.get("isDefault"):
                        tier_id = tier.get("id")
                        print(f"[Antigravity OAuth] 找到默认 tier: {tier_id}", flush=True)
                        return tier_id
                
                # 如果没有默认 tier，使用 LEGACY
                print("[Antigravity OAuth] 没有默认 tier，使用 LEGACY", flush=True)
                return "LEGACY"
    except Exception as e:
        print(f"[Antigravity OAuth] 获取 tier 异常: {e}", flush=True)
    
    return None


# 存储 OAuth state
oauth_states = {}


@router.get("/auth-url")
async def get_antigravity_auth_url(
    request: Request,
    user: User = Depends(get_current_user)
):
    """获取 Antigravity OAuth 认证链接"""
    # 生成 state
    state = secrets.token_urlsafe(32)
    oauth_states[state] = {"user_id": user.id}
    
    # Antigravity OAuth 固定使用 localhost:8080 作为回调
    redirect_uri = "http://localhost:8080"
    
    # 构建 OAuth URL（使用 Antigravity 配置）
    params = {
        "client_id": ANTIGRAVITY_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": " ".join(ANTIGRAVITY_SCOPES),
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state
    }
    
    auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    
    return {
        "auth_url": auth_url,
        "state": state,
        "redirect_uri": redirect_uri
    }


@router.post("/from-callback-url")
async def antigravity_credential_from_callback_url(
    data: CallbackURLRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """从回调 URL 获取 Antigravity 凭证"""
    print(f"[Antigravity OAuth] 收到回调 URL: {data.callback_url}", flush=True)
    
    try:
        parsed = urlparse(data.callback_url)
        params = parse_qs(parsed.query)
        
        code = params.get("code", [None])[0]
        print(f"[Antigravity OAuth] 解析到 code: {code[:20] if code else 'None'}...", flush=True)
        
        if not code:
            raise HTTPException(status_code=400, detail="URL 中未找到 code 参数")
        
        # 使用 Antigravity 的 Client ID/Secret 获取 token
        redirect_uri = "http://localhost:8080"
        
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": ANTIGRAVITY_CLIENT_ID,
                    "client_secret": ANTIGRAVITY_CLIENT_SECRET,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri
                }
            )
            token_data = token_response.json()
        
        print(f"[Antigravity OAuth] Token 响应: {token_data}", flush=True)
        
        if "error" in token_data:
            error_msg = token_data.get("error_description") or token_data.get("error", "获取 token 失败")
            raise HTTPException(status_code=400, detail=error_msg)
        
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        
        # 获取用户信息
        async with httpx.AsyncClient() as client:
            userinfo_response = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"}
            )
            userinfo = userinfo_response.json()
        
        email = userinfo.get("email", "unknown")
        print(f"[Antigravity OAuth] 用户邮箱: {email}", flush=True)
        
        # 使用 Antigravity API 获取 project_id
        project_id = await fetch_antigravity_project_id(access_token)
        
        if not project_id:
            # 如果获取失败，生成随机 project_id
            import uuid
            random_id = uuid.uuid4().hex[:8]
            project_id = f"projects/random-{random_id}/locations/global"
            print(f"[Antigravity OAuth] 使用随机 project_id: {project_id}", flush=True)
        
        # 检查是否已存在相同邮箱的 Antigravity 凭证
        from sqlalchemy import select
        existing_cred = await db.execute(
            select(Credential).where(
                Credential.user_id == user.id,
                Credential.email == email,
                Credential.api_type == "antigravity"
            )
        )
        existing = existing_cred.scalar_one_or_none()
        
        if existing:
            # 更新现有凭证
            existing.api_key = encrypt_credential(access_token)
            existing.refresh_token = encrypt_credential(refresh_token)
            existing.project_id = project_id
            credential = existing
            is_new_credential = False
            print(f"[Antigravity OAuth] 更新现有凭证: {email}", flush=True)
        else:
            # 创建新凭证
            credential = Credential(
                user_id=user.id,
                name=f"Antigravity - {email}",
                api_key=encrypt_credential(access_token),
                refresh_token=encrypt_credential(refresh_token),
                project_id=project_id,
                credential_type="oauth",
                email=email,
                is_public=data.is_public,
                api_type="antigravity"  # 标记为 Antigravity 凭证
            )
            is_new_credential = True
            print(f"[Antigravity OAuth] 创建新凭证: {email}", flush=True)
        
        # 验证凭证是否有效（使用 Antigravity API）
        is_valid = True
        detected_tier = "2.5"
        try:
            async with httpx.AsyncClient(timeout=30.0) as test_client:
                # 使用 Antigravity API 端点测试
                test_url = f"{ANTIGRAVITY_API_URL}/v1internal:generateContent"
                test_payload = {
                    "model": "gemini-2.5-flash",
                    "project": project_id,
                    "request": {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}
                }
                test_headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "User-Agent": ANTIGRAVITY_USER_AGENT
                }
                test_response = await test_client.post(test_url, headers=test_headers, json=test_payload)
                
                if test_response.status_code == 200 or test_response.status_code == 429:
                    print(f"[Antigravity OAuth] ✅ 凭证有效", flush=True)
                    # 测试 3.0 模型资格
                    test_payload_3 = {
                        "model": "gemini-3-pro-preview",
                        "project": project_id,
                        "request": {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}
                    }
                    test_response_3 = await test_client.post(test_url, headers=test_headers, json=test_payload_3)
                    if test_response_3.status_code == 200 or test_response_3.status_code == 429:
                        detected_tier = "3"
                        print(f"[Antigravity OAuth] 🎉 检测到 Gemini 3 资格！", flush=True)
                elif test_response.status_code in [401, 403]:
                    is_valid = False
                    print(f"[Antigravity OAuth] ❌ 凭证无效: {test_response.status_code}", flush=True)
        except Exception as ve:
            print(f"[Antigravity OAuth] ⚠️ 验证失败: {ve}", flush=True)
        
        credential.model_tier = detected_tier
        credential.is_active = is_valid
        
        if is_new_credential:
            db.add(credential)
        
        # 奖励用户额度（只有新凭证、捐赠且有效才奖励）
        reward_quota = 0
        if is_new_credential and data.is_public and is_valid:
            if detected_tier == "3":
                reward_quota = settings.quota_flash + settings.quota_25pro + settings.quota_30pro
            else:
                reward_quota = settings.quota_flash + settings.quota_25pro
            user.daily_quota += reward_quota
            print(f"[Antigravity OAuth] 用户 {user.username} 获得 {reward_quota} 额度奖励 (等级: {detected_tier})", flush=True)
        
        await db.commit()
        
        # 构建返回消息
        msg_parts = ["凭证更新成功" if not is_new_credential else "凭证获取成功"]
        if not is_new_credential:
            msg_parts.append("（已存在相同邮箱凭证，已更新token）")
        if not is_valid:
            msg_parts.append("⚠️ 凭证验证失败，已禁用")
        else:
            msg_parts.append(f"✅ 等级: {detected_tier}")
            if detected_tier == "3":
                msg_parts.append("🎉 支持 Gemini 3！")
        if reward_quota:
            msg_parts.append(f"奖励 +{reward_quota} 额度")
        
        return {
            "message": "，".join(msg_parts),
            "email": email,
            "is_public": data.is_public,
            "credential_id": credential.id,
            "reward_quota": reward_quota,
            "is_valid": is_valid,
            "model_tier": detected_tier,
            "project_id": project_id
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"[Antigravity OAuth] 异常: {e}", flush=True)
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")