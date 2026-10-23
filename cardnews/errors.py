"""API_SPEC 0.4의 오류 코드. HTTP 응답과 run.error가 같은 모양을 써요."""

STATUS = {
    "VALIDATION_ERROR": 422,
    "NOT_FOUND": 404,
    "STAGE_CONFLICT": 409,
    "VERSION_CONFLICT": 409,
    "IDEMPOTENCY_CONFLICT": 409,
    "RUN_IN_PROGRESS": 409,
    "QUESTION_STALE": 409,
    "ALREADY_ANSWERED": 409,
    "AUTH_REQUIRED": 503,
    "TOOL_UNAVAILABLE": 503,
    "SEARCH_FAILED": 502,
    "ENGINE_OUTPUT_INVALID": 502,
    "IMAGE_FAILED": 502,
    "RENDER_FAILED": 500,
    "CANCELLED": 409,
    "INTERRUPTED": 409,
    "INTERNAL_ERROR": 500,
}

NEXT_ACTIONS = {
    "VALIDATION_ERROR": ["fix_input"],
    "NOT_FOUND": ["go_home"],
    "STAGE_CONFLICT": ["reload"],
    "VERSION_CONFLICT": ["reload"],
    "IDEMPOTENCY_CONFLICT": ["reload"],
    "RUN_IN_PROGRESS": ["wait", "cancel"],
    "QUESTION_STALE": ["reload"],
    "ALREADY_ANSWERED": ["reload"],
    "AUTH_REQUIRED": ["login", "retry"],
    "TOOL_UNAVAILABLE": ["install", "retry"],
    "SEARCH_FAILED": ["retry"],
    "ENGINE_OUTPUT_INVALID": ["retry"],
    "IMAGE_FAILED": ["retry_card"],
    "RENDER_FAILED": ["retry_card"],
    "CANCELLED": ["restart"],
    "INTERRUPTED": ["continue", "restart"],
    "INTERNAL_ERROR": ["retry"],
}


class AppError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None,
                 next_actions: list[str] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.next_actions = next_actions or NEXT_ACTIONS.get(code, [])

    @property
    def status(self) -> int:
        return STATUS.get(self.code, 500)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "nextActions": self.next_actions,
            "details": self.details,
        }
