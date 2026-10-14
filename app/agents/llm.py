"""LLM 封装：输入 system / user 文本和 Pydantic schema，返回校验过的 schema 实例。

节点只依赖 StructuredLLM 这个调用签名，测试时可以注入假实现，不需要 API key。
"""

from typing import Awaitable, Callable, Type, TypeVar

from pydantic import BaseModel

from app.config import Settings

T = TypeVar("T", bound=BaseModel)

StructuredLLM = Callable[[Type[T], str, str], Awaitable[T]]


class LLMError(Exception):
    pass


def make_deepseek_llm(settings: Settings) -> StructuredLLM:
    if not settings.deepseek_api_key:
        raise LLMError("DEEPSEEK_API_KEY is not configured")

    from langchain_deepseek import ChatDeepSeek

    chat = ChatDeepSeek(
        model=settings.deepseek_model,
        temperature=settings.llm_temperature,
        api_key=settings.deepseek_api_key,
        timeout=settings.llm_timeout_s,
        max_retries=1,
    )

    async def call(schema: Type[T], system: str, user: str) -> T:
        # DeepSeek 不支持严格的 json_schema 模式；function calling 输出再经 Pydantic 校验
        runnable = chat.with_structured_output(schema, method="function_calling")
        try:
            result = await runnable.ainvoke([("system", system), ("user", user)])
        except Exception as e:  # 网络错误、校验失败等统一转换，不把请求细节带出去
            raise LLMError(f"{e.__class__.__name__}: {str(e)[:200]}") from e
        if not isinstance(result, schema):
            raise LLMError("LLM returned no structured output")
        return result

    return call
