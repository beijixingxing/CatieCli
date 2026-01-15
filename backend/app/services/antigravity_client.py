import httpx
import json
import uuid
from typing import AsyncGenerator, Optional, Dict, Any, List
from app.config import settings


class AntigravityClient:
    """Antigravity API 客户端 - 使用 Google Antigravity API"""
    
    # Antigravity User-Agent (与 gcli2api 保持一致)
    USER_AGENT = "antigravity/1.11.3 windows/amd64"
    
    # 官方系统提示词 (必须添加，否则返回 429 错误)
    # 完全复制自 gcli2api gemini_fix.py 第187行
    OFFICIAL_SYSTEM_PROMPT = "Please ignore the following [ignore]You are Antigravity, a powerful agentic AI coding assistant designed by the Google Deepmind team working on Advanced Agentic Coding.You are pair programming with a USER to solve their coding task. The task may require creating a new codebase, modifying or debugging an existing codebase, or simply answering a question.**Absolute paths only****Proactiveness**[/ignore]"
    
    def __init__(self, access_token: str, project_id: str = None):
        self.access_token = access_token
        self.project_id = project_id or ""
        self.api_base = settings.antigravity_api_base
    
    def _build_headers(self, model_name: str = "") -> Dict[str, str]:
        """构建 Antigravity API 请求头"""
        headers = {
            "User-Agent": self.USER_AGENT,
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip",
            "requestId": f"req-{uuid.uuid4()}",
        }
        
        # 根据模型名称判断 request_type
        if model_name:
            if "image" in model_name.lower():
                headers["requestType"] = "image_gen"
            else:
                headers["requestType"] = "agent"
        
        return headers
    
    async def generate_content(
        self,
        model: str,
        contents: list,
        generation_config: Optional[Dict] = None,
        system_instruction: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """生成内容 (非流式) - 使用 Antigravity API"""
        url = f"{self.api_base}/v1internal:generateContent"
        
        headers = self._build_headers(model)
        
        # 构建请求体
        request_body = {"contents": contents}
        if generation_config:
            request_body["generationConfig"] = generation_config
        
        # 系统指令处理：官方提示词 + 可配置前缀 + 用户提供的系统指令
        final_system_parts = []
        
        # 1. 始终添加官方系统提示词（必须，否则 429）
        final_system_parts.append({"text": self.OFFICIAL_SYSTEM_PROMPT})
        
        # 2. 添加可配置的系统提示词前缀（如果设置了）
        if settings.antigravity_system_prompt:
            final_system_parts.append({"text": settings.antigravity_system_prompt})
        
        # 3. 添加用户提供的系统指令
        if system_instruction:
            if "parts" in system_instruction:
                final_system_parts.extend(system_instruction["parts"])
            elif "text" in system_instruction:
                final_system_parts.append({"text": system_instruction["text"]})
        
        # 设置 systemInstruction
        request_body["systemInstruction"] = {"parts": final_system_parts}
        
        # 添加安全设置 (与 gcli2api 完全一致，使用 BLOCK_NONE，包含10个类别)
        request_body["safetySettings"] = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_IMAGE_HATE", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_IMAGE_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_IMAGE_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_IMAGE_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_JAILBREAK", "threshold": "BLOCK_NONE"},
        ]
        # 对 Claude 模型应用思考块修复 (与 gcli2api 一致)
        if generation_config is None:
            generation_config = {}
        self._apply_claude_thinking_fix(model, contents, generation_config)
        if generation_config:
            request_body["generationConfig"] = generation_config
        
        payload = {
            "model": model,
            "project": self.project_id,
            "request": request_body,
        }
        
        print(f"[AntigravityClient] 请求: model={model}, project={self.project_id}", flush=True)
        print(f"[AntigravityClient] generationConfig: {generation_config}", flush=True)
        
        # 使用更细粒度的超时配置
        timeout = httpx.Timeout(
            connect=30.0,
            read=600.0,
            write=30.0,
            pool=30.0
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            
            print(f"[AntigravityClient] 响应头: {dict(response.headers)}", flush=True)
            
            if response.status_code != 200:
                error_text = response.text
                print(f"[AntigravityClient] ❌ 错误 {response.status_code}: {error_text[:500]}", flush=True)
                raise Exception(f"API Error {response.status_code}: {error_text}")
            result = response.json()
            print(f"[AntigravityClient] ✅ 原始响应: {json.dumps(result, ensure_ascii=False)[:1000]}", flush=True)
            return result
    
    async def generate_content_stream(
        self,
        model: str,
        contents: list,
        generation_config: Optional[Dict] = None,
        system_instruction: Optional[Dict] = None
    ) -> AsyncGenerator[str, None]:
        """生成内容 (流式) - 使用 Antigravity API"""
        url = f"{self.api_base}/v1internal:streamGenerateContent?alt=sse"
        
        headers = self._build_headers(model)
        
        # 构建请求体
        request_body = {"contents": contents}
        if generation_config:
            request_body["generationConfig"] = generation_config
        
        # 系统指令处理：官方提示词 + 可配置前缀 + 用户提供的系统指令
        final_system_parts = []
        
        # 1. 始终添加官方系统提示词（必须，否则 429）
        final_system_parts.append({"text": self.OFFICIAL_SYSTEM_PROMPT})
        
        # 2. 添加可配置的系统提示词前缀（如果设置了）
        if settings.antigravity_system_prompt:
            final_system_parts.append({"text": settings.antigravity_system_prompt})
        
        # 3. 添加用户提供的系统指令
        if system_instruction:
            if "parts" in system_instruction:
                final_system_parts.extend(system_instruction["parts"])
            elif "text" in system_instruction:
                final_system_parts.append({"text": system_instruction["text"]})
        
        # 设置 systemInstruction
        request_body["systemInstruction"] = {"parts": final_system_parts}
        
        # 添加安全设置 (与 gcli2api 完全一致，使用 BLOCK_NONE，包含10个类别)
        request_body["safetySettings"] = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_IMAGE_HATE", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_IMAGE_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_IMAGE_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_IMAGE_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_JAILBREAK", "threshold": "BLOCK_NONE"},
        ]
        
        # 对 Claude 模型应用思考块修复 (与 gcli2api 一致)
        if generation_config is None:
            generation_config = {}
        self._apply_claude_thinking_fix(model, contents, generation_config)
        if generation_config:
            request_body["generationConfig"] = generation_config
        
        payload = {
            "model": model,
            "project": self.project_id,
            "request": request_body,
        }
        
        print(f"[AntigravityClient] 流式请求: model={model}, project={self.project_id}", flush=True)
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST", url, headers=headers, json=payload
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    print(f"[AntigravityClient] ❌ 流式错误 {response.status_code}: {error_text.decode()[:500]}", flush=True)
                    raise Exception(f"API Error {response.status_code}: {error_text.decode()}")
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        yield line[6:]
    
    async def fetch_available_models(self) -> List[Dict[str, Any]]:
        """获取可用模型列表"""
        url = f"{self.api_base}/v1internal:fetchAvailableModels"
        
        headers = self._build_headers()
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, json={})
                
                if response.status_code == 200:
                    data = response.json()
                    print(f"[AntigravityClient] 模型列表响应: {json.dumps(data, ensure_ascii=False)[:500]}", flush=True)
                    
                    models = []
                    if 'models' in data and isinstance(data['models'], dict):
                        for model_id in data['models'].keys():
                            models.append({
                                "id": model_id,
                                "object": "model",
                                "owned_by": "google"
                            })
                    return models
                else:
                    print(f"[AntigravityClient] ❌ 获取模型列表失败 ({response.status_code}): {response.text[:500]}", flush=True)
                    return []
        except Exception as e:
            print(f"[AntigravityClient] ❌ 获取模型列表异常: {e}", flush=True)
            return []
    
    async def fetch_quota_info(self) -> Dict[str, Any]:
        """获取配额信息"""
        url = f"{self.api_base}/v1internal:fetchAvailableModels"
        
        headers = self._build_headers()
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, json={})
                
                if response.status_code == 200:
                    data = response.json()
                    quota_info = {}
                    
                    if 'models' in data and isinstance(data['models'], dict):
                        for model_id, model_data in data['models'].items():
                            if isinstance(model_data, dict) and 'quotaInfo' in model_data:
                                quota = model_data['quotaInfo']
                                remaining = quota.get('remainingFraction', 0)
                                reset_time = quota.get('resetTime', '')
                                
                                quota_info[model_id] = {
                                    "remaining": remaining,
                                    "resetTime": reset_time
                                }
                    
                    return {"success": True, "models": quota_info}
                else:
                    return {"success": False, "error": f"API返回错误: {response.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def is_fake_streaming(self, model: str) -> bool:
        """Antigravity 不支持假流式，总是返回 False"""
        return False
    
    async def chat_completions(
        self,
        model: str,
        messages: list,
        **kwargs
    ) -> Dict[str, Any]:
        """OpenAI兼容的chat completions (非流式)"""
        contents, system_instruction = self._convert_messages_to_contents(messages)
        generation_config = self._build_generation_config(model, kwargs)
        gemini_model = self._map_model_name(model)
        
        print(f"[AntigravityClient] 模型名映射: {model} -> {gemini_model}", flush=True)
        
        result = await self.generate_content(gemini_model, contents, generation_config, system_instruction)
        return self._convert_to_openai_response(result, model)
    
    async def chat_completions_stream(
        self,
        model: str,
        messages: list,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """OpenAI兼容的chat completions (流式)"""
        contents, system_instruction = self._convert_messages_to_contents(messages)
        generation_config = self._build_generation_config(model, kwargs)
        gemini_model = self._map_model_name(model)
        
        async for chunk in self.generate_content_stream(gemini_model, contents, generation_config, system_instruction):
            yield self._convert_to_openai_stream(chunk, model)
    
    async def chat_completions_fake_stream(
        self,
        model: str,
        messages: list,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """假流式: 先发心跳，拿到完整响应后一次性输出"""
        import asyncio
        
        contents, system_instruction = self._convert_messages_to_contents(messages)
        generation_config = self._build_generation_config(model, kwargs)
        gemini_model = self._map_model_name(model)
        
        # 发送初始 chunk（空内容，保持连接）
        initial_chunk = {
            "id": "chatcmpl-antigravity",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": model,
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]
        }
        yield f"data: {json.dumps(initial_chunk)}\n\n"
        
        # 创建请求任务
        request_task = asyncio.create_task(
            self.generate_content(gemini_model, contents, generation_config, system_instruction)
        )
        
        # 每2秒发送心跳，直到请求完成
        heartbeat_chunk = {
            "id": "chatcmpl-antigravity",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": None}]
        }
        
        while not request_task.done():
            await asyncio.sleep(2)
            if not request_task.done():
                yield f"data: {json.dumps(heartbeat_chunk)}\n\n"
        
        # 获取完整响应
        try:
            result = await request_task
            content = ""
            
            # API 返回格式是 {"response": {"candidates": ...}}
            response_data = result.get("response", result)
            
            if "candidates" in response_data and response_data["candidates"]:
                candidate = response_data["candidates"][0]
                if "content" in candidate and "parts" in candidate["content"]:
                    for part in candidate["content"]["parts"]:
                        if "text" in part and not part.get("thought", False):
                            content += part.get("text", "")
            
            # 输出完整内容
            if content:
                content_chunk = {
                    "id": "chatcmpl-antigravity",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": model,
                    "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]
                }
                yield f"data: {json.dumps(content_chunk)}\n\n"
            
            # 发送结束标记
            done_chunk = {
                "id": "chatcmpl-antigravity",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
            }
            yield f"data: {json.dumps(done_chunk)}\n\n"
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            error_chunk = {
                "id": "chatcmpl-antigravity",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": model,
                "choices": [{"index": 0, "delta": {"content": f"\n\n[Error: {str(e)}]"}, "finish_reason": "stop"}]
            }
            yield f"data: {json.dumps(error_chunk)}\n\n"
            yield "data: [DONE]\n\n"
    
    def _build_generation_config(self, model: str, kwargs: dict) -> dict:
        """构建生成配置 (与 gcli2api gemini_fix.py 保持一致)"""
        generation_config = {}
        
        # 基础配置
        if "temperature" in kwargs:
            generation_config["temperature"] = kwargs["temperature"]
        if "top_p" in kwargs:
            generation_config["topP"] = kwargs["top_p"]
        
        # 强制设置 maxOutputTokens = 64000 (与 gcli2api 一致)
        generation_config["maxOutputTokens"] = 64000
        
        # 强制设置 topK = 64 (与 gcli2api 一致)
        generation_config["topK"] = 64
        
        # 为 thinking 模型添加 thinkingConfig (与 gcli2api gemini_fix.py 第206-215行一致)
        if self._is_thinking_model(model):
            generation_config["thinkingConfig"] = {
                "thinkingBudget": 1024,
                "includeThoughts": True
            }
            print(f"[AntigravityClient] 已添加 thinkingConfig: thinkingBudget=1024", flush=True)
        
        return generation_config
    
    def _is_thinking_model(self, model: str) -> bool:
        """检查是否为思考模型 (与 gcli2api gemini_fix.py 第111-113行一致)"""
        return "think" in model.lower() or "pro" in model.lower() or "claude" in model.lower()
    
    def _apply_claude_thinking_fix(self, model: str, contents: list, generation_config: dict) -> None:
        """
        对 Claude 模型应用思考块修复 (与 gcli2api gemini_fix.py 第217-254行一致)
        
        当存在历史对话时，在最后一个 model 消息开头插入带有
        thoughtSignature: skip_thought_signature_validator 的思考块
        """
        if "claude" not in model.lower():
            return
        
        # 检测是否有工具调用（MCP场景）
        has_tool_calls = any(
            isinstance(content, dict) and 
            any(
                isinstance(part, dict) and ("functionCall" in part or "function_call" in part)
                for part in content.get("parts", [])
            )
            for content in contents
        )
        
        if has_tool_calls:
            # MCP 场景：检测到工具调用，移除 thinkingConfig
            print(f"[AntigravityClient] 检测到工具调用（MCP场景），移除 thinkingConfig", flush=True)
            generation_config.pop("thinkingConfig", None)
        else:
            # 非 MCP 场景：在最后一个 model 消息开头插入思考块
            for i in range(len(contents) - 1, -1, -1):
                content = contents[i]
                if isinstance(content, dict) and content.get("role") == "model":
                    parts = content.get("parts", [])
                    # 使用官方跳过验证的虚拟签名
                    thinking_part = {
                        "text": "...",
                        "thoughtSignature": "skip_thought_signature_validator"
                    }
                    # 如果第一个 part 不是 thinking，则插入
                    if not parts or not (isinstance(parts[0], dict) and ("thought" in parts[0] or "thoughtSignature" in parts[0])):
                        content["parts"] = [thinking_part] + parts
                        print(f"[AntigravityClient] 已在最后一个 assistant 消息开头插入思考块（含跳过验证签名）", flush=True)
                    break
    
    def _convert_messages_to_contents(self, messages: list) -> tuple:
        """将OpenAI消息格式转换为Gemini contents格式"""
        contents = []
        system_instructions = []
        
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "system":
                if isinstance(content, str):
                    system_instructions.append(content)
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            system_instructions.append(item.get("text", ""))
                        elif isinstance(item, str):
                            system_instructions.append(item)
                continue
            
            gemini_role = "user" if role == "user" else "model"
            
            # 处理多模态内容
            parts = []
            if isinstance(content, str):
                parts.append({"text": content})
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            parts.append({"text": item.get("text", "")})
                        elif item.get("type") == "image_url":
                            image_url = item.get("image_url", {})
                            url = image_url.get("url", "") if isinstance(image_url, dict) else image_url
                            if url.startswith("data:"):
                                try:
                                    header, base64_data = url.split(",", 1)
                                    mime_type = header.split(":")[1].split(";")[0]
                                    parts.append({
                                        "inlineData": {
                                            "mimeType": mime_type,
                                            "data": base64_data
                                        }
                                    })
                                except Exception as e:
                                    print(f"[AntigravityClient] ⚠️ 解析图片数据失败: {e}", flush=True)
                            else:
                                parts.append({
                                    "fileData": {
                                        "mimeType": "image/jpeg",
                                        "fileUri": url
                                    }
                                })
                        elif "text" in item and "type" not in item:
                            parts.append({"text": item["text"]})
                        elif "inlineData" in item:
                            parts.append({"inlineData": item["inlineData"]})
                        elif "fileData" in item:
                            parts.append({"fileData": item["fileData"]})
                    elif isinstance(item, str):
                        parts.append({"text": item})
            
            if not parts:
                parts.append({"text": ""})
            
            contents.append({
                "role": gemini_role,
                "parts": parts
            })
        
        # 构建 systemInstruction
        system_instruction = None
        if system_instructions:
            combined = "\n\n".join(system_instructions)
            system_instruction = {"parts": [{"text": combined}]}
        
        if not contents:
            contents.append({"role": "user", "parts": [{"text": "请根据系统指令回答。"}]})
        
        return contents, system_instruction
    
    def _map_model_name(self, model: str) -> str:
        """映射模型名称 - 移除自定义前缀并处理特殊模型 (与 gcli2api gemini_fix.py 第259-274行一致)"""
        original_model = model
        
        # 移除 agy- 前缀 (CatieCli 自定义)
        if model.startswith("agy-"):
            model = model[4:]
        # 移除 gcli- 前缀 (如果有)
        if model.startswith("gcli-"):
            model = model[5:]
        # 移除 假流式/ 和 流式抗截断/ 前缀
        for prefix in ["假流式/", "流式抗截断/"]:
            if model.startswith(prefix):
                model = model[len(prefix):]
        
        # 移除 -thinking 后缀 (如果有)
        model = model.replace("-thinking", "")
        
        # Claude 模型关键词映射 (与 gcli2api gemini_fix.py 第259-274行完全一致)
        model_lower = model.lower()
        if "opus" in model_lower:
            model = "claude-opus-4-5-thinking"
        elif "sonnet" in model_lower:
            model = "claude-sonnet-4-5-thinking"
        elif "haiku" in model_lower:
            model = "gemini-2.5-flash"  # gcli2api 将 haiku 映射到 flash
        elif "claude" in model_lower:
            # Claude 模型兜底：如果包含 claude 但不是 opus/sonnet/haiku
            model = "claude-sonnet-4-5-thinking"
        
        if original_model != model:
            print(f"[AntigravityClient] 模型映射: {original_model} -> {model}", flush=True)
        
        return model
    
    def _convert_to_openai_response(self, gemini_response: dict, model: str) -> dict:
        """将Gemini响应转换为OpenAI格式"""
        content = ""
        reasoning_content = ""
        
        response_data = gemini_response.get("response", gemini_response)
        
        if "candidates" in response_data and response_data["candidates"]:
            candidate = response_data["candidates"][0]
            if "content" in candidate and "parts" in candidate["content"]:
                for part in candidate["content"]["parts"]:
                    text = part.get("text", "")
                    if part.get("thought", False):
                        reasoning_content += text
                    else:
                        content += text
        
        message = {
            "role": "assistant",
            "content": content
        }
        if reasoning_content:
            message["reasoning_content"] = reasoning_content
        
        return {
            "id": "chatcmpl-antigravity",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [{
                "index": 0,
                "message": message,
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }
        }
    
    def _convert_to_openai_stream(self, chunk_data: str, model: str) -> str:
        """将Gemini流式响应转换为OpenAI SSE格式"""
        try:
            data = json.loads(chunk_data)
            content = ""
            reasoning_content = ""
            
            response_data = data.get("response", data)
            
            if "candidates" in response_data and response_data["candidates"]:
                candidate = response_data["candidates"][0]
                if "content" in candidate and "parts" in candidate["content"]:
                    for part in candidate["content"]["parts"]:
                        text = part.get("text", "")
                        if part.get("thought", False):
                            reasoning_content += text
                        else:
                            content += text
            
            delta = {}
            if content:
                delta["content"] = content
            if reasoning_content:
                delta["reasoning_content"] = reasoning_content
            
            if not delta:
                return ""
            
            openai_chunk = {
                "id": "chatcmpl-antigravity",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": delta,
                    "finish_reason": None
                }]
            }
            return f"data: {json.dumps(openai_chunk)}\n\n"
        except:
            return ""