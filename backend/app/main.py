from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import os

from app.database import init_db, async_session
from app.models.user import User
from app.services.auth import get_password_hash
from app.config import settings, load_config_from_db
from app.routers import auth, proxy, admin, oauth, ws, manage
from sqlalchemy import select


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化
    await init_db()
    
    # 从数据库加载持久化配置
    try:
        await load_config_from_db()
        print("✅ 已加载持久化配置")
    except Exception as e:
        print(f"⚠️ 加载配置失败: {e}")
    
    # 创建或更新管理员账号，确保只有配置的用户名是管理员
    async with async_session() as db:
        # 先把其他管理员降级为普通用户
        other_admins = await db.execute(
            select(User).where(User.is_admin == True, User.username != settings.admin_username)
        )
        for other in other_admins.scalars().all():
            other.is_admin = False
            print(f"⚠️ 降级旧管理员: {other.username}")
        
        # 创建或更新配置的管理员
        result = await db.execute(select(User).where(User.username == settings.admin_username))
        admin_user = result.scalar_one_or_none()
        if not admin_user:
            admin_user = User(
                username=settings.admin_username,
                hashed_password=get_password_hash(settings.admin_password),
                is_admin=True,
                daily_quota=999999
            )
            db.add(admin_user)
            print(f"✅ 创建管理员账号: {settings.admin_username}")
        else:
            # 更新管理员密码（确保 .env 修改后生效）
            admin_user.hashed_password = get_password_hash(settings.admin_password)
            admin_user.is_admin = True
            print(f"✅ 已同步管理员账号: {settings.admin_username}")
        
        await db.commit()
    
    yield


app = FastAPI(
    title="Catiecli",
    description="🐱 Catiecli - Gemini API 多用户代理服务",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router)
app.include_router(proxy.router)
app.include_router(admin.router)
app.include_router(oauth.router)
app.include_router(ws.router)
app.include_router(manage.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "Catiecli"}


@app.get("/api/public/stats")
async def public_stats():
    """公共统计信息（无需登录）"""
    from sqlalchemy import select, func, and_
    from app.models.user import User, Credential, UsageLog
    from datetime import date
    
    async with async_session() as db:
        user_count = (await db.execute(select(func.count(User.id)))).scalar() or 0
        active_credentials = (await db.execute(
            select(func.count(Credential.id)).where(Credential.is_active == True)
        )).scalar() or 0
        today = date.today()
        
        # 今日成功请求 (status_code 200)
        today_success = (await db.execute(
            select(func.count(UsageLog.id)).where(
                and_(func.date(UsageLog.created_at) == today, UsageLog.status_code == 200)
            )
        )).scalar() or 0
        
        # 今日失败请求 (status_code != 200)
        today_failed = (await db.execute(
            select(func.count(UsageLog.id)).where(
                and_(func.date(UsageLog.created_at) == today, UsageLog.status_code != 200)
            )
        )).scalar() or 0
        
        return {
            "user_count": user_count,
            "active_credentials": active_credentials,
            "today_requests": today_success + today_failed,
            "today_success": today_success,
            "today_failed": today_failed
        }


# 静态文件服务 (前端)
frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.exists(frontend_path):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_path, "assets")), name="assets")
    
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        file_path = os.path.join(frontend_path, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(frontend_path, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
