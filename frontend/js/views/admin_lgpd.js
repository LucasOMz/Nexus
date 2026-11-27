import { api } from "../api.js";
import { dialog, el, icon, skeleton } from "../ui.js";

const numeros = new Intl.NumberFormat("pt-BR");
const regras = {
  auditoria: ["Logs de auditoria", "Preserva o histórico de ações. A limpeza desvincula o usuário e oculta o IP."],
  movimentacoes: ["Movimentações de patrimônio", "Preserva o histórico de entradas, saídas e transferências."],
  manutencoes: ["Histórico de manutenções", "Preserva o histórico dos serviços realizados nos equipamentos."],
  reportes: ["Reportes de erro", ""],
  logs_acesso: ["Logs de acesso", ""],
  notificacoes: ["Notificações", ""],
  fotos: ["Fotos de ativos", ""],
};

function quantidade(valor, singular, plural) {
  return numeros.format(valor) + " " + (valor === 1 ? singular : plural);
}

function descreverPrazo(regra) {
  if (!regra.dias) return "Enquanto o ativo estiver cadastrado";
  const prazo = regra.dias % 365 === 0
    ? quantidade(regra.dias / 365, "ano", "anos")
    : quantidade(regra.dias, "dia", "dias");
  if (regra.acao === "manter") return "Guarda mínima de " + prazo;
  return prazo + (regra.acao === "anonimizar" ? " antes de anonimizar" : " antes de excluir");
}

function itemPolitica(item) {
  const [nome, descricao] = regras[item.tipo] || [item.tipo, item.motivo];
  const badge = item.pendentes
    ? el("span", { class: "badge aviso" }, quantidade(item.pendentes, "pendente", "pendentes"))
    : item.acao === "manter" ? el("span", { class: "badge" }, "Preservado") : null;
  return el("details", { class: "lgpd-regra" },
    el("summary", {},
      el("span", { class: "lgpd-regra-texto" }, el("strong", {}, nome), el("small", { class: "muted" }, descreverPrazo(item))),
      badge, el("span", { class: "lgpd-seta", "aria-hidden": "true", html: icon("chevron", 16) })),
    el("div", { class: "lgpd-regra-detalhe" },
      el("p", {}, descricao),
      el("small", { class: "muted" }, quantidade(item.total, "registro no histórico", "registros no histórico"))));
}

function explicacaoOutros(tipos) {
  if (!tipos.length) return null;
  return el("details", { class: "lgpd-regra" },
    el("summary", {}, el("strong", { class: "lgpd-regra-texto" }, "Dados fora desta limpeza"),
      el("span", { class: "lgpd-seta", "aria-hidden": "true", html: icon("chevron", 16) })),
    el("p", { class: "lgpd-regra-detalhe muted" }, tipos.map(tipo => regras[tipo]?.[0] || tipo).join(" · ")));
}

function efeitos(apagar, anonimizar) {
  return [
    apagar ? quantidade(apagar, "registro para excluir", "registros para excluir") : "",
    anonimizar ? quantidade(anonimizar, "registro para anonimizar", "registros para anonimizar") : "",
  ].filter(Boolean).join(" · ");
}

function confirmarLimpeza(dados, executar) {
  const limite = el("input", { id: "lgpd-limite", type: "number", min: 1, max: 50000, step: 1,
    value: 5000, required: true, "aria-describedby": "lgpd-limite-dica" });
  const aviso = el("p", { class: "lgpd-aviso", role: "status" });
  const confirmar = el("button", { type: "submit", form: "lgpd-confirmar", class: "btn danger" }, "Confirmar limpeza");
  const cancelar = el("button", { type: "button", class: "btn text" }, "Cancelar");
  const form = el("form", { id: "lgpd-confirmar" },
    el("p", {}, efeitos(dados.a_apagar, dados.a_anonimizar)),
    el("p", { class: "muted" }, "As alterações são permanentes. A anonimização preserva a ação registrada no histórico."),
    el("details", { class: "lgpd-regra" },
      el("summary", {}, "Limite do lote", el("span", { class: "lgpd-seta", "aria-hidden": "true", html: icon("chevron", 16) })),
      el("div", { class: "field lgpd-regra-detalhe" }, el("label", { for: "lgpd-limite" }, "Máximo por tipo de registro"),
        limite, el("small", { id: "lgpd-limite-dica", class: "muted" }, "Se houver mais registros, execute a limpeza novamente."))),
    aviso);
  const modal = dialog({ title: "Executar limpeza de dados", body: form,
    actions: [{ elemento: cancelar }, { elemento: confirmar }] });
  modal.dlg.setAttribute("role", "dialog");
  modal.dlg.setAttribute("aria-modal", "true");
  modal.dlg.setAttribute("aria-label", "Executar limpeza de dados");
  limite.addEventListener("invalid", () => { limite.closest("details").open = true; });
  cancelar.focus();
  cancelar.onclick = modal.close;
  modal.overlay.addEventListener("click", (evento) => {
    if (evento.target === modal.overlay && confirmar.disabled) evento.stopImmediatePropagation();
  }, { capture: true });
  form.onsubmit = async (evento) => {
    evento.preventDefault();
    if (confirmar.disabled) return;
    const maximo = limite.valueAsNumber;
    confirmar.disabled = cancelar.disabled = limite.disabled = true;
    aviso.textContent = "Limpando os registros…";
    try {
      const resultado = await api.request("POST", "/admin/lgpd/expurgar", {
        query: { confirmo: true, limite: maximo }, enfileirar: false,
      });
      modal.close();
      await executar(resultado);
    } catch (erro) {
      aviso.textContent = erro.message;
      confirmar.disabled = cancelar.disabled = limite.disabled = false;
    }
  };
}

export async function renderLgpd(root) {
  const painel = el("div", { class: "lgpd-painel" }, skeleton(3));
  root.replaceChildren(painel);

  async function carregar(botaoAtualizar, botaoLimpar, ultimaLimpeza) {
    if (botaoAtualizar) botaoAtualizar.disabled = true;
    if (botaoLimpar) botaoLimpar.disabled = true;
    try {
      const dados = await api.get("/admin/lgpd/retencao");
      if (!painel.isConnected) return;
      const atualizar = el("button", { class: "btn outline", type: "button",
        onclick: () => carregar(atualizar, limpar) }, el("span", { html: icon("refresh", 17) }), "Atualizar");
      const limpar = el("button", { type: "button", class: "btn filled", disabled: !dados.pendentes,
        onclick: () => confirmarLimpeza(dados, resultado => carregar(atualizar, limpar, resultado)) }, "Executar limpeza");
      const resumo = ultimaLimpeza && el("p", { class: "recado ok", role: "status" },
        ultimaLimpeza.total
          ? "Limpeza concluída. " + [
              quantidade(Object.values(ultimaLimpeza.apagados).reduce((soma, n) => soma + n, 0), "registro excluído", "registros excluídos"),
              quantidade(ultimaLimpeza.anonimizados, "registro anonimizado", "registros anonimizados"),
            ].join(" · ")
          : "Não havia registros pendentes quando a limpeza foi executada.");
      painel.replaceChildren(
        el("section", { class: "card lgpd-resumo" },
          el("div", { class: "lgpd-topo" },
            el("div", {},
              el("h2", { class: "section-title" }, "Limpeza de dados"),
              el("p", { class: "muted" }, "Revise os registros com prazo vencido e inicie a limpeza quando precisar.")),
            el("div", { class: "lgpd-acoes" }, atualizar, limpar)),
          el("div", { class: "lgpd-situacao" },
            el("span", { class: "badge " + (dados.pendentes ? "aviso" : "ok") },
              dados.pendentes ? quantidade(dados.pendentes, "registro pendente", "registros pendentes") : "Sem limpeza pendente"),
            dados.pendentes ? el("small", {}, efeitos(dados.a_apagar, dados.a_anonimizar)) : null),
          resumo),
        el("section", { class: "card lgpd-politica" },
          el("h2", { class: "section-title" }, "Prazos de guarda"),
          el("p", { class: "muted" }, "Abra um item para ver o que fica no histórico."),
          ...(dados.itens || []).map(itemPolitica),
          explicacaoOutros(dados.sem_tabela || [])));
      if (botaoAtualizar) (ultimaLimpeza && !limpar.disabled ? limpar : atualizar).focus();
    } catch (erro) {
      if (!painel.isConnected) return;
      painel.replaceChildren(el("div", { class: "card" },
        ultimaLimpeza ? el("p", { class: "recado ok" }, ultimaLimpeza.mensagem) : null,
        el("p", { role: "alert" }, erro.message),
        el("button", { class: "btn tonal", type: "button", onclick: () => carregar() }, "Tentar novamente")));
    }
  }

  await carregar();
}
