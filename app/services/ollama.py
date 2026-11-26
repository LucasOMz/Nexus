"""Configuração efetiva e chamadas à API do Ollama."""
from dataclasses import dataclass
from ipaddress import IPv6Address, ip_address, ip_network
from socket import SOCK_STREAM, getaddrinfo

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.core import ConfiguracaoSistema

_REDES_LOCAIS = tuple(ip_network(rede) for rede in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))


@dataclass(frozen=True)
class ConfigOllama:
    url: str
    modelo: str
    origem: str
    chat_ativo: bool = True
    historico_dias: int | None = None


def config_efetiva(db: Session) -> ConfigOllama:
    salvo = db.execute(
        select(ConfiguracaoSistema.ollama_url, ConfiguracaoSistema.ollama_modelo,
               ConfiguracaoSistema.ollama_chat_ativo, ConfiguracaoSistema.ollama_historico_dias)
        .where(ConfiguracaoSistema.id == 1)
    ).one_or_none()
    chat_ativo = salvo.ollama_chat_ativo if salvo is not None else True
    historico_dias = salvo.ollama_historico_dias if salvo is not None else None
    if salvo and salvo.ollama_url and salvo.ollama_modelo:
        return ConfigOllama(salvo.ollama_url, salvo.ollama_modelo, "administracao", chat_ativo, historico_dias)
    url = settings.nexus_ollama_url.strip()
    return ConfigOllama(url, settings.nexus_ollama_modelo, "ambiente" if url else "sem_configuracao",
                        chat_ativo, historico_dias)


def normalizar_url(valor: str) -> httpx.URL:
    try:
        url = httpx.URL(valor.strip().rstrip("/"))
    except (httpx.InvalidURL, ValueError) as exc:
        raise HTTPException(422, "Informe uma URL HTTP ou HTTPS válida para o Ollama.") from exc
    if (url.scheme not in {"http", "https"} or not url.host or url.port == 0 or
            url.userinfo or url.query or url.fragment or "\\" in valor):
        raise HTTPException(422, "Informe a URL do Ollama sem credenciais, parâmetros ou fragmento.")
    if len(str(url)) > 500:
        raise HTTPException(422, "O endereço do Ollama é longo demais.")
    return url


@dataclass(frozen=True)
class DestinoOllama:
    url: httpx.URL
    endereco: httpx.URL

    def solicitar(self, client: httpx.Client, metodo: str, rota: str, **opcoes) -> httpx.Response:
        caminho = self.endereco.path.rstrip("/") + rota
        return client.request(metodo, self.endereco.copy_with(path=caminho),
                              headers={"Host": self.url.netloc.decode("ascii")},
                              extensions={"sni_hostname": self.url.raw_host.decode("ascii")}, **opcoes)


def destino_ollama(valor: str, *, rede_local: bool) -> DestinoOllama:
    url = normalizar_url(valor)
    if not rede_local:
        return DestinoOllama(url, url)

    # Fixa o IP validado na requisição. O hostname continua sendo usado em
    # Host e na validação TLS, sem uma segunda resolução pelo cliente HTTP.
    try:
        respostas = getaddrinfo(url.raw_host.decode("ascii"), url.port, type=SOCK_STREAM)
    except OSError as exc:
        raise HTTPException(502, "O Nexus não conseguiu localizar o servidor Ollama na rede.") from exc
    for _, _, _, _, sockaddr in respostas:
        ip = ip_address(sockaddr[0])
        original = ip.ipv4_mapped if isinstance(ip, IPv6Address) and ip.ipv4_mapped else ip
        if any(original in rede for rede in _REDES_LOCAIS):
            return DestinoOllama(url, url.copy_with(host=str(original)))
    raise HTTPException(422, "Informe o IP privado ou o nome de rede interna do servidor Ollama.")


def listar_modelos(valor: str) -> list[str]:
    destino = destino_ollama(valor, rede_local=True)
    try:
        with httpx.Client(trust_env=False) as client:
            resposta = destino.solicitar(client, "GET", "/api/tags", timeout=httpx.Timeout(8, connect=4))
        resposta.raise_for_status()
        modelos = resposta.json()["models"]
        if not isinstance(modelos, list):
            raise ValueError("lista inválida")
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "O Ollama demorou para responder ao teste de conexão.") from exc
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(502, "O Nexus não conseguiu listar os modelos. Confira o endereço e se o Ollama está acessível.") from exc

    nomes = set()
    for item in modelos:
        if isinstance(item, dict):
            nome = item.get("name") or item.get("model")
            if isinstance(nome, str) and 0 < len(nome.strip()) <= 250:
                nomes.add(nome.strip())
    return sorted(nomes, key=str.casefold)
