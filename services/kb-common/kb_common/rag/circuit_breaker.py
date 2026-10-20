"""外接模型服务的连续失败熔断器。

背景：模型服务（embedding/rerank）不可达时，每次调用都要等满 HTTP 超时
（曾为 30s），检索链路串行多库后单次问答耗时 60~95s，期间检索接口还持有
DB 连接，把连接池抽干后整个应用跟着卡。熔断器在连续失败达到阈值后直接
快速失败（调用方立刻降级），冷却期过后放行一次探测请求，成功即恢复。

状态机：CLOSED（正常）→ 连续 failure_threshold 次失败 → OPEN（快速失败）
→ 冷却 cooldown_seconds 后 HALF_OPEN（放行一次探测；再失败立即回 OPEN，
成功回 CLOSED）。
"""
from __future__ import annotations

import threading
import time


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 300.0):
        self._failure_threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        """是否处于快速失败状态；冷却期满时自动转入半开（放行探测）。"""
        with self._lock:
            if self._opened_at is None:
                return False
            if time.monotonic() - self._opened_at >= self._cooldown:
                # 半开：本次调用放行探测；保持 failures 在阈值-1，
                # 探测再失败一次即重新打开，无需重新累计。
                self._failures = self._failure_threshold - 1
                self._opened_at = None
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._failure_threshold:
                self._opened_at = time.monotonic()

    def reset(self) -> None:
        """测试/运维重置。"""
        with self._lock:
            self._failures = 0
            self._opened_at = None
