"""Transporte para provedores externos com suporte a ferramentas de chat."""
from dataclasses import dataclass, field
import json
from typing import Literal

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.cripto import decifrar
from app.models.core import ConfiguracaoSistema

ProvedorExterno = Literal["openai", "openrouter"]
_ROTAS = {
    "openai": ("https://api.openai.com/v1/chat/completions", "max_completion_tokens"),
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions", "max_tokens"),
}


@dataclass(frozen=True)
class DestinoExterno:
    provedor: ProvedorExterno
    modelo: str
    token: str = field(repr=False)

    def perguntar(self, client, mensagens, timeout, *, ferramentas=None, escolha=None, limite=800):
        url, campo_limite = _ROTAS[self.provedor]
        payload = {"model": self.modelo, "messages": mensagens, campo_limite: limite}
        if self.provedor == "openai":
            payload["store"] = False
        if ferramentas:
            payload["tools"] = ferramentas
        if escolha:
            payload["tool_choice"] = {"type": "function", "function": {"name": escolha}}
        try:
            resposta = client.post(url, json=payload, headers={"Authorization": f"Bearer {self.token}"}, timeout=timeout)
            if resposta.status_code in (401, 403):
                raise HTTPException(502, "O provedor recusou a chave de API ou o acesso ao modelo.")
            if resposta.status_code in (402, 429):
                raise HTTPException(502, "O provedor retornou um limite de uso ou cobrança. Confira sua conta.")
            if resposta.status_code in (400, 404):
                raise HTTPException(502, "O provedor recusou o modelo ou a chamada de ferramentas. Confira o modelo escolhido.")
            resposta.raise_for_status()
            mensagem = resposta.json()["choices"][0]["message"]
            if not isinstance(mensagem, dict):
                raise ValueError("mensagem inválida")
        except httpx.TimeoutException:
            raise HTTPException(504, "O provedor externo demorou demais para responder.") from None
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
            raise HTTPException(502, "O Nexus não conseguiu consultar o provedor externo.") from None
        # A API externa entrega os argumentos como JSON em texto. O executor
        # do Nexus continua validando o esquema e as permissões de cada consulta.
        chamadas = []
        recebidas = mensagem.get("tool_calls")
        for chamada in recebidas[:3] if isinstance(recebidas, list) else []:
            try:
                funcao = chamada["function"]
                chamadas.append({"function": {
                    "name": funcao["name"], "arguments": json.loads(funcao["arguments"]),
                }})
            except (TypeError, KeyError, ValueError):
                continue
        return {"content": mensagem.get("content"), "tool_calls": chamadas}


def destino_externo(db: Session) -> DestinoExterno | None:
    cfg = db.get(ConfiguracaoSistema, 1)
    if cfg is None or not cfg.ia_externa_ativa:
        return None
    token = decifrar(cfg.ia_token_externo)
    if cfg.ia_provedor_externo not in _ROTAS or not cfg.ia_modelo_externo or not token:
        raise HTTPException(503, "Peça à TI para conferir o provedor, o modelo e a chave do Agente de IA.")
    return DestinoExterno(cfg.ia_provedor_externo, cfg.ia_modelo_externo, token)


def testar_destino(destino: DestinoExterno) -> None:
    nome = "confirmar_conexao"
    with httpx.Client(trust_env=False) as client:
        resposta = destino.perguntar(
            client, [{"role": "user", "content": "Chame a ferramenta confirmar_conexao."}],
            httpx.Timeout(12, connect=5), limite=220, escolha=nome,
            ferramentas=[{"type": "function", "function": {
                "name": nome, "description": "Confirma a conectividade sem consultar dados do Nexus.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            }}],
        )
    if not any(chamada["function"]["name"] == nome for chamada in resposta["tool_calls"]):
        raise HTTPException(502, "O modelo não confirmou suporte às ferramentas do chat.")
