"""
OpenAI to Gemini 格式转换器 - 从 gcli2api 完整复制
"""
import json
from typing import Any, Dict, List


async def merge_system_messages(openai_request: Dict[str, Any]) -> Dict[str, Any]:
    """
    合并连续的 system 消息为 systemInstruction
    """
    messages = openai_request.get("messages", [])
    if not messages:
        return openai_request
    
    system_parts = []
    other_messages = []
    
    for msg in messages:
        if msg.get("role") == "system":
            content = msg.get("content", "")
            if isinstance(content, str):
                system_parts.append({"text": content})
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        system_parts.append({"text": item.get("text", "")})
                    elif isinstance(item, str):
                        system_parts.append({"text": item})
        else:
            other_messages.append(msg)
    
    result = dict(openai_request)
    result["messages"] = other_messages
    
    if system_parts:
        result["systemInstruction"] = {"parts": system_parts}
    
    return result


async def convert_openai_to_gemini_request(openai_request: Dict[str, Any]) -> Dict[str, Any]:
    """
    将 OpenAI 格式请求体转换为 Gemini 格式请求体
    从 gcli2api 完整复制
    """
    # 处理连续的system消息
    openai_request = await merge_system_messages(openai_request)

    contents = []

    # 提取消息列表
    messages = openai_request.get("messages", [])

    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")

        # system 消息已由 merge_system_messages 处理
        if role == "system":
            continue

        # 处理 tool 消息
        if role == "tool":
            tool_call_id = message.get("tool_call_id", "")
            func_name = message.get("name", "unknown_function")
            
            try:
                response_data = json.loads(content) if isinstance(content, str) else content
            except (json.JSONDecodeError, TypeError):
                response_data = {"result": str(content)}
            
            if not isinstance(response_data, dict):
                response_data = {"result": response_data}
            
            contents.append({
                "role": "user",
                "parts": [{
                    "functionResponse": {
                        "id": tool_call_id,
                        "name": func_name,
                        "response": response_data
                    }
                }]
            })
            continue

        # 将OpenAI角色映射到Gemini角色
        gemini_role = "model" if role == "assistant" else role

        # 检查是否有tool_calls
        tool_calls = message.get("tool_calls")
        if tool_calls:
            parts = []

            # 如果有文本内容,先添加文本
            if content:
                parts.append({"text": content})

            # 添加每个工具调用
            for tool_call in tool_calls:
                try:
                    args = (
                        json.loads(tool_call["function"]["arguments"])
                        if isinstance(tool_call["function"]["arguments"], str)
                        else tool_call["function"]["arguments"]
                    )

                    function_call_part = {
                        "functionCall": {
                            "id": tool_call.get("id", ""),
                            "name": tool_call["function"]["name"],
                            "args": args
                        },
                        "thoughtSignature": "skip_thought_signature_validator"
                    }
                    parts.append(function_call_part)
                except (json.JSONDecodeError, KeyError):
                    continue

            if parts:
                contents.append({"role": gemini_role, "parts": parts})
            continue

        # 处理普通内容
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        parts.append({"text": part.get("text", "")})
                    elif part.get("type") == "image_url":
                        image_url = part.get("image_url", {}).get("url", "")
                        if image_url and image_url.startswith("data:image/"):
                            import re
                            match = re.match(r"^data:image/(\w+);base64,(.+)$", image_url)
                            if match:
                                mime_type = match.group(1)
                                base64_data = match.group(2)
                                parts.append({
                                    "inlineData": {
                                        "mimeType": f"image/{mime_type}",
                                        "data": base64_data
                                    }
                                })
            if parts:
                contents.append({"role": gemini_role, "parts": parts})
        elif content:
            contents.append({"role": gemini_role, "parts": [{"text": content}]})

    # 构建生成配置
    generation_config = {}
    
    if "temperature" in openai_request:
        generation_config["temperature"] = openai_request["temperature"]
    if "top_p" in openai_request:
        generation_config["topP"] = openai_request["top_p"]
    if "top_k" in openai_request:
        generation_config["topK"] = openai_request["top_k"]
    if "max_tokens" in openai_request or "max_completion_tokens" in openai_request:
        max_tokens = openai_request.get("max_completion_tokens") or openai_request.get("max_tokens")
        if max_tokens:
            generation_config["maxOutputTokens"] = max_tokens
    if "stop" in openai_request:
        stop = openai_request["stop"]
        generation_config["stopSequences"] = [stop] if isinstance(stop, str) else stop
    if "frequency_penalty" in openai_request:
        generation_config["frequencyPenalty"] = openai_request["frequency_penalty"]
    if "presence_penalty" in openai_request:
        generation_config["presencePenalty"] = openai_request["presence_penalty"]
    if "n" in openai_request:
        generation_config["candidateCount"] = openai_request["n"]
    if "seed" in openai_request:
        generation_config["seed"] = openai_request["seed"]

    # 处理 response_format
    if "response_format" in openai_request and openai_request["response_format"]:
        response_format = openai_request["response_format"]
        format_type = response_format.get("type")
        
        if format_type == "json_object":
            generation_config["responseMimeType"] = "application/json"
        elif format_type == "text":
            generation_config["responseMimeType"] = "text/plain"

    # 如果contents为空,添加默认用户消息
    if not contents:
        contents.append({"role": "user", "parts": [{"text": "请根据系统指令回答。"}]})

    # 构建基础请求
    gemini_request = {
        "contents": contents,
        "generationConfig": generation_config
    }

    # 如果有 systemInstruction
    if "systemInstruction" in openai_request:
        gemini_request["systemInstruction"] = openai_request["systemInstruction"]

    return gemini_request
