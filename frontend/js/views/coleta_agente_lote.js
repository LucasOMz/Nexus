import { api } from "../api.js";
import { el, fmtDate, icon } from "../ui.js";

const rota = "/acoes-agente/lotes";
const totalPt = new Intl.NumberFormat("pt-BR");
const MOTIVOS = {
  falhou: "O agente não conseguiu enviar o inventário.",
  cancelada: "Vínculo ou acesso alterado.",
  expirada: "Prazo esgotado sem retorno.",
};

export function abrirColetaAgenteLote(origem) {
  const janela = el("dialog", { class: "dialog coleta-agente-lote", "aria-labelledby": "coleta-lote-titulo" });
  const fechar = el("button", { class: "iconbtn", type: "button", "aria-label": "Fechar",
    autofocus: true, onclick: () => janela.close(), html: icon("close", 20) });
  const escopo = el("p", { class: "muted" });
  const iniciar = el("button", { class: "btn filled", type: "button", disabled: true, onclick: solicitar }, "Iniciar coleta");
  const mensagem = el("p", { class: "muted", role: "status", hidden: true });
  const seletor = el("select", { class: "search-input", "aria-label": "Coletas recentes", onchange: () => selecionar() });
  const selecao = el("label", { class: "coleta-lote-selecao", hidden: true }, "Coletas recentes", seletor);
  const progresso = el("div", { class: "coleta-lote-progresso" });
  let contexto;
  let timer;
  let revisao = 0;
  let paginaFalhas = 0;
  let idSelecionado = null;
  let enviando = false;
  let ultimoDesenho;
  let selecionadoEmAndamento = false;

  janela.append(
    el("header", { class: "row between coleta-lote-topo" },
      el("h2", { id: "coleta-lote-titulo" }, "Coleta em lote"), fechar),
    escopo, iniciar, mensagem, selecao, progresso,
  );
  janela.addEventListener("close", () => {
    clearTimeout(timer);
    janela.remove();
    if (origem?.isConnected) origem.focus();
  });
  document.body.append(janela);
  janela.showModal();
  refrescarLotes();

  function avisar(texto) {
    mensagem.textContent = texto;
    mensagem.hidden = !texto;
  }

  async function refrescarLotes(preferido = null) {
    try {
      contexto = await api.get(rota);
      if (!janela.open) return;
      const abrangencia = contexto.planta_id === null ? "Todas as plantas" : "Planta ativa";
      escopo.textContent = `${abrangencia} · Computadores vinculados ao agente · Até ${contexto.coletas_por_minuto} por minuto`;
      selecao.hidden = !contexto.lotes.length;
      seletor.replaceChildren(...contexto.lotes.map(lote => el("option", { value: lote.id },
        `#${lote.id} · ${fmtDate(lote.solicitada_em, true)} · ${lote.solicitante}`)));
      seletor.value = String(preferido ?? contexto.lotes[0]?.id ?? "");
      await selecionar();
      atualizarIniciar();
    } catch (e) {
      if (janela.open) avisar(e.message);
    }
  }

  function atualizarIniciar() {
    iniciar.disabled = !contexto || enviando;
  }

  async function solicitar() {
    if (enviando || !contexto) return;
    enviando = true;
    atualizarIniciar();
    avisar("");
    try {
      const lote = await api.request("POST", rota, { enfileirar: false });
      await refrescarLotes(lote.id);
    } catch (e) {
      if (janela.open) avisar(e.message);
    } finally {
      enviando = false;
      atualizarIniciar();
    }
  }

  function selecionar() {
    paginaFalhas = 0;
    ultimoDesenho = null;
    selecionadoEmAndamento = false;
    idSelecionado = seletor.value;
    progresso.replaceChildren();
    return carregarProgresso();
  }

  async function carregarProgresso() {
    clearTimeout(timer);
    const atual = ++revisao;
    if (!idSelecionado || !janela.open) return;
    let continuar = true;
    try {
      const lote = await api.get(`${rota}/${idSelecionado}`, { falhas_offset: paginaFalhas });
      if (atual !== revisao || !janela.open) return;
      continuar = lote.aguardando + lote.em_execucao > 0;
      if (selecionadoEmAndamento && !continuar) avisar("");
      selecionadoEmAndamento = continuar;
      const desenho = JSON.stringify([paginaFalhas, lote]);
      if (ultimoDesenho !== desenho) {
        desenharProgresso(lote);
        ultimoDesenho = desenho;
      }
    } catch (e) {
      if (atual === revisao && janela.open) avisar(e.message);
    } finally {
      if (atual === revisao && janela.open && continuar) timer = setTimeout(carregarProgresso, 8000);
    }
  }

  function desenharProgresso(lote) {
    const finalizadas = lote.concluidas + lote.total_falhas;
    const excluidos = [
      lote.sem_agente ? `${totalPt.format(lote.sem_agente)} sem agente` : "",
      lote.ja_solicitados ? `${totalPt.format(lote.ja_solicitados)} com coleta já solicitada` : "",
    ].filter(Boolean).join(" · ");
    const metricas = [["Na fila", lote.aguardando], ["Em execução", lote.em_execucao],
      ["Concluídas", lote.concluidas], ["Falhas", lote.total_falhas]];
    progresso.replaceChildren(
      el("p", { class: "coleta-lote-contagem" }, `${totalPt.format(finalizadas)} de ${totalPt.format(lote.total)} finalizadas`),
      el("progress", { value: finalizadas, max: lote.total, "aria-label": "Progresso da coleta em lote" }),
      el("dl", { class: "coleta-lote-metricas" }, ...metricas.map(([rotulo, valor]) => el("div", {},
        el("dt", { class: "muted" }, rotulo), el("dd", {}, totalPt.format(valor))))),
      excluidos ? el("p", { class: "muted" }, excluidos) : null,
      lote.total_falhas ? el("section", { class: "coleta-lote-falhas", "aria-label": "Falhas da coleta" },
        el("h3", {}, "Falhas"),
        el("ul", {}, ...lote.falhas.map(f => el("li", {},
          el("strong", {}, f.ativo), el("span", { class: "muted" }, MOTIVOS[f.estado])))),
        el("div", { class: "row wrap coleta-lote-paginas" },
          paginaFalhas > 0 ? el("button", { class: "btn text small", type: "button",
            onclick: () => mudarPagina(Math.max(0, paginaFalhas - 25)) }, "Anteriores") : null,
          lote.proximo_offset != null ? el("button", { class: "btn text small", type: "button",
            onclick: () => mudarPagina(lote.proximo_offset) }, "Próximas falhas") : null),
      ) : null,
    );
  }

  function mudarPagina(offset) {
    paginaFalhas = offset;
    carregarProgresso();
  }
}
