"""Logging with a redaction filter. Tokens, codes and secrets never reach logs."""

import logging
import re

_PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)((?:access|refresh|id)_token[\"']?\s*[:=]\s*[\"']?)[^\"'&\s,}]+"),
    re.compile(r"(?i)((?:client_secret|code_verifier|code|password|state)[\"']?\s*[:=]\s*[\"']?)[^\"'&\s,}]+"),
    re.compile(r"\b(ya29\.)[A-Za-z0-9._-]+"),
    re.compile(r"\b(xox[abposr]-)[A-Za-z0-9-]+"),
    re.compile(r"\b(gh[uprs]_)[A-Za-z0-9]+"),
    re.compile(r"\b(ntn_|secret_)[A-Za-z0-9]+"),
    re.compile(r"(postgres(?:ql)?://[^:/\s]+:)[^@\s]+"),
]
# Personal data: never written to logs either.
_PII = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[CARD]"),
    (re.compile(r"(?<![\w.])\+?\d{1,3}[ .-]?\(?\d{2,4}\)?[ .-]?\d{3,4}[ .-]?\d{3,4}\b"), "[PHONE]"),
]


def redact(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(r"\1[REDACTED]", text)
    for pattern, label in _PII:
        text = pattern.sub(label, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if record.exc_info:
            # Tracebacks can embed values; redact them too and drop the raw exc_info.
            msg += "\n" + logging.Formatter().formatException(record.exc_info)
            record.exc_info = None
            record.exc_text = None
        record.msg = redact(msg)
        record.args = None
        return True


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # httpx logs full request URLs (which can carry codes); keep it quiet.
    logging.getLogger("httpx").setLevel(logging.WARNING)
