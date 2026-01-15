# CatieCli Antigravity 功能开发日志

> 分支: `feature/demokt`
> 最后更新: 2026-01-15

## 📋 项目概述

本分支基于 CatieCli 原版项目，添加了对 Google Antigravity API 的反向代理支持。Antigravity 是 Google 提供的另一种 Gemini API 访问方式，与原有的 GeminiCLI 方式相互独立。

---

## ✅ 已完成的改动

### 1. 后端配置 (`backend/app/config.py`)
- [x] 新增 `ANTIGRAVITY_ENABLED` 配置项（是否启用 Antigravity 功能）
- [x] 新增 `ANTIGRAVITY_API_BASE` 配置项（默认: `https://daily-cloudcode-pa.sandbox.googleapis.com`）

### 2. 数据库模型 (`backend/app/models/user.py`)
- [x] `Credential` 模型新增 `api_type` 字段，用于区分凭证类型：
  - `geminicli`: 传统 GeminiCLI 凭证
  - `antigravity`: Antigravity 凭证

### 3. 凭证池服务 (`backend/app/services/credential_pool.py`)
- [x] 所有方法增加 `mode` 参数支持
- [x] `get_random_credential()` 支持按 mode 获取凭证
- [x] `get_access_token()` 优化 token 刷新逻辑
- [x] 新增 `_is_token_expired()` 方法，提前 5 分钟检查过期
- [x] 新增 `ANTIGRAVITY_USER_AGENT` 常量
- [x] 新增 `fetch_project_id()` 函数，支持 Antigravity 方式获取 project_id

### 4. Antigravity 客户端 (`backend/app/services/antigravity_client.py`) [新文件]
- [x] 实现 `AntigravityClient` 类
- [x] 支持 `generate_content()` 非流式调用
- [x] 支持 `generate_content_stream()` 流式调用
- [x] 支持 `fetch_available_models()` 获取可用模型列表
- [x] 支持 `fetch_quota_info()` 获取配额信息
- [x] 支持 OpenAI 格式转换 (`chat_completions`, `chat_completions_stream`)
- [x] 支持假流式模式 (`chat_completions_fake_stream`)

### 5. Antigravity 代理路由 (`backend/app/routers/antigravity_proxy.py`) [新文件]
- [x] `POST /agy/v1/chat/completions` - OpenAI 兼容的聊天补全接口
- [x] 支持流式和非流式响应
- [x] 自动轮换凭证

### 6. Antigravity 凭证管理路由 (`backend/app/routers/antigravity_manage.py`) [新文件]
- [x] `POST /api/antigravity/credentials/upload` - 批量上传凭证
- [x] `GET /api/antigravity/credentials` - 获取用户凭证列表
- [x] `PATCH /api/antigravity/credentials/{id}` - 更新凭证状态
- [x] `DELETE /api/antigravity/credentials/{id}` - 删除凭证
- [x] `POST /api/antigravity/credentials/{id}/verify` - 验证凭证有效性
- [x] `POST /api/antigravity/credentials/{id}/refresh-project-id` - 刷新 Project ID
- [x] `GET /api/antigravity/credentials/{id}/quota` - 获取凭证额度信息
- [x] `GET /api/antigravity/credentials/{id}/export` - 导出凭证
- [x] `GET /api/antigravity/stats` - 获取统计信息
- [x] 管理员批量操作接口

### 7. Antigravity OAuth 路由 (`backend/app/routers/antigravity_oauth.py`) [新文件]
- [x] `GET /api/antigravity/oauth/auth-url` - 获取 OAuth 认证链接
- [x] `POST /api/antigravity/oauth/complete` - 完成 OAuth 认证
- [x] 使用 Antigravity 专用的 User-Agent 和 API 端点

### 8. 主应用入口 (`backend/app/main.py`)
- [x] 注册 Antigravity 代理路由 (`antigravity_proxy.router`)
- [x] 注册 Antigravity 管理路由 (`antigravity_manage.router`)
- [x] 注册 Antigravity OAuth 路由 (`antigravity_oauth.router`)

### 9. 前端 - 路由配置 (`frontend/src/App.jsx`)
- [x] 新增 `/antigravity-credentials` 路由
- [x] 新增 `/antigravity-oauth` 路由

### 10. 前端 - Antigravity 凭证管理页面 (`frontend/src/pages/AntigravityCredentials.jsx`) [新文件]
- [x] 凭证统计卡片（总凭证、活跃、公开、我的活跃）
- [x] 凭证上传功能（支持 JSON/ZIP）
- [x] 凭证列表展示
- [x] 凭证操作按钮：
  - 禁用/启用
  - 检测有效性
  - 刷新 Project ID
  - **额度查询** (代码已添加，第489-501行)
  - 导出
  - 设为公开/取消公开
  - 删除
- [x] 检测结果弹窗
- [x] 额度查询弹窗（带进度条显示）

### 11. 前端 - Antigravity OAuth 页面 (`frontend/src/pages/AntigravityOAuth.jsx`) [新文件]
- [x] 获取 OAuth 认证链接
- [x] 完成认证流程
- [x] 凭证保存功能

### 12. 前端 - Dashboard 页面 (`frontend/src/pages/Dashboard.jsx`)
- [x] 添加 Antigravity 凭证管理入口

### 13. 前端 - 设置页面 (`frontend/src/pages/Settings.jsx`)
- [x] 添加 Antigravity 功能开关

---

## 🚧 当前工作进度

| 功能 | 后端 | 前端 | 测试 |
|------|------|------|------|
| 凭证上传 | ✅ | ✅ | ⚠️ 待测试 |
| 凭证管理 | ✅ | ✅ | ⚠️ 待测试 |
| 凭证检测 | ✅ | ✅ | ⚠️ 待测试 |
| Project ID 刷新 | ✅ | ✅ | ⚠️ 待测试 |
| 额度查询 | ✅ | ✅ | ⚠️ 待测试 |
| OAuth 获取凭证 | ✅ | ✅ | ⚠️ 待测试 |
| API 代理 | ✅ | N/A | ⚠️ 待测试 |
| Docker 构建 | ✅ | ❌ 需手动构建 | ❌ |

---

## 🐛 已知 Bug 和问题

### 1. [严重] 前端额度按钮不显示
**问题描述**: 
- 代码中已添加额度按钮（`AntigravityCredentials.jsx` 第489-501行）
- 但实际运行的 Docker 容器中没有显示该按钮

**原因分析**:
- CatieCli 项目的前端是独立的 React/Vite 项目
- Docker 只构建了后端，前端资源（`backend/static/`）需要单独构建
- 当前容器使用的是旧版前端资源

**解决方案**:
```bash
# 1. 进入前端目录
cd CatieCli/frontend

# 2. 安装依赖（如果没有）
npm install

# 3. 构建前端
npm run build

# 4. 复制构建产物到后端静态目录
cp -r dist/* ../backend/static/

# 5. 重新构建 Docker
cd .. && docker compose build && docker compose up -d
```

### 2. [中等] Token 刷新可能失败
**问题描述**: 
- 刷新凭证时可能提示"无法获取 access token"

**已实施的缓解措施**:
- 添加了 `_is_token_expired()` 方法，提前 5 分钟判断过期
- 刷新失败时会尝试使用现有的 access_token

**待改进**:
- 需要进一步调试实际的刷新失败场景

### 3. [低] docker-compose.yml 版本警告
**问题描述**:
```
level=warning msg="the attribute `version` is obsolete"
```

**解决方案**: 删除 `docker-compose.yml` 中的 `version: '3.8'` 行（该属性已弃用）

---

## 📁 新增/修改的文件列表

### 新增文件
| 文件路径 | 说明 |
|----------|------|
| `backend/app/services/antigravity_client.py` | Antigravity API 客户端 |
| `backend/app/routers/antigravity_proxy.py` | Antigravity 代理路由 |
| `backend/app/routers/antigravity_manage.py` | Antigravity 凭证管理路由 |
| `backend/app/routers/antigravity_oauth.py` | Antigravity OAuth 路由 |
| `frontend/src/pages/AntigravityCredentials.jsx` | Antigravity 凭证管理页面 |
| `frontend/src/pages/AntigravityOAuth.jsx` | Antigravity OAuth 页面 |

### 修改文件
| 文件路径 | 修改内容 |
|----------|----------|
| `backend/app/config.py` | 新增 Antigravity 配置项 |
| `backend/app/models/user.py` | Credential 模型新增 api_type 字段 |
| `backend/app/services/credential_pool.py` | 支持 mode 参数，优化 token 刷新 |
| `backend/app/main.py` | 注册新路由 |
| `backend/app/routers/auth.py` | 小调整 |
| `backend/app/routers/manage.py` | 小调整 |
| `backend/app/routers/proxy.py` | 小调整 |
| `frontend/src/App.jsx` | 新增路由配置 |
| `frontend/src/pages/Dashboard.jsx` | 新增 Antigravity 入口 |
| `frontend/src/pages/Settings.jsx` | 新增 Antigravity 开关 |

---

## 📝 TODO

- [ ] 手动构建前端并更新静态资源
- [ ] 测试所有 Antigravity 功能
- [ ] 修复前端额度按钮不显示问题
- [ ] 测试 Token 刷新逻辑
- [ ] 完善错误处理
- [ ] 添加更多日志输出
- [ ] 考虑将前端构建集成到 Docker

---

## 🔗 参考项目

- [gcli2api](https://github.com/su-kaka/gcli2api) - Antigravity API 实现参考