"""Rate-limit parsing and conservative wait decisions."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable


class RateLimitManager:
    def __init__(self, threshold: int, wait_enabled: bool, max_wait_seconds: int,
                 sleep: Callable[[float], None] = time.sleep, logger: logging.Logger | None = None) -> None:
        self.threshold = threshold
        self.wait_enabled = wait_enabled
        self.max_wait_seconds = max_wait_seconds
        self.sleep = sleep
        self.logger = logger or logging.getLogger("pr_dataset")

    def handle(self, rate_limit: dict[str, Any] | None) -> None:
        if not rate_limit:
            return
        remaining = rate_limit.get("remaining")
        self.logger.info("GraphQL request successful; cost=%s remaining=%s reset=%s",
                         rate_limit.get("cost"), remaining, rate_limit.get("resetAt"))
        if not isinstance(remaining, int) or remaining > self.threshold:
            return
        self.logger.warning("GitHub rate limit is low: %s remaining (threshold %s)", remaining, self.threshold)
        if not self.wait_enabled or remaining > 0:
            return
        reset_at = rate_limit.get("resetAt")
        try:
            reset = datetime.fromisoformat(str(reset_at).replace("Z", "+00:00"))
            seconds = max(0, (reset - datetime.now(timezone.utc)).total_seconds()) + 1
        except (TypeError, ValueError):
            self.logger.warning("Cannot parse rate-limit reset time: %r", reset_at)
            return
        if seconds <= self.max_wait_seconds:
            self.logger.warning("Rate limit exhausted; waiting %.0f seconds for reset", seconds)
            self.sleep(seconds)
        else:
            self.logger.warning("Rate limit reset is %.0f seconds away; not sleeping beyond configured maximum", seconds)

