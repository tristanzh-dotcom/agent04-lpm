from __future__ import annotations

"""
火山方舟视觉 API 最小连通性测试。

运行前：
    export ARK_API_KEY="你的火山方舟 API Key"
    export ARK_ENDPOINT_ID="你的火山方舟专属接入点 ID"
    python3 tests/test_ark_connectivity.py

10 张真实照片灰度测试：
    # 1. 准备一个只包含 10 张照片的小目录，例如：
    mkdir -p /tmp/limb_ark_gray10
    cp /path/to/photo1.jpg /tmp/limb_ark_gray10/
    # 重复放入 10 张真实照片即可。

    # 2. 设置凭证与输出位置：
    export ARK_API_KEY="你的火山方舟 API Key"
    export ARK_ENDPOINT_ID="你的火山方舟专属接入点 ID"
    export LIMB_ARK_DB="data/limb_ark_gray10.sqlite3"
    export LIMB_THUMBNAIL_DIR=".cache/thumbnails"

    # 3. 稳妥并发灰度索引：
    python3 -m backend.ark_index_engine /tmp/limb_ark_gray10 \
      --db "$LIMB_ARK_DB" \
      --concurrency 2 \
      --max-edge 1024

    # 4. 检查结构化 JSON 是否落盘：
    sqlite3 "$LIMB_ARK_DB" \
      'SELECT path, description, tags_json, colors_json FROM photos LIMIT 10;'

    # 5. 检查缩略图是否落盘：
    find "$LIMB_THUMBNAIL_DIR" -maxdepth 1 -name "*.jpg" | head
    ls -lh "$LIMB_THUMBNAIL_DIR"/*.jpg | head
"""

import asyncio
import base64
import io
import os
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image


GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"
MODEL = "doubao-1-5-vision-pro-32k"
PROMPT = "这张图片是什么主色调？请只返回颜色名字，不要返回其他任何字符。"


def create_red_png_bytes() -> bytes:
    """在内存中生成 100x100 纯红 PNG，不读取任何本地图片。"""

    buffer = io.BytesIO()
    Image.new("RGB", (100, 100), (255, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


def is_red_answer(text: str) -> bool:
    normalized = str(text).strip().replace("。", "").replace(".", "")
    return "红色" in normalized or normalized == "红"


def extract_usage(response: Any) -> tuple[int, int, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return (0, 0, 0)
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    total_tokens = int(getattr(usage, "total_tokens", prompt_tokens + completion_tokens) or 0)
    return prompt_tokens, completion_tokens, total_tokens


def render_failure_guide(error: Exception) -> str:
    text = str(error)
    if "401" in text or "Unauthorized" in text or "authentication" in text.lower():
        return (
            "认证/欠费排查：请确认 ARK_API_KEY 是否正确、账号是否有余额、"
            "ARK_ENDPOINT_ID 是否正确，以及该接入点是否已开通视觉模型。"
        )
    if "429" in text or "Rate Limit" in text or "rate limit" in text.lower():
        return "限流排查：当前请求触发 RPM/TPM 限制，请降低并发，例如灰度索引使用 --concurrency 2。"
    return "通用排查：请检查网络、火山方舟服务状态、SDK 版本，以及接入点是否已开通视觉能力。"


async def call_ark_with_image_bytes(image_bytes: bytes):
    """使用 AsyncArk 发起最小视觉请求。

    优先尝试 data URL 形式传入内存图片；如果当前方舟 SDK/接入点不接受 data URL，
    自动退回到临时 PNG 路径，让 SDK 的本地文件托管能力处理上传。临时文件会自动删除。
    """

    try:
        from volcenginesdkarkruntime import AsyncArk
    except ImportError as exc:
        raise RuntimeError(
            "缺少火山方舟 SDK，请先执行：python3 -m pip install --upgrade 'volcengine-python-sdk[ark]'"
        ) from exc

    api_key = os.environ.get("ARK_API_KEY")
    endpoint_id = os.environ.get("ARK_ENDPOINT_ID")
    if not api_key:
        raise RuntimeError("缺少 ARK_API_KEY 环境变量。")
    if not endpoint_id:
        raise RuntimeError("缺少 ARK_ENDPOINT_ID 环境变量。")

    client = AsyncArk(api_key=api_key)
    data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    try:
        return await _create_completion(client, endpoint_id, data_url)
    except Exception as first_error:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as file:
            file.write(image_bytes)
            file.flush()
            try:
                return await _create_completion(client, endpoint_id, str(Path(file.name).resolve()))
            except Exception:
                raise first_error


async def _create_completion(client: Any, endpoint_id: str, image_reference: str):
    return await client.chat.completions.create(
        model=endpoint_id,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": image_reference}},
                ],
            }
        ],
        temperature=0,
    )


async def run_connectivity_test() -> int:
    try:
        response = await call_ark_with_image_bytes(create_red_png_bytes())
        answer = str(response.choices[0].message.content).strip()
        prompt_tokens, completion_tokens, total_tokens = extract_usage(response)
        print(f"模型返回：{answer}")
        print(f"prompt_tokens={prompt_tokens}")
        print(f"completion_tokens={completion_tokens}")
        print(f"total_tokens={total_tokens}")
        if is_red_answer(answer):
            print(f"{GREEN}[SUCCESS] 火山方舟 API 连通性测试完美通过！凭证完全正确。{RESET}")
            return 0
        print(f"{RED}[FAILED] 模型已响应，但答案不是红色，请检查接入点模型是否为视觉模型。{RESET}")
        return 2
    except Exception as exc:
        print(f"{RED}[FAILED] 火山方舟 API 连通性测试失败：{exc}{RESET}")
        print(f"{RED}{render_failure_guide(exc)}{RESET}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_connectivity_test()))
