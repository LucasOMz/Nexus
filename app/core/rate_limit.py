"""Rate limiting simples em memória (janela deslizante).

Usado em endpoints sensíveis (/login e /scan). Para múltiplas réplicas em
produção, troque por um backend Redis (OPCIONAL: a janela por processo já cobre
o caso de implantação single-node do docker-compose).
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock


class SlidingWindowLimiter:
    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window_seconds:
                q.popleft()
            if len(q) >= self.max_requests:
                return False
            q.append(now)
            return True


# 10 tentativas de login por minuto por IP; 120 scans por minuto por usuário.
login_limiter = SlidingWindowLimiter(max_requests=10, window_seconds=60)
scan_limiter = SlidingWindowLimiter(max_requests=120, window_seconds=60)
