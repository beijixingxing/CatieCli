from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Float
from sqlalchemy.orm import relationship
from datetime import datetime
import secrets
from app.database import Base


class User(Base):
    """用户表"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    discord_id = Column(String(50), unique=True, index=True, nullable=True)  # Discord 用户 ID
    discord_name = Column(String(100), nullable=True)  # Discord 用户名
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    daily_quota = Column(Integer, default=100)  # 基础每日配额（管理员设置）
    bonus_quota = Column(Integer, default=0)  # 凭证奖励配额（自动计算，凭证失效时扣除）
    # 按模型分类的配额（0=使用系统默认，-1=无限制）
    quota_flash = Column(Integer, default=0)   # Flash模型配额
    quota_25pro = Column(Integer, default=0)   # 2.5 Pro模型配额
    quota_30pro = Column(Integer, default=0)   # 3.0模型配额
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 关系
    api_keys = relationship("APIKey", back_populates="user", cascade="all, delete-orphan")
    usage_logs = relationship("UsageLog", back_populates="user", cascade="all, delete-orphan")
    credentials = relationship("Credential", back_populates="owner")


class APIKey(Base):
    """用户API密钥表"""
    __tablename__ = "api_keys"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    key = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(100), default="default")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    
    # 关系
    user = relationship("User", back_populates="api_keys")
    
    @staticmethod
    def generate_key():
        """生成API密钥: cat-xxxxxxxx"""
        return f"cat-{secrets.token_hex(24)}"


class UsageLog(Base):
    """使用记录表"""
    __tablename__ = "usage_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=True)
    credential_id = Column(Integer, ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True)  # 使用的凭证
    model = Column(String(100), nullable=True)
    endpoint = Column(String(200), nullable=True)
    tokens_input = Column(Integer, default=0)
    tokens_output = Column(Integer, default=0)
    status_code = Column(Integer, nullable=True)
    latency_ms = Column(Float, nullable=True)
    cd_seconds = Column(Integer, nullable=True)  # 429 时设置的 CD 秒数
    created_at = Column(DateTime, default=datetime.utcnow)
    # 详细报错信息
    error_message = Column(Text, nullable=True)  # 错误信息
    request_body = Column(Text, nullable=True)   # 请求内容（截断保存）
    client_ip = Column(String(50), nullable=True)  # 客户端 IP
    user_agent = Column(String(500), nullable=True)  # User Agent
    # 错误分类字段（新增）
    error_type = Column(String(50), nullable=True, index=True)  # 错误类型：AUTH_ERROR, RATE_LIMIT, QUOTA_EXHAUSTED 等
    error_code = Column(String(100), nullable=True)  # 错误码：PERMISSION_DENIED, RESOURCE_EXHAUSTED 等
    credential_email = Column(String(100), nullable=True)  # 使用的凭证邮箱（方便排查）
    retry_count = Column(Integer, default=0)  # 重试次数：0表示首次成功，>0表示经过重试
    
    # 关系
    user = relationship("User", back_populates="usage_logs")
    credential = relationship("Credential")


class Credential(Base):
    """Gemini凭证池
    
    凭证类型 (api_type):
    - geminicli: GeminiCLI 凭证，使用 GeminiCLI User-Agent
    - antigravity: Antigravity 凭证，使用 Antigravity User-Agent
    
    注意：GeminiCLI 和 Antigravity 是完全独立的凭证体系，不能混用！
    同一个 Google 账号需要分别认证才能获得两种凭证。
    """
    __tablename__ = "credentials"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # 所属用户
    name = Column(String(100), nullable=False)
    api_key = Column(Text, nullable=False)  # Gemini API Key 或 OAuth access_token
    refresh_token = Column(Text, nullable=True)  # OAuth refresh_token
    client_id = Column(Text, nullable=True)  # OAuth client_id（加密存储）
    client_secret = Column(Text, nullable=True)  # OAuth client_secret（加密存储）
    project_id = Column(String(200), nullable=True)  # Project ID（两种类型都需要）
    # 凭证类型：geminicli 或 antigravity（独立的凭证体系）
    api_type = Column(String(20), default="geminicli", index=True)  # geminicli 或 antigravity
    credential_type = Column(String(20), default="api_key")  # api_key 或 oauth
    model_tier = Column(String(10), default="2.5")  # 模型等级: "3" 或 "2.5"
    account_type = Column(String(20), default="free")  # 账号类型: "pro" 或 "free"
    email = Column(String(100), nullable=True)  # OAuth 关联的邮箱
    is_public = Column(Boolean, default=False)  # 是否捐赠到公共池
    is_active = Column(Boolean, default=True)
    total_requests = Column(Integer, default=0)
    failed_requests = Column(Integer, default=0)
    last_used_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # CD 机制：按模型组记录最后使用时间（适用于两种凭证类型）
    last_used_flash = Column(DateTime, nullable=True)  # Flash 模型组 CD
    last_used_pro = Column(DateTime, nullable=True)    # Pro 模型组 CD
    last_used_30 = Column(DateTime, nullable=True)     # 3.0 模型组 CD
    # 模型级 CD 机制（JSON 格式 {"model_name": "timestamp"}）
    model_cooldowns = Column(Text, nullable=True)
    
    # 关系
    owner = relationship("User", back_populates="credentials")


class SystemConfig(Base):
    """系统配置表（持久化存储）"""
    __tablename__ = "system_config"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, index=True, nullable=False)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ErrorMessageConfig(Base):
    """自定义错误消息配置
    
    用于配置返回给客户端的友好错误消息。
    可以按错误类型或关键词匹配，关键词匹配优先级更高。
    
    全局开关通过 SystemConfig 中的 'custom_error_messages_enabled' 配置项控制。
    """
    __tablename__ = "error_message_configs"
    
    id = Column(Integer, primary_key=True, index=True)
    # 匹配条件
    error_type = Column(String(50), nullable=True, index=True)  # 错误类型：NETWORK_ERROR, RATE_LIMIT 等
    keyword = Column(String(200), nullable=True)                # 可选：匹配原始错误文本中的关键词
    # 自定义消息
    custom_message = Column(Text, nullable=False)               # 返回给客户端的自定义消息
    # 状态与优先级
    is_active = Column(Boolean, default=True)
    priority = Column(Integer, default=0)                       # 优先级（数值越大越优先）
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

