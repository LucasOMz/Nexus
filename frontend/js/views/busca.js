/**
 * Busca global (Ctrl+K).
 *
 * Um atalho que acha ativo, produto, usuário e planta sem passar pelo menu.
 * O ganho está em não precisar saber ONDE a coisa mora: quem procura o
 * patrimônio "TI-0042" não deveria escolher entre seis telas antes.
 *
 * @module views/busca
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { el, icon, mostrarErro } from "../ui.js";

// Espera o usuário parar de digitar antes de consultar. Sem isto, "notebook"
// dispararia 8 requisições — uma por tecla.
const ESPERA_MS = 220;

let aberto = null;

/** O atalho está disponível? Usado pelo handler global de teclado. */
export function buscaAberta() {
  return aberto !== null;
}

export function fecharBusca() {
  if (!aberto) return;
  aberto.overlay.remove();
  document.removeEventListener("keydown", aberto.teclas, true);
  aberto = null;
}

/**
 * Abre a janela de busca.
 *
 * Não usa o `dialog()` padrão de propósito: a busca precisa de um campo que
 * recebe foco imediato, navegação por setas e Enter — um formulário próprio,
 * não um aviso com botões.
 */
export function abrirBusca() {
  if (aberto) { aberto.campo.focus(); return; }

  const campo = el("input", {
    class: "busca-campo",
    type: "search",
    placeholder: "Buscar ativo, produto, usuário ou planta…",
    autocomplete: "off",
    spellcheck: "false",
  });
  const lista = el("div", { class: "busca-lista" });
  const rodape = el("div", { class: "busca-rodape" });

  const caixa = el("div", { class: "busca-caixa card elevated" },
    el("div", { class: "busca-topo" },
      el("span", { class: "busca-lupa", html: icon("search", 20) }),
      campo,
      el("kbd", { class: "busca-esc" }, "Esc"),
    ),
    lista,
    rodape,
  );
  const overlay = el("div", { class: "busca-overlay", onclick: (e) => {
    if (e.target === overlay) fecharBusca();
  } }, caixa);

  // Índice do item destacado. Navegar por setas é o que torna a busca rápida:
  // digitar e apertar Enter, sem tirar a mão do teclado.
  let destacado = 0;
  let itens = [];
  let timer = null;
  // Cada consulta leva um número; só a última pode pintar o resultado. Sem
  // isto, uma resposta lenta de "not" chegaria DEPOIS de "notebook" e
  // sobrescreveria a lista certa.
  let geracao = 0;

  function pintar(dados) {
    lista.innerHTML = "";
    itens = [];
    destacado = 0;

    if (!dados) { rodape.textContent = "Digite ao menos 2 letras."; return; }
    if (!dados.grupos?.length) {
      lista.append(el("p", { class: "busca-vazio muted" }, "Nada encontrado."));
      rodape.textContent = "";
      return;
    }

    for (const g of dados.grupos) {
      lista.append(el("p", { class: "busca-grupo" }, g.nome));
      for (const it of g.itens) {
        const i = itens.length;
        const linha = el("button", {
          type: "button",
          class: "busca-item",
          onclick: () => ir(it.rota),
          onmouseenter: () => { destacado = i; marcar(); },
        },
          el("span", { class: "busca-item-titulo" }, it.titulo),
          it.detalhe ? el("span", { class: "busca-item-detalhe" }, it.detalhe) : null,
        );
        itens.push({ el: linha, rota: it.rota });
        lista.append(linha);
      }
    }
    marcar();
    rodape.textContent = `${dados.total} resultado(s) · ↑↓ para navegar · Enter para abrir`;
  }

  function marcar() {
    itens.forEach((it, i) => it.el.classList.toggle("destacado", i === destacado));
    itens[destacado]?.el.scrollIntoView({ block: "nearest" });
  }

  function ir(rota) {
    fecharBusca();
    // O roteador escuta `hashchange`: trocar o hash navega sem recarregar.
    location.hash = rota.replace(/^#/, "");
  }

  async function consultar() {
    const termo = campo.value.trim();
    if (termo.length < 2) { pintar(null); return; }

    const meu = ++geracao;
    try {
      const dados = await api.get(`/busca?q=${encodeURIComponent(termo)}`);
      if (meu !== geracao) return;   // chegou atrasada: descarta
      pintar(dados);
    } catch (e) {
      if (meu !== geracao) return;
      lista.innerHTML = "";
      lista.append(el("p", { class: "busca-vazio text-error" }, e.message));
    }
  }

  campo.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(consultar, ESPERA_MS);
  });

  function teclas(e) {
    if (e.key === "Escape") { e.preventDefault(); fecharBusca(); return; }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!itens.length) return;
      const passo = e.key === "ArrowDown" ? 1 : -1;
      destacado = (destacado + passo + itens.length) % itens.length;
      marcar();
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      if (itens[destacado]) ir(itens[destacado].rota);
    }
  }

  document.addEventListener("keydown", teclas, true);
  document.body.append(overlay);
  aberto = { overlay, campo, teclas };

  // Foco imediato: quem apertou Ctrl+K quer digitar, não clicar.
  campo.focus();
  pintar(null);
}

/**
 * Liga o atalho global.
 *
 * Ctrl+K (e Cmd+K no Mac). O `preventDefault` é essencial: sem ele, o
 * Ctrl+K do navegador — que foca a barra de endereços no Firefox — vence, e
 * a busca nunca abre.
 */
export function ligarAtalhoDeBusca() {
  document.addEventListener("keydown", (e) => {
    const cmd = e.ctrlKey || e.metaKey;
    if (cmd && e.key.toLowerCase() === "k") {
      e.preventDefault();
      if (!state.access) return;      // só faz sentido logado
      abrirBusca();
    }
  });
}
