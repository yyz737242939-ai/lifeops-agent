"""Safe typed failures raised at Executor adapter boundaries."""


class ExecutorModelError(Exception):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class InvalidExecutorModelActionError(ExecutorModelError):
    pass
