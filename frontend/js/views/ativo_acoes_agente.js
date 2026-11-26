import { api } from "../api.js";
import { el, fmtDate, icon } from "../ui.js";

const ACOES = [
  ["coletar", "Solicitar nova coleta", "Nova coleta", "refresh"],
  ["testar_comunicacao", "Testar comunicação com o Nexus", "Testar conexão", "integracoes"],
  ["status_servico", "Consultar status do serviço", "Status do serviço", "server"],
];
const ESTADOS = {
  aguardando: "Aguardando agente", entregue: "Aguardando resultado", concluida: "Concluída",
  falhou: "Falhou", expirada: "Expirada", cancelada: "Cancelada",
};
const TONS = { aguardando: "aviso", entregue: "aviso", concluida: "ok", falhou: "erro" };
const RESULTADOS = {
  coleta_enviada: "Inventário enviado ao Nexus.",
  falha_coleta: "O agente não conseguiu enviar o inventário.",
  comunicacao_ok: "O agente respondeu ao Nexus.",
  servico_em_execucao: "O serviço NexusAgente estava em execução.",
  falha_status: "O agente não conseguiu confirmar o status do serviço.",
  acesso_ou_vinculo_alterado: "A permissão ou o vínculo mudou antes da entrega.",
};
const pendente = item => ["aguardando", "entregue"].includes(item.estado);

export function painelAcoesAgente(ativoId) {
  const rota = `/ativos/${ativoId}/acoes-agente`;
  const painel = el("section", { class: "card ativo-acoes-agente", hidden: true, "aria-label": "Ações remotas" });
  const resumoFila = el("span", { class: "chip aviso", role: "status", hidden: true });
  const contato = el("p", { class: "muted" });
  const recado = el("p", { class: "muted", role: "status", hidden: true });
  const lista = el("ul", { class: "ativo-acoes-historico" });
  const vazio = el("p", { class: "muted" }, "Nenhuma solicitação registrada.");
  let itens = [];
  let anteriores = [];
  let cursor = null;
  let solicitando = false;
  let timer;
  let revisao = 0;

  const botoes = ACOES.map(([tipo, rotulo, curto, icone]) => [tipo, el("button", {
    class: "btn text small", type: "button", onclick: () => solicitar(tipo), title: rotulo,
    "aria-label": rotulo, html: icon(icone, 16) + " " + curto,
  })]);
  const atualizar = el("button", { class: "iconbtn", type: "button", title: "Atualizar histórico",
    "aria-label": "Atualizar histórico", onclick: carregar, html: icon("refresh", 19) });
  const mais = el("button", { class: "btn text", type: "button", hidden: true, onclick: carregarAnteriores },
    "Ver ações anteriores");
  const historico = el("details", { class: "ativo-acoes-detalhes" },
    el("summary", {}, "Histórico", el("span", { class: "ativo-acoes-seta", html: icon("chevron", 16) })),
    el("div", { class: "row between ativo-acoes-contato" }, contato, atualizar),
    vazio, lista, mais,
  );
  painel.append(
    el("div", { class: "row between wrap" }, el("h3", { class: "section-title" }, "Ações remotas"), resumoFila),
    el("div", { class: "row wrap ativo-acoes-botoes" }, ...botoes.map(([, botao]) => botao)),
    recado, historico,
  );

  function atualizarBotoes() {
    for (const [tipo, botao] of botoes) {
      botao.disabled = solicitando || itens.some(i => i.tipo === tipo && pendente(i));
    }
  }

  async function carregar() {
    clearTimeout(timer);
    if (!painel.isConnected) return;
    const atual = ++revisao;
    try {
      const dados = await api.get(rota);
      if (atual !== revisao || !painel.isConnected) return;
      painel.hidden = !dados.vinculado;
      if (!dados.vinculado) return;
      const data = dados.ultimo_contato ? fmtDate(dados.ultimo_contato, true) : "sem registro";
      contato.textContent = "Último contato do agente: " + data
        + (dados.recebe_acoes ? "" : ". Aguardando o primeiro contato de uma versão compatível com ações remotas.");
      itens = dados.historico;
      atualizarResumoFila();
      if (!anteriores.length) cursor = dados.proximo;
      atualizarBotoes();
      desenharHistorico();
    } catch (e) {
      if (atual === revisao && !painel.hidden) informar(e.message);
    } finally {
      if (atual === revisao && painel.isConnected && !painel.hidden && itens.some(pendente)) {
        timer = setTimeout(carregar, 8000);
      }
    }
  }

  function atualizarResumoFila() {
    const total = itens.filter(pendente).length;
    const texto = total === 1 ? "1 pendente" : `${total} pendentes`;
    resumoFila.hidden = total === 0;
    if (resumoFila.textContent !== texto) resumoFila.textContent = texto;
  }

  async function carregarAnteriores() {
    mais.disabled = true;
    try {
      const dados = await api.get(rota, { antes_de: cursor });
      if (!painel.isConnected) return;
      anteriores.push(...dados.historico);
      cursor = dados.proximo;
      desenharHistorico();
    } catch (e) {
      informar(e.message);
    } finally {
      mais.disabled = false;
    }
  }

  function desenharHistorico() {
    const todos = new Map([...anteriores, ...itens].map(i => [i.id, i]));
    vazio.hidden = todos.size > 0;
    mais.hidden = !cursor;
    lista.replaceChildren(...[...todos.values()].sort((a, b) => b.id - a.id).map(i => el("li", {},
      el("div", { class: "row between wrap" },
        el("strong", {}, ACOES.find(([tipo]) => tipo === i.tipo)?.[1] || i.tipo),
        el("span", { class: `chip ${TONS[i.estado] || ""}` }, ESTADOS[i.estado] || i.estado)),
      el("small", { class: "muted" }, i.solicitante + " · " + fmtDate(i.solicitada_em, true)),
      i.resultado || i.encerrada_em ? el("p", {}, [
        RESULTADOS[i.resultado], i.encerrada_em ? fmtDate(i.encerrada_em, true) : "",
      ].filter(Boolean).join(" · ")) : null,
    )));
  }

  function informar(texto) {
    recado.textContent = texto;
    recado.hidden = !texto;
  }

  async function solicitar(tipo) {
    if (solicitando) return;
    solicitando = true;
    atualizarBotoes();
    informar("");
    try {
      const registrada = await api.request("POST", rota, { body: { tipo }, enfileirar: false });
      if (!itens.some(i => i.id === registrada.id)) itens.unshift(registrada);
      atualizarResumoFila();
      desenharHistorico();
    } catch (e) {
      informar(e.message);
    } finally {
      solicitando = false;
      await carregar();
      atualizarBotoes();
    }
  }

  setTimeout(carregar, 0);
  return painel;
}
