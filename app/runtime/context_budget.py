from dataclasses import dataclass


@dataclass(frozen=True)
class ContextBudgetConfig:
    max_input_tokens: int = 32000
    reserved_output_tokens: int = 4000
    safety_margin_tokens: int = 2000
    recent_window_tokens: int = 12000

    @property
    def working_input_tokens(self) -> int:
        return max(
            0,
            self.max_input_tokens
            - self.reserved_output_tokens
            - self.safety_margin_tokens,
        )

    @property
    def effective_recent_window_tokens(self) -> int:
        return min(self.recent_window_tokens, self.working_input_tokens)
