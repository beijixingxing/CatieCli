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
from app.routers import auth, proxy, admin, oauth, ws, manage, error_config
from app.routers.test import router as test_router
from app.routers import antigravity_proxy, antigravity_manage, antigravity_oauth
from app.middleware.url_normalize import URLNormalizeMiddleware
from sqlalchemy import select


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    from datetime import datetime, timedelta
    from sqlalchemy import delete
    from app.models.user import UsageLog
    
    # 启动时初始化
    await init_db()
    
    # 自动添加缺失的数据库列（简单迁移）
    try:
        async with async_session() as db:
            from sqlalchemy import text
            # 检查并添加 retry_count 列
            try:
                await db.execute(text("SELECT retry_count FROM usage_logs LIMIT 1"))
            except Exception:
                print("🔄 正在添加 retry_count 列...")
                try:
                    await db.execute(text("ALTER TABLE usage_logs ADD COLUMN retry_count INTEGER DEFAULT 0"))
                    await db.commit()
                    print("✅ 成功添加 retry_count 列")
                except Exception as e:
                    print(f"⚠️ 添加 retry_count 列失败（可能已存在）: {e}")
    except Exception as e:
        print(f"⚠️ 数据库迁移检查失败: {e}")
    
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
    
    # 定时清理过期日志的后台任务
    async def cleanup_old_logs():
        while True:
            try:
                retention_days = settings.log_retention_days
                if retention_days > 0:
                    cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
                    async with async_session() as db:
                        result = await db.execute(
                            delete(UsageLog).where(UsageLog.created_at < cutoff_date)
                        )
                        deleted_count = result.rowcount
                        await db.commit()
                        if deleted_count > 0:
                            print(f"🗑️ 自动清理了 {deleted_count} 条过期日志（{retention_days}天前）")
            except Exception as e:
                print(f"⚠️ 日志清理失败: {e}")
            
            # 每24小时执行一次
            await asyncio.sleep(86400)
    
    # 启动后台清理任务
    cleanup_task = asyncio.create_task(cleanup_old_logs())
    print("✅ 已启动日志自动清理任务")
    
    yield
    
    # 关闭时取消后台任务
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


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

# URL 规范化中间件（防呆设计：处理用户错误添加的 URL 前缀）
# 注意：ASGI 中间件的执行顺序是后添加先执行，所以这个中间件会在 CORS 之后执行
app.add_middleware(URLNormalizeMiddleware)

# 注册路由
app.include_router(auth.router)
app.include_router(proxy.router)
app.include_router(admin.router)
app.include_router(oauth.router)
app.include_router(ws.router)
app.include_router(manage.router)
app.include_router(error_config.router)  # 自定义错误消息配置
app.include_router(test_router)  # 测试接口（用于模拟报错场景）
app.include_router(antigravity_proxy.router)  # Antigravity API 反代
app.include_router(antigravity_manage.router)  # Antigravity 凭证管理
app.include_router(antigravity_oauth.router)  # Antigravity OAuth 凭证获取


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "Catiecli"}


@app.get("/api/public/stats")
async def public_stats():
    """公共统计信息（无需登录）"""
    from sqlalchemy import select, func
    from app.models.user import User, Credential, UsageLog
    from datetime import date
    
    async with async_session() as db:
        user_count = (await db.execute(select(func.count(User.id)))).scalar() or 0
        active_credentials = (await db.execute(
            select(func.count(Credential.id)).where(Credential.is_active == True)
        )).scalar() or 0
        today = date.today()
        today_requests = (await db.execute(
            select(func.count(UsageLog.id)).where(func.date(UsageLog.created_at) == today)
        )).scalar() or 0
        
        # 成功/失败统计
        today_success = (await db.execute(
            select(func.count(UsageLog.id))
            .where(func.date(UsageLog.created_at) == today)
            .where(UsageLog.status_code == 200)
        )).scalar() or 0
        today_failed = today_requests - today_success
        
        return {
            "user_count": user_count,
            "active_credentials": active_credentials,
            "today_requests": today_requests,
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
