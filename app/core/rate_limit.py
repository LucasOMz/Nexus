"""Janela deslizante compartilhada entre as instâncias da API."""
from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections import defaultdict, deque
from threading import Lock

from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

from app.config import settings

log = logging.getLogger(__name__)

_DECIDIR = """
local relogio = redis.call('TIME')
local agora = tonumber(relogio[1]) * 1000 + math.floor(tonumber(relogio[2]) / 1000)
local janela = tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', agora - janela)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then
    return 0
end
redis.call('ZADD', KEYS[1], agora, ARGV[3])
redis.call('PEXPIRE', KEYS[1], janela)
return 1
"""


class RedisContadores:
    def __init__(self, url: str) -> None:
        self._cliente = Redis.from_url(
            url, socket_connect_timeout=0.25, socket_timeout=0.5, retry=Retry(NoBackoff(), 0),
        )
        self._decidir = self._cliente.register_script(_DECIDIR)
        self._retentar_em = 0.0
        self._avisar_em = 0.0
        self._lock = Lock()

    def fechar(self) -> None:
        self._cliente.close()

    def is_allowed(self, grupo: str, chave: str, janela: int, maximo: int) -> bool | None:
        agora = time.monotonic()
        if agora < self._retentar_em:
            return None
        identidade = hashlib.sha256(chave.encode()).hexdigest()
        try:
            return bool(self._decidir(
                keys=[f"nexus:limite:v1:{grupo}:{identidade}"],
                args=[janela * 1000, maximo, uuid.uuid4().hex],
            ))
        except RedisError as exc:
            with self._lock:
                agora = time.monotonic()
                self._retentar_em = agora + 1
                if agora >= self._avisar_em:
                    self._avisar_em = agora + 30
                    log.warning("Redis indisponível para o rate limit. Usando contadores locais (%s).",
                                type(exc).__name__)
            return None


class SlidingWindowLimiter:
    def __init__(
        self, max_requests: int, window_seconds: int, *, redis: RedisContadores | None = None, grupo: str = "",
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._redis = redis
        self._grupo = grupo
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()
        self._limpar_em = 0.0

    def is_allowed(self, key: str) -> bool:
        decisao = self._redis.is_allowed(self._grupo, key, self.window_seconds, self.max_requests) if self._redis else None
        if decisao is False:
            return False
        # Espelha os envios aceitos para manter a proteção durante falhas do Redis.
        permitido_local = self._permitir_local(key)
        return permitido_local if decisao is None else decisao

    def _permitir_local(self, key: str) -> bool:
        now = time.monotonic()
        corte = now - self.window_seconds
        with self._lock:
            if now >= self._limpar_em:
                expiradas = [k for k, fila in self._hits.items() if not fila or fila[-1] <= corte]
                for k in expiradas:
                    del self._hits[k]
                self._limpar_em = now + self.window_seconds
            q = self._hits[key]
            while q and q[0] <= corte:
                q.popleft()
            if len(q) >= self.max_requests:
                return False
            q.append(now)
            return True


_redis_url = settings.rate_limit_redis_url.get_secret_value().strip()
redis_contadores = RedisContadores(_redis_url) if _redis_url else None

# 10 tentativas de login por minuto por IP e 120 scans por minuto por usuário.
login_limiter = SlidingWindowLimiter(10, 60, redis=redis_contadores, grupo="login")
scan_limiter = SlidingWindowLimiter(120, 60, redis=redis_contadores, grupo="scan")

# Teto GERAL da API, por usuário (ou IP, para quem não está autenticado).
#
# 600 por minuto é folgado de propósito. Uma tela do sistema faz de 5 a 10
# chamadas, e quem clica rápido não passa perto disso — o limite existe para
# travar **varredura**, não uso. Um teto apertado quebraria a navegação
# normal e seria afrouxado no primeiro chamado, voltando a não proteger nada.
#
api_limiter = SlidingWindowLimiter(600, 60, redis=redis_contadores, grupo="api")


def chave_do_cliente(request) -> str:
    """Quem está fazendo a requisição — é o que o limite conta.

    Usuário autenticado vem primeiro: é a identidade estável, e sem ela
    quatro pessoas atrás do mesmo NAT dividiriam o mesmo teto — punindo o
    grupo pelo consumo de um.

    Sem token, usa o endereço que o servidor ASGI apurou. O Uvicorn
    resolve o IP encaminhado somente para proxies de confiança.
    """
    usuario = getattr(getattr(request, "state", None), "usuario_id", None)
    if usuario:
        return f"u:{usuario}"

    cliente = getattr(request, "client", None)
    return f"ip:{cliente.host}" if cliente else "ip:desconhecido"
