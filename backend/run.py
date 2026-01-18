import uvicorn
import os
from app.config import settings

if __name__ == "__main__":
    # Zeabur/生产环境使用 PORT 环境变量（Zeabur 默认设为 8080）
    # 开发环境使用 settings.port（默认 5001）
    port = int(os.environ.get("PORT", settings.port))
    
    # 生产环境检测：有 PORT 环境变量时禁用 reload
    is_production = "PORT" in os.environ
    
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=port,
        reload=not is_production  # 仅开发环境启用热重载
    )
