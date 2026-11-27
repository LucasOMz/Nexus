import { api, expirarSessao } from "./api.js";
import { state } from "./state.js";

const INTERVALO_ENVIO_MS = 15 * 1000;
const CHAVE_POLITICA = "nexus.inatividadeMinutos";

export function atualizarPrazoSessao(minutos) {
  if (!Number.isInteger(minutos) || minutos < 1 || minutos > 1440) return;
  localStorage.setItem(CHAVE_POLITICA, String(minutos));
  window.dispatchEvent(new Event("nexus:politica-sessao"));
}

export function monitorarSessao() {
  const inicio = Date.now();
  let prazo;
  let envio;
  let ultimoEnvio = 0;
  let ultimaInteracao = 0;
  const eventos = new AbortController();

  function verificar() {
    clearTimeout(prazo);
    if (!state.isAuthed) return false;
    const minutos = Number(localStorage.getItem(CHAVE_POLITICA)) || 10;
    const restante = (state.ultimaAtividade || inicio) + minutos * 60000 - Date.now();
    if (!state.sessaoCompartilhada || restante <= 0) {
      expirarSessao();
      return false;
    }
    prazo = setTimeout(verificar, restante);
    return true;
  }

  function enviarAtividade() {
    envio = undefined;
    if (!verificar()) return;
    const agora = Date.now();
    const atraso = Math.max(0, agora - ultimaInteracao);
    // Uma aba suspensa pode acordar muito depois do evento original.
    if (atraso > 30000) return;
    ultimoEnvio = agora;
    api.request("POST", "/auth/atividade", {
      query: { atraso_ms: atraso }, enfileirar: false, prazoMs: 10000, keepalive: true,
    }).catch(() => {});
  }

  function interagir(evento) {
    if (!evento.isTrusted || document.hidden) return;
    const agora = Date.now();
    if (agora - ultimaInteracao < 250 || !verificar()) return;
    ultimaInteracao = agora;
    state.marcarAtividade(agora);
    if (envio === undefined) {
      const espera = INTERVALO_ENVIO_MS - (agora - ultimoEnvio);
      if (espera <= 0) enviarAtividade();
      else envio = setTimeout(enviarAtividade, espera);
    }
  }

  const opcoes = { signal: eventos.signal, capture: true, passive: true };
  for (const tipo of ["pointerdown", "pointermove", "keydown", "wheel", "touchmove"]) {
    document.addEventListener(tipo, interagir, opcoes);
  }
  document.addEventListener("visibilitychange", verificar, opcoes);
  window.addEventListener("focus", verificar, opcoes);
  window.addEventListener("pagehide", () => {
    if (envio === undefined) return;
    clearTimeout(envio);
    enviarAtividade();
  }, opcoes);
  window.addEventListener("pageshow", verificar, opcoes);
  window.addEventListener("nexus:politica-sessao", verificar, opcoes);
  window.addEventListener("storage", (event) => {
    if ([null, "gp_access", "gp_atividade", CHAVE_POLITICA].includes(event.key)) verificar();
  }, opcoes);
  async function consultarPolitica() {
    if (!state.isAuthed) return;
    try {
      const politica = await api.get("/auth/politica-sessao");
      if (state.isAuthed) atualizarPrazoSessao(politica.inatividade_minutos);
    } catch { /* o prazo conhecido continua valendo com a rede indisponível */ }
  }
  const consulta = setInterval(consultarPolitica, 30000);
  consultarPolitica();
  window.addEventListener("nexus:sessao-expirada", () => {
    clearTimeout(prazo);
    clearTimeout(envio);
    clearInterval(consulta);
    eventos.abort();
  }, { once: true });

  return verificar;
}
