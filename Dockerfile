# 第一阶段：构建前端
FROM node:18-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
# 在 Docker 环境中覆盖 outDir 为 dist（因为相对路径 ../backend 在 Docker 中不存在）
RUN npm run build -- --outDir dist

# 第二阶段：构建后端
FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码
COPY backend/ .

# 复制前端构建产物（覆盖 static 目录）
COPY --from=frontend-builder /frontend/dist ./static

# 创建数据目录
RUN mkdir -p /app/data

# 设置 Python 编码为 UTF-8（确保 emoji 等 Unicode 字符正常输出）
ENV PYTHONIOENCODING=utf-8
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# 默认端口（Zeabur 期望 8080）
ENV PORT=8080
EXPOSE 8080

# 启动命令（使用 shell 形式以支持环境变量）
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT
