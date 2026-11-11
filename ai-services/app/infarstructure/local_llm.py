"""Bounded recovery for truncated or malformed nonstreaming local tool output."""
from langchain_core.messages.ai import add_usage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_openai import ChatOpenAI
from pydantic import Field


class LocalToolOutputError(ValueError):
    def __init__(self, code: str, reason: str):
        self.code = code
        super().__init__(f'{code}: {reason}')


class LocalChatOpenAI(ChatOpenAI):
    context_window: int = Field(default=8192, ge=256)

    def bind_tools(self, tools, *, strict=None, parallel_tool_calls=None, **kwargs):
        # Apply to the first request for both the business agent and LangMem.
        # Keep tool_choice=auto available: ordinary replies need no tool call.
        formatted = [convert_to_openai_tool(tool, strict=True) for tool in tools]
        # Already formatted dict tools bypass LangChain's strict conversion.
        formatted = [{**tool, 'function': {**tool['function'], 'strict': True}}
                     if tool.get('type') == 'function' else tool for tool in formatted]
        return super().bind_tools(formatted, strict=True,
                                  parallel_tool_calls=parallel_tool_calls, **kwargs)

    @staticmethod
    def _truncated(result):
        return any((generation.generation_info or {}).get('finish_reason') == 'length'
                   for generation in result.generations)

    @staticmethod
    def _invalid_tools(result):
        # Hermes returns the original tool markup as plain content on parse
        # failure. LangChain can also expose malformed structured arguments.
        return any(generation.message.invalid_tool_calls or (
            isinstance(generation.message.content, str)
            and '<tool_call>' in generation.message.content)
            for generation in result.generations)

    def _recovery_options(self, result, kwargs):
        if not kwargs.get('tools') or kwargs.get('stream') or self.streaming:
            return None
        truncated, invalid = self._truncated(result), self._invalid_tools(result)
        if not truncated and not invalid:
            return None
        options = self._retry_options(result, kwargs) if truncated else dict(kwargs)
        if invalid:
            if kwargs.get('tool_choice') == 'none':
                raise LocalToolOutputError('local_tool_output_invalid', 'tool output was disabled')
            if kwargs.get('tool_choice') in (None, 'auto'):
                options['tool_choice'] = 'required'
            options['parallel_tool_calls'] = False
        return options

    def _retry_options(self, result, kwargs):
        budget = kwargs.get('max_completion_tokens', kwargs.get('max_tokens', self.max_tokens))
        usage = (result.llm_output or {}).get('token_usage') or {}
        prompt = usage.get('prompt_tokens')
        if type(prompt) is not int or type(budget) is not int:
            raise LocalToolOutputError('local_tool_output_truncated', 'missing token budget or usage')
        enlarged = min(budget * 2, 4096, self.context_window - prompt)
        if enlarged <= budget:
            raise LocalToolOutputError('local_tool_output_truncated', 'no room for a larger completion')
        options = {key: value for key, value in kwargs.items() if key != 'max_tokens'}
        options['max_completion_tokens'] = enlarged
        return options

    def _finish_retry(self, first, second):
        if self._truncated(second):
            raise LocalToolOutputError('local_tool_output_truncated', 'retry also reached its token limit')
        if self._invalid_tools(second):
            raise LocalToolOutputError('local_tool_output_invalid', 'retry also returned malformed tool output')
        if self._invalid_tools(first) and not all(
                generation.message.tool_calls for generation in second.generations):
            raise LocalToolOutputError('local_tool_output_invalid', 'retry returned no required tool call')
        # Account for both requests, including tokens spent on the discarded output.
        for generation, previous in zip(second.generations, first.generations):
            generation.message.usage_metadata = add_usage(
                previous.message.usage_metadata, generation.message.usage_metadata)
        old = (first.llm_output or {}).get('token_usage') or {}
        if second.llm_output is not None:
            usage = second.llm_output.setdefault('token_usage', {})
            for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
                if type(old.get(key)) is int and type(usage.get(key)) is int:
                    usage[key] += old[key]
        return second

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        result = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        options = self._recovery_options(result, kwargs)
        if options is None:
            return result
        retry = super()._generate(messages, stop=stop, run_manager=run_manager, **options)
        return self._finish_retry(result, retry)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        result = await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
        options = self._recovery_options(result, kwargs)
        if options is None:
            return result
        retry = await super()._agenerate(messages, stop=stop, run_manager=run_manager, **options)
        return self._finish_retry(result, retry)
