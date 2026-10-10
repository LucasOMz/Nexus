/**
 * Seletor de ativo com BUSCA.
 *
 * Por que não um `<select>`: o sistema tem milhares de ativos, e uma lista
 * suspensa só carrega os primeiros (o formulário de manutenção trazia 200 —
 * o resto era inalcançável). Aqui a pessoa digita parte do patrimônio, do
 * modelo ou do número de série e a busca acontece no servidor.
 *
 * @module seletor_ativo
 */
import { api } from "./api.js";
import { state } from "./state.js";
import { el, icon } from "./ui.js";

/**
 * Linha de detalhe de um ativo na busca.
 *
 * ## Por que o hostname aparece destacado
 *
 * O hostname vive na ficha técnica, não no ativo — então quem digitava "NTAT"
 * via `TP98000011212 / Latitude 3420 · Dell · TAT` e **nada** indicava o
 * motivo de aquele item ter aparecido. O resultado estava certo e a pessoa
 * duvidava dele.
 *
 * Quando o termo digitado está no hostname, ele vem **antes** e em destaque:
 * é a resposta à pergunta "por que este resultado?".
 *
 * Exportada para os outros seletores de ativo usarem a MESMA regra — foi o
 * pedido de ser padrão, e não um caso isolado.
 */
export function subtituloDoAtivo(a, termo = "") {
  const alvo = (termo || "").trim().toLowerCase();
  const host = (a.hostname || "").trim();
  const casouNoHost = Boolean(alvo && host && host.toLowerCase().includes(alvo));

  const partes = [];
  if (host) {
    partes.push(el("span", {
      class: casouNoHost ? "seletor-host casou" : "seletor-host",
    }, host));
  }
  if (a.modelo) partes.push(el("span", {}, a.modelo));
  if (a.marca) partes.push(el("span", {}, a.marca));
  if (a.planta_sigla) partes.push(el("span", {}, a.planta_sigla));

  if (!partes.length) return el("span", { class: "seletor-item-sub" }, "sem detalhes");

  // Junta com " · " sem transformar os separadores em texto solto.
  const conteudo = [];
  partes.forEach((p, i) => {
    if (i) conteudo.push(document.createTextNode(" · "));
    conteudo.push(p);
  });
  return el("span", { class: "seletor-item-sub" }, ...conteudo);
}

const ESPERA_MS = 300; // aguarda a digitação parar antes de consultar

/**
 * Monta o seletor.
 *
 * @param {object} [opcoes]
 * @param {object|null} [opcoes.ativoFixo] quando o ativo já é conhecido, o
 *   seletor nem aparece (caso da leitura de QR Code).
 * @returns {{elemento: HTMLElement, id: () => number|null, nome: () => string}}
 */
export function seletorDeAtivo({ ativoFixo = null } = {}) {
  let escolhido = ativoFixo || null;
  let timer = null;
  let ultimaBusca = "";

  const campo = el("input", {
    class: "search-input",
    placeholder: "Buscar por patrimônio, modelo ou nº de série…",
    autocomplete: "off",
  });

  const resultados = el("div", { class: "seletor-resultados hidden" });
  const caixa = el("div", { class: "seletor-ativo" }, campo, resultados);

  // --- Ativo já escolhido: mostra um cartão em vez do campo ---------------
  const cartao = el("div", { class: "seletor-escolhido hidden" });
  function mostrarEscolhido() {
    cartao.innerHTML = "";
    if (!escolhido) {
      cartao.classList.add("hidden");
      caixa.classList.remove("hidden");
      return;
    }
    cartao.classList.remove("hidden");
    caixa.classList.add("hidden");
    cartao.append(
      el("div", { class: "seletor-escolhido-info" },
        el("strong", {}, escolhido.patrimonio),
        el("span", { class: "muted" },
          `${escolhido.modelo || "sem modelo"}${escolhido.planta_sigla ? ` · ${escolhido.planta_sigla}` : ""}`),
      ),
      el("button", {
        type: "button", class: "iconbtn", title: "Trocar de ativo",
        onclick: () => { escolhido = null; mostrarEscolhido(); campo.value = ""; campo.focus(); },
        html: icon("edit", 18),
      }),
    );
  }

  function fecharResultados() {
    resultados.classList.add("hidden");
    resultados.innerHTML = "";
  }

  function escolher(ativo) {
    escolhido = ativo;
    fecharResultados();
    mostrarEscolhido();
  }

  function desenharResultados(itens, termo) {
    resultados.innerHTML = "";
    if (!itens.length) {
      resultados.append(el("div", { class: "seletor-vazio" },
        `Nenhum ativo encontrado para “${termo}”.`));
    } else {
      itens.forEach((a) => {
        const linha = el("button", { type: "button", class: "seletor-item" },
          el("span", { class: "seletor-item-nome" }, a.patrimonio),
          subtituloDoAtivo(a, termo),
        );
        linha.addEventListener("click", () => escolher(a));
        resultados.append(linha);
      });
    }
    resultados.classList.remove("hidden");
  }

  async function buscar(termo) {
    const alvo = termo.trim();
    ultimaBusca = alvo;
    if (alvo.length < 2) { fecharResultados(); return; }
    try {
      const dados = await api.get("/ativos", { dominio: state.dominio, search: alvo, size: 20 });
      // Se o texto mudou enquanto a resposta voltava, ignora o resultado antigo.
      if (ultimaBusca !== alvo) return;
      desenharResultados(dados.items || [], alvo);
    } catch {
      fecharResultados();
    }
  }

  campo.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => buscar(campo.value), ESPERA_MS);
  });

  // Enter pega o primeiro resultado — agiliza quem já sabe o patrimônio.
  campo.addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter") return;
    ev.preventDefault();
    const primeiro = resultados.querySelector(".seletor-item");
    if (primeiro) primeiro.click();
  });

  document.addEventListener("click", (ev) => {
    if (!caixa.contains(ev.target)) fecharResultados();
  });

  const elemento = el("div", {}, cartao, caixa);
  mostrarEscolhido();

  return {
    elemento,
    id: () => (escolhido ? escolhido.id : null),
    nome: () => (escolhido ? escolhido.patrimonio : ""),
  };
}
