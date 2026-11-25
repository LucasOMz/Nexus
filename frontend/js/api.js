/**
 * Cliente HTTP da API com JWT, refresh automático e fila offline.
 * @module api
 */
import { state } from "./state.js";
import { enqueue, pending, dequeue } from "./offline.js";
import { mensagemErro, camposComErro } from "./erros.js";

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
  }
}

const BASE = "/api/v1";

function incluirPlanta(headers) {
  if (state.plantaAtiva) headers["X-Planta-Id"] = String(state.plantaAtiva);
  else if (state.isAdmin) headers["X-Planta-Id"] = "todas";
}

let renovacaoEmCurso;

function comTravaDeSessao(operacao) {
  return globalThis.navigator?.locks?.request("nexus-sessao", operacao) ?? operacao();
}

function refreshTokens(acessoQueFalhou) {
  if (state.access !== acessoQueFalhou) return Boolean(state.access);
  renovacaoEmCurso ??= comTravaDeSessao(async () => {
    if (state.access !== acessoQueFalhou) return Boolean(state.access);
    if (state.sincronizarSessao()) return true;
    const refresh = state.refresh;
    if (!refresh) return false;
    let res;
    try {
      res = await fetch(`${BASE}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
        signal: AbortSignal.timeout(10000),
      });
    } catch {
      return false;
    }
    if (state.refresh !== refresh) return Boolean(state.access);
    if (!res.ok) {
      if (res.status === 401) state.logout();
      return false;
    }
    state.setAuth(await res.json());
    return true;
  }).catch(() => false).finally(() => { renovacaoEmCurso = null; });
  return renovacaoEmCurso;
}

export async function encerrarSessao() {
  await renovacaoEmCurso;
  return comTravaDeSessao(async () => {
    try {
      state.sincronizarSessao();
      if (state.refresh) {
        await fetch(`${BASE}/auth/logout`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: state.refresh }),
          signal: AbortSignal.timeout(5000),
          keepalive: true,
        });
      }
    } catch {
      // A saída local também precisa funcionar offline.
    } finally {
      state.logout();
    }
  });
}

export const api = {
  base: BASE,

  async request(method, path, { body, query, renovar = true } = {}) {
    let url = this.base + path;
    if (query) {
      const qs = new URLSearchParams();
      for (const [k, v] of Object.entries(query)) {
        if (v !== undefined && v !== null && v !== "") qs.set(k, v);
      }
      if ([...qs].length) url += "?" + qs.toString();
    }

    const headers = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const acesso = state.access;
    if (acesso) headers["Authorization"] = "Bearer " + acesso;
    incluirPlanta(headers);

    // Prazo para a resposta.
    //
    // ## Por que existe
    //
    // Uma requisição que nunca responde deixava a tela **carregando para
    // sempre** — o esqueleto animado ficava na tela e não havia erro, nem
    // pista. Acontece quando o servidor está sem conexão livre no pool, ou
    // preso numa consulta lenta: o `fetch` fica pendurado e o `catch` do
    // chamador nunca roda.
    //
    // Com prazo, o mesmo problema vira uma mensagem: "o servidor não
    // respondeu em 30s". É diagnóstico, e não silêncio.
    //
    // 30s é folgado de propósito: relatório grande e exportação de PDF
    // passam perto disso, e um prazo curto quebraria operação legítima.
    const PRAZO_MS = 30000;
    const controle = new AbortController();
    const relogio = setTimeout(() => controle.abort(), PRAZO_MS);

    let res;
    try {
      res = await fetch(url, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: controle.signal,
      });
    } catch (e) {
      // Abortado pelo prazo é diferente de rede caindo: o servidor pode ter
      // recebido o pedido. Não enfileira para reenvio.
      if (e && e.name === "AbortError") {
        throw new ApiError(
          0,
          `O servidor não respondeu em ${PRAZO_MS / 1000}s. `
          + "Pode estar processando algo pesado, ou sem conexão livre no banco. "
          + "Tente de novo em instantes.",
        );
      }
      // Offline: fila a escrita para reenvio posterior.
      if (method !== "GET" && !path.startsWith("/auth/") && !path.startsWith("/mfa/")) {
        await enqueue(method, path, body);
      }
      throw new ApiError(0, "Sem conexão com o servidor");
    } finally {
      clearTimeout(relogio);
    }

    // 401 → tenta refresh uma vez e repete a requisição.
    if (renovar && res.status === 401 && state.refresh && (!path.startsWith("/auth/") || path === "/auth/me")) {
      if (await refreshTokens(acesso)) return this.request(method, path, { body, query, renovar: false });
    }

    let data = null;
    const ct = res.headers.get("content-type") || "";
    if (res.status !== 204) {
      data = ct.includes("json") ? await res.json() : await res.text();
    }
    if (!res.ok) {
      // `detail` pode ser string (HTTPException) ou lista de erros (validação 422).
      const detalhe = data && typeof data === "object" && "detail" in data ? data.detail : data;
      const erro = new ApiError(res.status, mensagemErro(detalhe, res.status));
      erro.detail = detalhe;
      erro.campos = camposComErro(detalhe);

      // 503 = modo manutenção. Mostra a tela do administrador em vez de um
      // erro genérico: a pessoa precisa entender que não é problema dela, e
      // a mensagem é escrita por quem ligou o modo.
      if (res.status === 503) {
        mostrarManutencao(typeof detalhe === "string" ? detalhe : null);
      }

      throw erro;
    }
    return data;
  },

  get(path, query) { return this.request("GET", path, { query }); },
  post(path, body) { return this.request("POST", path, { body }); },
  put(path, body) { return this.request("PUT", path, { body }); },
  patch(path, body) { return this.request("PATCH", path, { body }); },
  del(path) { return this.request("DELETE", path); },

  /**
   * Envia FormData (upload de arquivo).
   *
   * NÃO define `Content-Type`: o navegador precisa gerar o `boundary` do
   * multipart sozinho — definindo à mão, o servidor não consegue separar os
   * campos e o upload falha.
   */
  async form(method, path, dados, renovar = true) {
    const headers = {};
    const acesso = state.access;
    if (acesso) headers["Authorization"] = "Bearer " + acesso;
    incluirPlanta(headers);

    let res;
    try {
      res = await fetch(this.base + path, { method, headers, body: dados });
    } catch {
      throw new ApiError(0, "Sem conexão com o servidor");
    }

    if (renovar && res.status === 401 && state.refresh && !path.startsWith("/auth/")) {
      if (await refreshTokens(acesso)) return this.form(method, path, dados, false);
    }

    let data = null;
    const ct = res.headers.get("content-type") || "";
    if (res.status !== 204) data = ct.includes("json") ? await res.json() : await res.text();
    if (!res.ok) {
      const detalhe = data && typeof data === "object" && "detail" in data ? data.detail : data;
      const erro = new ApiError(res.status, mensagemErro(detalhe, res.status));
      erro.detail = detalhe;
      erro.campos = camposComErro(detalhe);
      throw erro;
    }
    return data;
  },

  postForm(path, dados) { return this.form("POST", path, dados); },
  patchForm(path, dados) { return this.form("PATCH", path, dados); },

  /**
   * Baixa um arquivo protegido e devolve uma URL temporária (blob).
   *
   * Necessário para imagens/prints: um `<img src="/api/...">` ou
   * `window.open("/api/...")` NÃO envia o cabeçalho `Authorization`, então o
   * servidor responde 401 e o arquivo nunca aparece. Aqui a busca é feita com
   * o token e o conteúdo vira uma URL local do navegador.
   *
   * Quem chama deve liberar depois com `URL.revokeObjectURL`.
   */
  async blob(path, renovar = true) {
    const headers = {};
    const acesso = state.access;
    if (acesso) headers["Authorization"] = "Bearer " + acesso;
    incluirPlanta(headers);

    let res;
    try {
      res = await fetch(this.base + path, { headers });
    } catch {
      throw new ApiError(0, "Sem conexão com o servidor");
    }
    if (renovar && res.status === 401 && state.refresh && !path.startsWith("/auth/")) {
      if (await refreshTokens(acesso)) return this.blob(path, false);
    }
    if (!res.ok) {
      let detalhe = null;
      try { detalhe = (await res.json()).detail; } catch { /* resposta sem JSON */ }
      throw new ApiError(res.status, mensagemErro(detalhe, res.status));
    }
    return URL.createObjectURL(await res.blob());
  },
};

/** Reenvia operações pendentes da fila offline (chamado no boot quando online). */
export async function replayOfflineQueue() {
  const ops = await pending();
  for (const op of ops) {
    if (op.path.startsWith("/auth/") || op.path.startsWith("/mfa/")) {
      await dequeue(op.id);
      continue;
    }
    try {
      await api.request(op.method, op.path, { body: op.body });
      await dequeue(op.id);
    } catch (e) {
      if (e.status === 401) { await dequeue(op.id); break; }
      break; // ainda offline — para e tenta no próximo boot
    }
  }
}
