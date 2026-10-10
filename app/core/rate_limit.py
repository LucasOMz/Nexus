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

# Teto GERAL da API, por usuário (ou IP, para quem não está autenticado).
#
# 600 por minuto é folgado de propósito. Uma tela do sistema faz de 5 a 10
# chamadas, e quem clica rápido não passa perto disso — o limite existe para
# travar **varredura**, não uso. Um teto apertado quebraria a navegação
# normal e seria afrouxado no primeiro chamado, voltando a não proteger nada.
#
# Vale só por processo. Com múltiplas réplicas cada uma tem o seu contador, e
# o teto efetivo é N vezes maior — por isso o limite por IDENTIDADE (o do
# login) continua sendo o que realmente importa.
api_limiter = SlidingWindowLimiter(max_requests=600, window_seconds=60)


def chave_do_cliente(request) -> str:
    """Quem está fazendo a requisição — é o que o limite conta.

    Usuário autenticado vem primeiro: é a identidade estável, e sem ela
    quatro pessoas atrás do mesmo NAT dividiriam o mesmo teto — punindo o
    grupo pelo consumo de um.

    Sem token, cai para o IP. `X-Forwarded-For` só entra quando existe, e
    pega o PRIMEIRO endereço: é o cliente original; os demais são proxies.
    """
    usuario = getattr(getattr(request, "state", None), "usuario_id", None)
    if usuario:
        return f"u:{usuario}"

    encaminhado = request.headers.get("x-forwarded-for")
    if encaminhado:
        primeiro = encaminhado.split(",")[0].strip()
        if primeiro:
            return f"ip:{primeiro}"

    cliente = getattr(request, "client", None)
    return f"ip:{cliente.host}" if cliente else "ip:desconhecido"
