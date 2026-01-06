from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool, QueuePool
from app.config import settings
import os
import logging

logger = logging.getLogger(__name__)

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
        max_overflow=10,
        pool_pre_ping=True,
    )

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

async def get_db():
    async with async_session() as session:
        yield session

async def init_db(skip_migration_check: bool = False):
    # 自动迁移检测：如果配置了 PostgreSQL 且存在 SQLite 数据库文件，自动迁移
    if is_postgres and not skip_migration_check:
        sqlite_db_path = "./data/gemini_proxy.db"
        backup_path = f"{sqlite_db_path}.bak"

        # 快速检查：只有同时满足以下条件才尝试迁移
        # 1. SQLite 文件存在
        # 2. 备份文件不存在（说明未迁移过）
        if os.path.exists(sqlite_db_path) and not os.path.exists(backup_path):
            logger.info("检测到 SQLite 数据库文件，准备自动迁移到 PostgreSQL...")
            try:
                from app.migrate_to_postgres import auto_migrate_if_needed
                # 传入主应用的 engine，复用连接池
                migrated = await auto_migrate_if_needed(sqlite_db_path, engine)
                if migrated:
                    logger.info("数据迁移完成，继续启动服务...")
                else:
                    logger.info("无需迁移或迁移已完成")
            except Exception as e:
                logger.error(f"自动迁移失败: {e}")
                logger.error("请检查配置或手动迁移数据")
                raise

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
                "ALTER TABLE usage_logs ADD COLUMN cd_seconds INTEGER",
                "ALTER TABLE usage_logs ADD COLUMN error_message TEXT",
                "ALTER TABLE usage_logs ADD COLUMN request_body TEXT",
                "ALTER TABLE usage_logs ADD COLUMN client_ip VARCHAR(50)",
                "ALTER TABLE usage_logs ADD COLUMN user_agent VARCHAR(500)",
                # 错误分类字段（新增）
                "ALTER TABLE usage_logs ADD COLUMN error_type VARCHAR(50)",
                "ALTER TABLE usage_logs ADD COLUMN error_code VARCHAR(100)",
                "ALTER TABLE usage_logs ADD COLUMN credential_email VARCHAR(100)",
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
                "ALTER TABLE usage_logs ADD COLUMN IF NOT EXISTS cd_seconds INTEGER",
                "ALTER TABLE usage_logs ADD COLUMN IF NOT EXISTS error_message TEXT",
                "ALTER TABLE usage_logs ADD COLUMN IF NOT EXISTS request_body TEXT",
                "ALTER TABLE usage_logs ADD COLUMN IF NOT EXISTS client_ip VARCHAR(50)",
                "ALTER TABLE usage_logs ADD COLUMN IF NOT EXISTS user_agent VARCHAR(500)",
                # 错误分类字段（新增）
                "ALTER TABLE usage_logs ADD COLUMN IF NOT EXISTS error_type VARCHAR(50)",
                "ALTER TABLE usage_logs ADD COLUMN IF NOT EXISTS error_code VARCHAR(100)",
                "ALTER TABLE usage_logs ADD COLUMN IF NOT EXISTS credential_email VARCHAR(100)",
            ]
        
        for sql in migrations:
            try:
                await conn.execute(text(sql))
                print(f"[DB Migration] ✅ {sql[:50]}...")
            except Exception as e:
                if "duplicate column" not in str(e).lower() and "already exists" not in str(e).lower():
                    pass  # 列已存在，忽略
        
        # 创建索引优化查询性能
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_usage_logs_created_at ON usage_logs(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_usage_logs_user_id ON usage_logs(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_usage_logs_status_code ON usage_logs(status_code)",
            "CREATE INDEX IF NOT EXISTS idx_usage_logs_user_created ON usage_logs(user_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_credentials_is_active ON credentials(is_active)",
            "CREATE INDEX IF NOT EXISTS idx_credentials_is_public ON credentials(is_public)",
            "CREATE INDEX IF NOT EXISTS idx_credentials_user_id ON credentials(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id)",
            # 错误分类索引（新增）
            "CREATE INDEX IF NOT EXISTS idx_usage_logs_error_type ON usage_logs(error_type)",
            "CREATE INDEX IF NOT EXISTS idx_usage_logs_date_error ON usage_logs(created_at, error_type)",
        ]
        
        for sql in indexes:
            try:
                await conn.execute(text(sql))
                print(f"[DB Index] ✅ {sql[30:70]}...")
            except Exception as e:
                pass  # 索引已存在，忽略
