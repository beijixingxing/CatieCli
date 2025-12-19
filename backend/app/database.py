from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool, QueuePool
from app.config import settings
import os

# 判断数据库类型
is_sqlite = settings.database_url.startswith("sqlite")
is_postgres = "postgresql" in settings.database_url or "postgres" in settings.database_url

# SQLite 需要创建数据目录
if is_sqlite:
    os.makedirs("data", exist_ok=True)

# 根据数据库类型配置引擎
if is_sqlite:
    # SQLite 配置
    engine = create_async_engine(
        settings.database_url, 
        echo=False,
        connect_args={
            "timeout": 60,
            "check_same_thread": False
        },
        poolclass=NullPool,
    )
else:
    # PostgreSQL 配置
    engine = create_async_engine(
        settings.database_url, 
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

async def get_db():
    async with async_session() as session:
        yield session

async def init_db():
    async with engine.begin() as conn:
        # SQLite 特有优化
        if is_sqlite:
            from sqlalchemy import text
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA synchronous=NORMAL"))
            await conn.execute(text("PRAGMA busy_timeout=60000"))
        
        await conn.run_sync(Base.metadata.create_all)
        
        # 数据库迁移：添加新列（如果不存在）
        from sqlalchemy import text
        
        if is_sqlite:
            # SQLite 迁移
            migrations = [
                "ALTER TABLE usage_logs ADD COLUMN credential_id INTEGER REFERENCES credentials(id)",
                "ALTER TABLE users ADD COLUMN bonus_quota INTEGER DEFAULT 0",
                "ALTER TABLE credentials ADD COLUMN client_id TEXT",
                "ALTER TABLE credentials ADD COLUMN client_secret TEXT",
                "ALTER TABLE users ADD COLUMN quota_flash INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN quota_25pro INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN quota_30pro INTEGER DEFAULT 0",
                "ALTER TABLE credentials ADD COLUMN account_type VARCHAR(20) DEFAULT 'free'",
                "ALTER TABLE credentials ADD COLUMN last_used_flash DATETIME",
                "ALTER TABLE credentials ADD COLUMN last_used_pro DATETIME",
                "ALTER TABLE credentials ADD COLUMN last_used_30 DATETIME",
            ]
        else:
            # PostgreSQL 迁移（使用 IF NOT EXISTS 语法）
            migrations = [
                "ALTER TABLE usage_logs ADD COLUMN IF NOT EXISTS credential_id INTEGER REFERENCES credentials(id)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS bonus_quota INTEGER DEFAULT 0",
                "ALTER TABLE credentials ADD COLUMN IF NOT EXISTS client_id TEXT",
                "ALTER TABLE credentials ADD COLUMN IF NOT EXISTS client_secret TEXT",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_flash INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_25pro INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_30pro INTEGER DEFAULT 0",
                "ALTER TABLE credentials ADD COLUMN IF NOT EXISTS account_type VARCHAR(20) DEFAULT 'free'",
                "ALTER TABLE credentials ADD COLUMN IF NOT EXISTS last_used_flash TIMESTAMP",
                "ALTER TABLE credentials ADD COLUMN IF NOT EXISTS last_used_pro TIMESTAMP",
                "ALTER TABLE credentials ADD COLUMN IF NOT EXISTS last_used_30 TIMESTAMP",
            ]
        
        for sql in migrations:
            try:
                await conn.execute(text(sql))
                print(f"[DB Migration] ✅ {sql[:50]}...")
            except Exception as e:
                if "duplicate column" not in str(e).lower() and "already exists" not in str(e).lower():
                    pass  # 列已存在，忽略
