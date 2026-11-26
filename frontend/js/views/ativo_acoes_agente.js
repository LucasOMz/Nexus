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

export function botaoAcoesAgente(ativoId, patrimonio) {
  const rota = `/ativos/${ativoId}/acoes-agente`;
  const botao = el("button", {
    class: "btn outline small ativo-acoes-abrir", type: "button", hidden: true,
    "aria-haspopup": "dialog", onclick: () => abrirAcoesAgente(rota, patrimonio, botao),
    html: icon("integracoes", 17) + " Ações remotas",
  });
  api.get(rota).then(dados => { if (botao.isConnected) botao.hidden = !dados.vinculado; }).catch(() => {});
  return botao;
}

function abrirAcoesAgente(rota, patrimonio, origem) {
  const painel = el("dialog", { class: "dialog ativo-acoes-agente", "aria-labelledby": "ativo-acoes-titulo" });
  const resumoFila = el("span", { class: "chip aviso", role: "status", hidden: true });
  const fechar = el("button", { class: "iconbtn", type: "button", title: "Fechar", "aria-label": "Fechar",
    autofocus: true, onclick: () => painel.close(), html: icon("close", 20) });
  const contato = el("p", { class: "muted" });
  const recado = el("p", { class: "muted", role: "status", hidden: true });
  const lista = el("ul", { class: "ativo-acoes-historico" });
  const vazio = el("p", { class: "muted" }, "Carregando histórico…");
  let itens = [];
  let anteriores = [];
  let cursor = null;
  let solicitando = false;
  let vinculado = false;
  let timer;
  let revisao = 0;

  const botoes = ACOES.map(([tipo, rotulo, curto, icone]) => [tipo, el("button", {
    class: "btn tonal small", type: "button", disabled: true, onclick: () => solicitar(tipo), title: rotulo,
    "aria-label": rotulo, html: icon(icone, 16) + " " + curto,
  })]);
  const atualizar = el("button", { class: "iconbtn", type: "button", title: "Atualizar histórico",
    "aria-label": "Atualizar histórico", onclick: carregar, html: icon("refresh", 19) });
  const mais = el("button", { class: "btn text", type: "button", hidden: true, onclick: carregarAnteriores },
    "Ver ações anteriores");
  painel.append(
    el("div", { class: "row between ativo-acoes-topo" },
      el("div", {}, el("h2", { id: "ativo-acoes-titulo" }, "Ações remotas"),
        el("p", { class: "muted" }, patrimonio)), fechar),
    el("div", { class: "row between wrap ativo-acoes-contato" }, contato, resumoFila),
    el("div", { class: "row wrap ativo-acoes-botoes" }, ...botoes.map(([, botao]) => botao)),
    recado,
    el("div", { class: "row between ativo-acoes-historico-topo" },
      el("h3", { class: "section-title" }, "Histórico"), atualizar),
    vazio, lista, mais,
  );

  painel.addEventListener("close", () => {
    clearTimeout(timer);
    painel.remove();
    if (origem.isConnected && !origem.hidden) origem.focus();
  });
  painel.addEventListener("click", ev => {
    if (ev.target !== painel) return;
    const { left, right, top, bottom } = painel.getBoundingClientRect();
    if (ev.clientX < left || ev.clientX > right || ev.clientY < top || ev.clientY > bottom) painel.close();
  });

  function atualizarBotoes() {
    for (const [tipo, botao] of botoes) {
      botao.disabled = !vinculado || solicitando || itens.some(i => i.tipo === tipo && pendente(i));
    }
  }

  async function carregar() {
    clearTimeout(timer);
    if (!painel.isConnected) return;
    const atual = ++revisao;
    try {
      const dados = await api.get(rota);
      if (atual !== revisao || !painel.isConnected) return;
      vinculado = dados.vinculado;
      origem.hidden = !vinculado;
      if (vinculado) {
        const data = dados.ultimo_contato ? fmtDate(dados.ultimo_contato, true) : "sem registro";
        contato.textContent = "Último contato do agente: " + data
          + (dados.recebe_acoes ? "" : ". Aguardando contato de um agente compatível.");
      } else {
        contato.textContent = "Agente sem vínculo ativo.";
      }
      itens = dados.historico;
      vazio.textContent = "Nenhuma solicitação registrada.";
      atualizarResumoFila();
      if (!anteriores.length) cursor = dados.proximo;
      atualizarBotoes();
      desenharHistorico();
    } catch (e) {
      if (atual === revisao && painel.isConnected) {
        if (!vinculado) vazio.textContent = "Histórico indisponível.";
        informar(e.message);
      }
    } finally {
      if (atual === revisao && painel.isConnected && vinculado && itens.some(pendente)) {
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

  document.body.append(painel);
  painel.showModal();
  carregar();
}
