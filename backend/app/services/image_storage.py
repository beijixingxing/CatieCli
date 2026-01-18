"""
图片本地存储服务
用于保存 Antigravity 生成的图片并返回可访问的 URL
"""

import os
import base64
import uuid
from datetime import datetime
from pathlib import Path


class ImageStorage:
    """本地图片存储服务"""
    
    # 图片存储目录（相对于 app 目录）
    # backend/app/services/image_storage.py -> backend/static/images
    STORAGE_DIR = Path(__file__).parent.parent.parent / "static" / "images"
    
    @classmethod
    def init_storage(cls):
        """初始化存储目录"""
        cls.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        print(f"[ImageStorage] 图片存储目录: {cls.STORAGE_DIR}", flush=True)
    
    @classmethod
    def save_base64_image(cls, base64_data: str, mime_type: str = "image/png") -> str:
        """
        保存 base64 图片到本地并返回相对 URL
        
        Args:
            base64_data: base64 编码的图片数据
            mime_type: 图片 MIME 类型
            
        Returns:
            图片的相对 URL 路径 (如 /images/xxx.png)
        """
        # 确保存储目录存在
        cls.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        
        # 根据 MIME 类型确定扩展名
        ext_map = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/gif": ".gif",
            "image/webp": ".webp",
        }
        ext = ext_map.get(mime_type, ".png")
        
        # 生成唯一文件名
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        filename = f"{timestamp}_{unique_id}{ext}"
        
        # 保存文件
        file_path = cls.STORAGE_DIR / filename
        try:
            image_data = base64.b64decode(base64_data)
            with open(file_path, "wb") as f:
                f.write(image_data)
            print(f"[ImageStorage] ✅ 图片已保存: {filename} ({len(image_data)} bytes)", flush=True)
            
            # 返回相对 URL
            return f"/images/{filename}"
        except Exception as e:
            print(f"[ImageStorage] ❌ 保存图片失败: {e}", flush=True)
            return ""
    
    @classmethod
    def cleanup_old_images(cls, max_age_hours: int = 24):
        """清理过期图片（可选功能）"""
        # TODO: 实现定期清理
        pass


# 初始化存储目录
ImageStorage.init_storage()
