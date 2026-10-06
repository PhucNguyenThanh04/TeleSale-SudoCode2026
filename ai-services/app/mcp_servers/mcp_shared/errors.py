"""Stable business errors returned through MCP without leaking internals."""


class ToolError(Exception):
    def __init__(self, code: str, **details: object) -> None:
        self.code = code
        self.details = details
        super().__init__(code)


def tool_result_error(exc: ToolError) -> dict:
    return {"error": exc.code, **exc.details}
