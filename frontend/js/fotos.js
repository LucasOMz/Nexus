/** Exibe fotos privadas com o download autenticado do cliente da API. */
import { api } from "./api.js";
import { el } from "./ui.js";

const aguardando = new Map();
let visibilidade;
let remocoes;

async function carregar(img, id) {
  let url;
  try {
    url = await api.blob(`/admin/fotos/${encodeURIComponent(id)}/arquivo`);
    if (!img.isConnected) {
      URL.revokeObjectURL(url);
      return;
    }
    const liberar = () => {
      img.removeEventListener("load", liberar);
      img.removeEventListener("error", liberar);
      URL.revokeObjectURL(url);
    };
    img.addEventListener("load", liberar);
    img.addEventListener("error", liberar);
    img.src = url;
  } catch {
    if (url) URL.revokeObjectURL(url);
    // A legenda da foto continua disponível se o download falhar.
  }
}

function pararDeObservar(img) {
  visibilidade.unobserve(img);
  aguardando.delete(img);
  if (!aguardando.size) remocoes.disconnect();
}

function observarFoto(img, id) {
  visibilidade ??= new IntersectionObserver(entradas => {
    for (const { target, isIntersecting } of entradas) {
      if (!isIntersecting || !aguardando.has(target)) continue;
      const fotoId = aguardando.get(target);
      pararDeObservar(target);
      if (target.isConnected) carregar(target, fotoId);
    }
  }, { rootMargin: "160px" });
  remocoes ??= new MutationObserver(mudancas => {
    if (!mudancas.some(mudanca => mudanca.removedNodes.length)) return;
    for (const pendente of aguardando.keys()) {
      if (!pendente.isConnected) pararDeObservar(pendente);
    }
  });
  if (!aguardando.size) remocoes.observe(document.body, { childList: true, subtree: true });
  aguardando.set(img, id);
  visibilidade.observe(img);
}

export function fotoProtegida(id, { loading, ...atributos } = {}) {
  const img = el("img", { decoding: "async", ...atributos });
  queueMicrotask(() => {
    if (!img.isConnected) return;
    if (loading === "lazy" && typeof IntersectionObserver === "function") observarFoto(img, id);
    else carregar(img, id);
  });
  return img;
}
