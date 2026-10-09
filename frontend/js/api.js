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

async function refreshTokens() {
  if (!state.refresh) return false;
  const res = await fetch(`${BASE}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: state.refresh }),
  });
  if (!res.ok) { state.logout(); return false; }
  state.setAuth(await res.json());
  return true;
}

export const api = {
  base: BASE,

  async request(method, path, { body, query } = {}) {
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
    if (state.access) headers["Authorization"] = "Bearer " + state.access;

    let res;
    try {
      res = await fetch(url, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
    } catch {
      // Offline: fila a escrita para reenvio posterior.
      if (method !== "GET") await enqueue(method, path, body);
      throw new ApiError(0, "Sem conexão com o servidor");
    }

    // 401 → tenta refresh uma vez e repete a requisição.
    if (res.status === 401 && state.refresh && !path.includes("/auth/")) {
      if (await refreshTokens()) return this.request(method, path, { body, query });
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
  async form(method, path, dados) {
    const headers = {};
    if (state.access) headers["Authorization"] = "Bearer " + state.access;

    let res;
    try {
      res = await fetch(this.base + path, { method, headers, body: dados });
    } catch {
      throw new ApiError(0, "Sem conexão com o servidor");
    }

    if (res.status === 401 && state.refresh && !path.includes("/auth/")) {
      if (await refreshTokens()) return this.form(method, path, dados);
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
  async blob(path) {
    const headers = {};
    if (state.access) headers["Authorization"] = "Bearer " + state.access;

    let res;
    try {
      res = await fetch(this.base + path, { headers });
    } catch {
      throw new ApiError(0, "Sem conexão com o servidor");
    }
    if (res.status === 401 && state.refresh && !path.includes("/auth/")) {
      if (await refreshTokens()) return this.blob(path);
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
    try {
      await api.request(op.method, op.path, { body: op.body });
      await dequeue(op.id);
    } catch (e) {
      if (e.status === 401) { await dequeue(op.id); break; }
      break; // ainda offline — para e tenta no próximo boot
    }
  }
}
