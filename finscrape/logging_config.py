"""
Structured logging for FinScrape pipeline.
"""
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

# Per-request / per-cycle correlation id. The API sets it from the X-Request-ID
# header (or a generated uuid) per request; the worker sets it per source cycle.
# Both formatters read it, so every log line is traceable to one unit of work.
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")

# Record attributes that logging always sets — anything else on a record is a
# caller-supplied extra worth emitting in JSON.
_LOG_RESERVED = frozenset(
    vars(logging.makeLogRecord({})).keys()
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """One JSON object per line: ts, level, logger, msg, correlation id + any extras.

    Loki/Alloy ingest these directly; no regex parsing of the human format.
    """

    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": datetime.fromtimestamp(
                record.created, timezone.utc
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
        return json.dumps(out, default=str)


class FinScrapeFormatter(logging.Formatter):
    """Custom formatter with structured context."""

    def format(self, record):
        # Base format
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
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
            return f"{ts} | {level:8s} | {ctx} | {record.getMessage()}"
        else:
            return f"{ts} | {level:8s} | {record.getMessage()}"


def setup_logging(
    level: str = "INFO", log_file: str | None = None, json_format: bool = False
) -> None:
    """Configure logging for the whole process (root logger).

    Attaches one stream handler — human format by default, one-line JSON when
    json_format=True (containers, so Alloy/Loki get structured records).
    Idempotent: clears prior handlers so repeated calls don't double-log.
    """
    formatter = JsonFormatter() if json_format else FinScrapeFormatter()

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for h in root.handlers[:]:
        root.removeHandler(h)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    root.addHandler(console)

    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setFormatter(formatter)
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
