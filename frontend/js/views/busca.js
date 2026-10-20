/**
 * Busca global (Ctrl+K) — acha dados **e** telas.
 *
 * ## Duas buscas, uma janela
 *
 * ```
 * "contratos"  →  Ir para: Contratos            ← navega, sem ir ao servidor
 * "TI-0042"    →  Ativos: Notebook · TI-0042    ← consulta a API
 * ```
 *
 * A primeira é **local**: as telas do sistema já estão no cliente, e procurar
 * por elas no servidor gastaria uma requisição por tecla para responder algo
 * que o navegador já sabe. Também funciona **offline** e **antes** do login do
 * usuário na API — que é quando alguém mais precisa se orientar.
 *
 * ## Por que "Ir para" vem primeiro
 *
 * Quem digita "contratos" quer **abrir a tela**, não ver os contratos
 * cadastrados. Inverter a ordem faria o Enter abrir um contrato quando a
 * intenção era abrir a lista.
 *
 * ## Com o campo vazio, a janela lista as telas
 *
 * Vira um menu de atalhos: Ctrl+K e Enter. É o que um `command palette` faz, e
 * custa nada — a lista já está em memória.
 *
 * @module views/busca
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { el, icon } from "../ui.js";

// Espera o usuário parar de digitar antes de consultar. Sem isto, "notebook"
// dispararia 8 requisições — uma por tecla.
const ESPERA_MS = 220;

// Duas letras é o mínimo para a busca na API. As telas, por serem locais,
// procuram com uma letra — mas manter o mesmo mínimo deixa o comportamento
// previsível.
const MINIMO = 2;

let aberto = null;

/**
 * As telas do sistema, para o "Ir para".
 *
 * Preenchido por `ligarAtalhoDeBusca(MODULOS)`. Vem do `app.js` em vez de uma
 * lista própria: duplicar aqui faria a busca oferecer telas que não existem
 * mais no dia em que alguém renomeasse ou removesse uma.
 */
let TELAS = {};

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
 * Baixa a caixa e tira os acentos, para comparar.
 *
 * "manutencoes" precisa achar "Manutenções" — num sistema em português, exigir
 * o acento certo seria exigir que a pessoa adivinhe a grafia do rótulo.
 */
function normalizar(texto) {
  return String(texto || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

/**
 * As telas que casam com o termo.
 *
 * Vazio devolve **todas** as permitidas — é o menu de atalhos. Com termo,
 * filtra por rótulo, id do módulo, ou o que o rótulo significa.
 *
 * Respeita `state.podeModulo`: oferecer uma tela que o usuário não pode abrir
 * seria um atalho para o 403.
 */
function telasQueCasam(termo) {
  const alvo = normalizar(termo);
  const saida = [];

  for (const [id, meta] of Object.entries(TELAS)) {
    if (!meta?.rotulo) continue;
    try {
      if (!state.podeModulo(id)) continue;
    } catch {
      // Sem estado de permissão (ex.: durante o boot) não bloqueia.
    }

    if (!alvo) {
      saida.push({ id, rotulo: meta.rotulo, rota: id });
      continue;
    }

    // Casa pelo rótulo, pelo id, ou por palavras soltas do rótulo —
    // "monitor" acha "Monitor de impressoras", e "impressoras" também.
    const rotulo = normalizar(meta.rotulo);
    const bate = rotulo.includes(alvo)
      || normalizar(id).includes(alvo)
      || rotulo.split(/\s+/).some((p) => p.startsWith(alvo));

    if (bate) saida.push({ id, rotulo: meta.rotulo, rota: id });
  }

  // Quem começa com o termo vem antes: "con" → Contratos antes de
  // "Certificado de descarte".
  saida.sort((a, b) => {
    const pa = normalizar(a.rotulo).startsWith(alvo) ? 0 : 1;
    const pb = normalizar(b.rotulo).startsWith(alvo) ? 0 : 1;
    return pa - pb || a.rotulo.localeCompare(b.rotulo, "pt-BR");
  });

  return saida;
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
    placeholder: "Buscar ou ir para uma tela… (ex.: contratos)",
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

  /**
   * Desenha as telas e os dados.
   *
   * `dados` pode ser `null` — e mesmo assim as telas aparecem. É o que faz a
   * busca servir sem rede e antes da resposta da API.
   */
  function pintar(dados, termo) {
    lista.innerHTML = "";
    itens = [];
    destacado = 0;

    const telas = telasQueCasam(termo);
    const grupos = [];

    if (telas.length) {
      grupos.push({
        nome: termo ? "Ir para" : "Telas",
        itens: telas.slice(0, termo ? 8 : 30).map((t) => ({
          titulo: t.rotulo,
          detalhe: "tela",
          rota: t.rota,
        })),
      });
    }

    for (const g of dados?.grupos || []) grupos.push(g);

    if (!grupos.length) {
      const msg = !termo
        ? "Digite para buscar, ou escolha uma tela."
        : "Nada encontrado.";
      lista.append(el("p", { class: "busca-vazio muted" }, msg));
      rodape.textContent = "";
      return;
    }

    for (const g of grupos) {
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

    const nTelas = telas.length;
    const nDados = dados?.total ?? 0;
    const partes = [];
    if (nTelas) partes.push(`${nTelas} tela(s)`);
    if (nDados) partes.push(`${nDados} resultado(s)`);
    rodape.textContent = `${partes.join(" · ") || "—"} · ↑↓ navegar · Enter abrir`;
  }

  function marcar() {
    itens.forEach((it, i) => it.el.classList.toggle("destacado", i === destacado));
    itens[destacado]?.el.scrollIntoView({ block: "nearest" });
  }

  function ir(rota) {
    fecharBusca();
    // O roteador escuta `hashchange`: trocar o hash navega sem recarregar.
    location.hash = String(rota).replace(/^#/, "");
  }

  async function consultar() {
    const termo = campo.value.trim();

    // Campo vazio: só as telas, sem tocar na rede.
    if (!termo) { pintar(null, ""); return; }

    // Com uma letra, as telas já respondem — a API ainda não.
    if (termo.length < MINIMO) { pintar(null, termo); return; }

    const meu = ++geracao;
    try {
      const dados = await api.get(`/busca?q=${encodeURIComponent(termo)}`);
      if (meu !== geracao) return;   // chegou atrasada: descarta
      pintar(dados, termo);
    } catch (e) {
      if (meu !== geracao) return;
      // A API falhou, mas as telas são locais: continua útil.
      pintar(null, termo);
      if (!telasQueCasam(termo).length) {
        lista.innerHTML = "";
        lista.append(el("p", { class: "busca-vazio text-error" }, e.message));
      }
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
  pintar(null, "");
}

/**
 * Liga o atalho global.
 *
 * `modulos` é o `MODULOS` do `app.js` — recebido por parâmetro, e não
 * importado, para não criar dependência circular (o `app.js` importa este
 * arquivo para ligar o atalho).
 *
 * Ctrl+K (e Cmd+K no Mac). O `preventDefault` é essencial: sem ele, o
 * Ctrl+K do navegador — que foca a barra de endereços no Firefox — vence, e
 * a busca nunca abre.
 */
export function ligarAtalhoDeBusca(modulos = null) {
  if (modulos) TELAS = modulos;

  document.addEventListener("keydown", (e) => {
    const cmd = e.ctrlKey || e.metaKey;
    if (cmd && e.key.toLowerCase() === "k") {
      e.preventDefault();
      if (!state.access) return;      // só faz sentido logado
      abrirBusca();
    }
  });
}
