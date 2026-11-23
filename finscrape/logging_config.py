"""
Structured logging for FinScrape pipeline.

Every line passes a secret filter before it is formatted (plan M1.6): a credential that
reaches a log is a credential in Loki, in a GitHub Action transcript and in whatever
forwarded the line. The filter scrubs the values of the secret env vars and any
`scheme://user:password@host` DSN, so a careless `log.info("dsn=%s", dsn)` cannot leak.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

from finscrape import settings

# Per-request / per-cycle correlation id. The API sets it from the X-Request-ID
# header (or a generated uuid) per request; the worker sets it per source cycle.
# Both formatters read it, so every log line is traceable to one unit of work.
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")

# Record attributes that logging always sets — anything else on a record is a
# caller-supplied extra worth emitting in JSON.
_LOG_RESERVED = frozenset(
    vars(logging.makeLogRecord({})).keys()
) | {"message", "asctime", "taskName"}


# Env vars whose VALUES must never appear in a log line (plan M1.6).
SECRET_ENV_VARS = (
    "FINSCRAPE_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_WEBHOOK_SECRET",
    "ANALYZE_DISPATCH_TOKEN",
    "WORLDFIN_DATABASE_URL",
    "WORLDFIN_REDIS_URL",
    "FINSCRAPE_MODEL_API_KEY",
)
REDACTED = "<redacted>"
# scheme://user:password@host — the shape of a DSN, scrubbed even if the value is not
# one of the configured secrets (a derived URL, a logged exception, a test fixture).
_DSN_CREDENTIALS = re.compile(r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)[^/:@\s]+:[^@\s]+@")
# Values shorter than this are too generic to scrub without eating the message.
_MIN_SECRET_LEN = 6


def secret_values(environ=None) -> list[str]:
    """The currently configured secrets, longest first so a substring cannot survive."""
    env = settings.environ() if environ is None else environ
    values = [env.get(name, "") for name in SECRET_ENV_VARS]
    return sorted({v for v in values if len(v) >= _MIN_SECRET_LEN}, key=len, reverse=True)


def scrub(text: str, secrets: list[str] | None = None) -> str:
    """Replace every known secret and any `user:password@` DSN credential."""
    if not text:
        return text
    for value in secret_values() if secrets is None else secrets:
        text = text.replace(value, REDACTED)
    return _DSN_CREDENTIALS.sub(lambda m: m.group("scheme") + REDACTED + "@", text)


class RedactSecrets(logging.Filter):
    """Scrub secrets from the message, its args, the exception text and any extras.

    Runs before the formatter, so neither the human format nor the JSON one can print a
    credential. `record.args` is folded into the message, because a formatter resolves
    `%s` later and would otherwise re-insert the raw value.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        secrets = secret_values()
        message = record.getMessage()
        clean = scrub(message, secrets)
        if record.exc_info and record.exc_info[1] is not None:
            clean += "\n" + scrub(str(record.exc_info[1]), secrets)
        for key, value in list(record.__dict__.items()):
            if isinstance(value, str) and key not in ("name", "levelname", "pathname"):
                record.__dict__[key] = scrub(value, secrets)
        if clean != message or record.args:
            record.msg, record.args = clean, ()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line: ts, level, logger, msg, correlation id + any extras.

    Loki/Alloy ingest these directly; no regex parsing of the human format.
    """

    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": datetime.fromtimestamp(
                record.created, UTC
            ).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        cid = correlation_id.get()
        if cid:
            out["correlation_id"] = cid
        # Surface structured extras (source/ticker/stage/…) as top-level fields.
        for k, v in record.__dict__.items():
            if k not in _LOG_RESERVED and not k.startswith("_"):
                out[k] = v
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        # The filter scrubs the message; the traceback is formatted here, so scrub the
        # whole line as well — an exception body can carry a DSN too.
        return scrub(json.dumps(out, default=str))


class FinScrapeFormatter(logging.Formatter):
    """Custom formatter with structured context."""

    def format(self, record):
        # Base format
        ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        level = record.levelname

        # Extract context from record extras
        source = getattr(record, 'source', '')
        ticker = getattr(record, 'ticker', '')
        stage = getattr(record, 'stage', '')

        # Build context string
        ctx_parts = []
        cid = correlation_id.get()
        if cid:
            ctx_parts.append(f"cid={cid}")
        if source:
            ctx_parts.append(f"src={source}")
        if ticker:
            ctx_parts.append(f"tick={ticker}")
        if stage:
            ctx_parts.append(f"stage={stage}")
        ctx = " | ".join(ctx_parts)

        if ctx:
            return scrub(f"{ts} | {level:8s} | {ctx} | {record.getMessage()}")
        else:
            line = f"{ts} | {level:8s} | {record.getMessage()}"
            if record.exc_info:
                line += "\n" + self.formatException(record.exc_info)
            return scrub(line)


def setup_logging(
    level: str = "INFO",
    log_file: str | None = None,
    json_format: bool = False,
    stream=None,
) -> None:
    """Configure logging for the whole process (root logger).

    Attaches one stream handler — human format by default, one-line JSON when
    json_format=True (containers, so Alloy/Loki get structured records) — with the
    secret filter in front of it. Idempotent: clears prior handlers so repeated calls
    don't double-log.
    """
    formatter = JsonFormatter() if json_format else FinScrapeFormatter()
    redactor = RedactSecrets()

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for h in root.handlers[:]:
        root.removeHandler(h)

    console = logging.StreamHandler(stream or sys.stderr)
    console.setFormatter(formatter)
    console.addFilter(redactor)
    root.addHandler(console)
    # Filters on a logger only see records logged *through* it; the handler filter is
    # what catches a propagated record from any `worldfin.*` / `finscrape.*` logger.
    root.addFilter(redactor)

    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setFormatter(formatter)
        fh.addFilter(redactor)
        root.addHandler(fh)

    # finscrape stays at the requested level even if root is noisier elsewhere.
    logging.getLogger("finscrape").setLevel(
        getattr(logging, level.upper(), logging.INFO)
    )
    # Suppress noisy third-party loggers
    for name in ("urllib3", "curl_cffi", "httpx", "yfinance"):
        logging.getLogger(name).setLevel(logging.WARNING)


class PipelineLogger:
    """Context-aware logger for pipeline stages."""

    def __init__(self, source: str = "", stage: str = ""):
        self._logger = logging.getLogger("finscrape.pipeline")
        self.source = source
        self.stage = stage

    def _extra(self, ticker: str = "") -> dict:
        return {"source": self.source, "stage": self.stage, "ticker": ticker}

    def info(self, msg: str, ticker: str = "", *args):
        self._logger.info(msg, *args, extra=self._extra(ticker))

    def warning(self, msg: str, ticker: str = "", *args):
        self._logger.warning(msg, *args, extra=self._extra(ticker))

    def error(self, msg: str, ticker: str = "", *args):
        self._logger.error(msg, *args, extra=self._extra(ticker))

    def debug(self, msg: str, ticker: str = "", *args):
        self._logger.debug(msg, *args, extra=self._extra(ticker))

    def with_source(self, source: str) -> PipelineLogger:
        return PipelineLogger(source=source, stage=self.stage)

    def with_stage(self, stage: str) -> PipelineLogger:
        return PipelineLogger(source=self.source, stage=stage)
