import re


class RegexRedactor:
    def __init__(self, patterns: list[str], replacement: str = "[REDACTED]") -> None:
        self._patterns = tuple(re.compile(pattern) for pattern in patterns)
        self._replacement = replacement

    def __call__(self, value: str) -> str:
        for pattern in self._patterns:
            value = pattern.sub(self._replacement, value)
        return value
