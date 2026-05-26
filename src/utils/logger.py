import logging
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent.parent
LOG_DIR = ROOT / "out" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

def get_logger(name: str) -> logging.Logger:
    """Get a named logger with console + file output."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # Console handler — INFO and above
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s - %(message)s'
    ))

    # File handler — DEBUG and above
    log_file = LOG_DIR / f"{name.replace('.', '_')}.log"
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s - %(message)s'
    ))

    logger.addHandler(console)
    logger.addHandler(file_handler)
    logger.propagate = False  # prevent double logging via root logger
    return logger


class PipelineEventLog:
    """
    Structured JSON log for pipeline events.
    Tracks parse results, gaps, missing data, and downstream impacts.
    """
    def __init__(self, log_name: str):
        self.log_name = log_name
        self.log_file = LOG_DIR / f"{log_name}.json"
        self.events = []
        self.logger = get_logger(f"pipeline.{log_name}")

    def log_success(self, source_file: str, details: dict = {}):
        self._add_event("SUCCESS", source_file, details)
        self.logger.info(f"PASS: {source_file}")

    def log_failure(self, source_file: str, reason: str,
                    downstream_impact: list[str] = []):
        self._add_event("FAILURE", source_file, {
            "reason": reason,
            "downstream_impact": downstream_impact
        })
        self.logger.warning(f"FAIL: {source_file} — {reason}")
        if downstream_impact:
            self.logger.warning(f"  Downstream impact: {', '.join(downstream_impact)}")

    def log_warning(self, source_file: str, reason: str,
                    details: dict = {}):
        self._add_event("WARNING", source_file, {
            "reason": reason,
            **details
        })
        self.logger.warning(f"WARN: {source_file} — {reason}")

    def log_gap(self, source_file: str, gap_type: str,
                missing: str, downstream_impact: list[str] = []):
        """Log a data gap — missing copybook, missing variable, etc."""
        self._add_event("GAP", source_file, {
            "gap_type": gap_type,
            "missing": missing,
            "downstream_impact": downstream_impact
        })
        self.logger.warning(
            f"GAP [{gap_type}]: {source_file} — missing: {missing}"
        )
        if downstream_impact:
            self.logger.warning(
                f"  Downstream impact: {', '.join(downstream_impact)}"
            )

    def _add_event(self, event_type: str, source_file: str, details: dict):
        self.events.append({
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "source_file": source_file,
            "details": details
        })

    def save(self):
        """Save structured event log to JSON."""
        summary = {
            "log_name": self.log_name,
            "generated": datetime.now().isoformat(),
            "total": len(self.events),
            "success": sum(1 for e in self.events if e["type"] == "SUCCESS"),
            "failure": sum(1 for e in self.events if e["type"] == "FAILURE"),
            "warning": sum(1 for e in self.events if e["type"] == "WARNING"),
            "gap": sum(1 for e in self.events if e["type"] == "GAP"),
            "events": self.events
        }
        with open(self.log_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        self.logger.info(
            f"Log saved: {self.log_file} "
            f"(success={summary['success']}, "
            f"failure={summary['failure']}, "
            f"gaps={summary['gap']})"
        )
        return summary
