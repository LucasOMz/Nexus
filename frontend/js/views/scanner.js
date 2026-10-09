/**
 * Leitura de ativos — feita para LEITOR FÍSICO de QR Code (que digita o código
 * como teclado) e para digitação manual do identificador. NÃO usa câmera.
 * @module views/scanner
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { ctx } from "../context.js";
import { el, icon, toast, dialog, statusBadge, fmtDate, mostrarErro } from "../ui.js";
import { openForm as openFormManutencao } from "./manutencoes.js";
import { loadLookups, optionsOf } from "../lookups.js";
import { mensagemErro, erroDeResposta } from "../erros.js";
import { abrirNovoAtivoComQR } from "./ativos.js";

/** Mantida para compatibilidade com o roteador (nada a desligar). */
export function stopScanner() {}

let historico = [];

// ---------------------------------------------------------------------------
// Etiquetas em branco (QR sem dono, para colar e cadastrar depois)
// ---------------------------------------------------------------------------
let resumoEtiquetasEl = null;

/** Baixa o PDF do lote (tamanho exato, para imprimir em qualquer impressora). */
async function baixarPdfLote(lote, quantidade) {
  const url = `/api/v1/zerados/etiquetas.pdf?lote=${encodeURIComponent(lote)}&quantidade=${Math.max(1, quantidade || 1)}`;
  const res = await fetch(url, { headers: { Authorization: "Bearer " + state.access } });
  if (!res.ok) throw erroDeResposta(res.status, await res.json().catch(() => null));
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `etiquetas_branco_${lote}.pdf`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

/** Escolhe o destino (impressora cadastrada ou PDF) e a quantidade. */
async function imprimirLote(lote, livres) {
  let dispositivos = [];
  try { dispositivos = await api.get("/print/dispositivos"); } catch { dispositivos = []; }

  const destino = el("select", {},
    el("option", { value: "pdf" }, "Baixar PDF (imprimir em qualquer impressora)"),
    ...dispositivos.map((d) => el("option", { value: `d${d.id}` }, `Imprimir em ${d.nome}${d.padrao ? " (padrão)" : ""}`)),
  );
  const qtd = el("input", { type: "number", min: "1", value: String(Math.max(1, livres || 1)), style: "width:110px" });

  dialog({
    title: `Imprimir lote ${lote}`,
    body: el("div", {},
      el("p", { class: "muted", style: "margin-top:0" }, `${livres} etiqueta(s) ainda livre(s) neste lote.`),
      el("div", { class: "field" }, el("label", {}, "Destino"), destino),
      el("div", { class: "field" }, el("label", {}, "Quantidade"), qtd),
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Continuar", variant: "filled", onClick: async (close) => {
        try {
          const n = Math.max(1, Number(qtd.value) || 1);
          if (destino.value === "pdf") {
            await baixarPdfLote(lote, n);
            toast("PDF gerado");
          } else {
            const r = await api.post("/zerados/imprimir", {
              lote, quantidade: n, dispositivo_id: Number(destino.value.slice(1)),
            });
            toast(r.status === "error" ? (r.detail || "Falha ao imprimir") : `${r.quantidade} etiqueta(s) enviadas`);
          }
          close();
          atualizarResumoEtiquetas();
        } catch (e) { mostrarErro(e, "imprimir as etiquetas em branco"); }
      } },
    ],
  });
}

/** Recarrega o resumo (livres por lote) exibido na tela. */
async function atualizarResumoEtiquetas() {
  if (!resumoEtiquetasEl) return;
  try {
    const livres = await api.get("/zerados", { status: "livre", por_pagina: 1 });
    const lotes = await api.get("/zerados/lotes");

    resumoEtiquetasEl.innerHTML = "";
    resumoEtiquetasEl.append(
      el("p", { style: "margin:0 0 12px;font-weight:600" },
        `${livres.livres} etiqueta(s) livre(s) · ${lotes.length} lote(s)`),
    );
    if (!lotes.length) {
      resumoEtiquetasEl.append(el("p", { class: "muted", style: "margin:0" }, "Nenhum lote gerado ainda."));
      return;
    }

    const lista = el("div", {});
    for (const l of lotes.slice(0, 8)) {
      const btnImprimir = el("button", {
        class: "btn tonal small",
        onclick: () => imprimirLote(l.lote, l.livres),
        html: icon("print", 16) + " Imprimir",
      });
      btnImprimir.disabled = l.livres === 0;
      lista.append(el("div", { class: "list-row" },
        el("div", { class: "list-main" },
          el("div", { class: "list-title" }, l.lote),
          el("div", { class: "list-sub" },
            `${l.total} etiqueta(s) · ${l.livres} livre(s) · ${l.usados} usada(s) · ${fmtDate(l.criado_em, true)}`),
        ),
        el("div", { class: "row" },
          btnImprimir,
          el("button", {
            class: "btn outlined small",
            onclick: () => baixarPdfLote(l.lote, l.livres || l.total).catch((e) => mostrarErro(e, "gerar o PDF")),
            html: icon("download", 16) + " PDF",
          }),
        ),
      ));
    }
    resumoEtiquetasEl.append(lista);
  } catch (e) {
    resumoEtiquetasEl.innerHTML = "";
    resumoEtiquetasEl.append(el("p", { class: "text-error", style: "margin:0" }, e.message));
  }
}

/** Card "Etiquetas em branco": quantidade + geração. */
function secaoEtiquetasBrancas() {
  const qtd = el("input", { type: "number", min: "1", max: "1000", value: "10", style: "width:110px" });
  const gerar = el("button", { class: "btn filled small", html: icon("add", 18) + " Gerar etiquetas em branco" });
  const resumo = el("div", { style: "margin-top:16px" });
  resumoEtiquetasEl = resumo;

  gerar.addEventListener("click", async () => {
    const quantidade = Number(qtd.value) || 0;
    if (quantidade < 1) { toast("Informe a quantidade de etiquetas"); return; }
    gerar.disabled = true;
    try {
      const r = await api.post("/zerados", { quantidade, dominio: state.dominio });
      toast(`${r.quantidade} etiqueta(s) em branco geradas — lote ${r.lote}`);
      await atualizarResumoEtiquetas();
      imprimirLote(r.lote, r.quantidade);
    } catch (e) {
      mostrarErro(e, "gerar as etiquetas em branco");
    } finally {
      gerar.disabled = false;
    }
  });

  const card = el("div", { class: "card mt" },
    el("div", { class: "section-title", style: "margin:0" }, "Etiquetas em branco"),
    el("p", { class: "muted", style: "font-size:13px;margin:6px 0 16px" },
      "Gere QR Codes sem dono, imprima e cole nos equipamentos. Ao ler um deles na janela acima, "
      + "o cadastro abre já vinculado à etiqueta — basta preencher os dados."),
    el("div", { class: "row", style: "gap:12px;align-items:flex-end;flex-wrap:wrap" },
      el("div", { class: "field", style: "margin:0" }, el("label", {}, "Quantidade"), qtd),
      gerar,
    ),
    resumo,
  );
  atualizarResumoEtiquetas();
  return card;
}

function fotoUrl(fotoId) {
  return fotoId ? `/api/v1/admin/fotos/${fotoId}/arquivo?token=${encodeURIComponent(state.access)}` : "";
}

async function processar(codigo, ui) {
  const texto = (codigo || "").trim();
  if (!texto) return;
  ui.setStatus("Consultando…", "");
  try {
    const res = await api.post("/scanner/buscar", { codigo: texto });

    // Etiqueta EM BRANCO (gerada sem ativo): abre o cadastro já vinculado.
    if (res.tipo === "zerado") {
      ui.clear();
      ui.setStatus(`Etiqueta em branco ${res.zerado.codigo} — pronta para cadastrar`, "ok");
      abrirCadastroDeEtiqueta(res.zerado, ui);
      return;
    }

    const ativo = res.ativo;
    ui.setStatus(`Encontrado: ${ativo.patrimonio}`, "ok");
    historico = [{ ...ativo, lidoEm: new Date().toISOString() }, ...historico].slice(0, 12);
    ui.clear();
    ui.renderHistorico();
    abrirCartao(ativo);
  } catch (e) {
    ui.setStatus(e.message, "err");
    ui.clear();
  }
}

/** Etiqueta em branco lida: leva o operador direto para o cadastro do equipamento. */
function abrirCadastroDeEtiqueta(zerado, ui) {
  if (!state.podeModulo("ativos") || !state.canWrite) {
    dialog({
      title: `Etiqueta em branco ${zerado.codigo}`,
      body: el("p", { style: "margin:0" },
        "Esta etiqueta ainda não está vinculada a nenhum equipamento, e você não tem permissão para cadastrar ativos. "
        + "Peça a um usuário com permissão de escrita para fazer o cadastro."),
      actions: [{ label: "Fechar", variant: "text" }],
    });
    return;
  }
  abrirNovoAtivoComQR(zerado.payload, zerado.codigo, (ativo) => {
    ui.setStatus(`Equipamento ${ativo.patrimonio} cadastrado com a etiqueta ${zerado.codigo}`, "ok");
    toast(`Ativo ${ativo.patrimonio} cadastrado`);
    atualizarResumoEtiquetas();
  });
}

/**
 * Abre a manutenção do ativo que acabou de ser lido.
 *
 * Carrega os cadastros auxiliares (fornecedores) e reaproveita o MESMO
 * formulário da guia Manutenções — uma implementação só. A ordem aparece na
 * guia Manutenções como qualquer outra.
 */
async function abrirManutencao(ativo) {
  try {
    const lookups = await loadLookups();
    await openFormManutencao(lookups, ativo);
  } catch (e) {
    mostrarErro(e, "abrir a manutenção");
  }
}

function abrirCartao(ativo) {
  const podeAcoes = state.podeModulo("ativos") && state.canWrite;
  const acoes = [];

  if (podeAcoes) {
    acoes.push({ label: "Alterar status", variant: "outlined", onClick: () => alterarStatus(ativo) });
    acoes.push({ label: "Imprimir etiqueta", variant: "outlined", onClick: () => imprimir(ativo) });
    acoes.push({ label: "Histórico", variant: "outlined", onClick: () => verHistorico(ativo) });
    acoes.push({ label: "Atribuir", variant: "tonal", onClick: () => atribuir(ativo) });
    if (ativo.dominio === "impressora") {
      acoes.push({ label: "Leitura de contador", variant: "tonal", onClick: () => leituraContador(ativo) });
    }
  }

  // Abrir manutenção direto da leitura: o ativo já está identificado, então a
  // pessoa só preenche a ordem — que aparece na guia Manutenções.
  if (state.podeModulo("manutencoes") && state.canWrite) {
    acoes.push({ label: "Abrir manutenção", variant: "filled", onClick: () => abrirManutencao(ativo) });
  }

  const origem = { qr: "QR Code (assinatura validada)", id: "ID informado", patrimonio: "Patrimônio", serie: "Nº de série" }[ativo.origem] || ativo.origem;
  const linhas = [
    ["Modelo", ativo.modelo || "—"],
    ["Marca", ativo.marca || "—"],
    ["Nº de série", ativo.numero_serie || "—"],
    ["Origem da leitura", origem],
  ];
  if (ativo.contador_paginas !== null && ativo.contador_paginas !== undefined) {
    linhas.push(["Contador", `${ativo.contador_paginas} páginas`]);
  }

  dialog({
    title: `Patrimônio ${ativo.patrimonio}`,
    body: el("div", {},
      ativo.foto_id ? el("img", { class: "photo-preview mb", src: fotoUrl(ativo.foto_id), alt: "Foto do ativo" }) : null,
      el("div", { style: "margin:6px 0 14px", html: statusBadge(ativo.status) }),
      ...linhas.map(([k, v]) => el("div", { class: "row between", style: "border-bottom:1px solid var(--md-sys-color-outline-variant);padding:9px 0" },
        el("span", { class: "muted" }, k), el("span", {}, String(v)))),
    ),
    actions: [{ label: "Fechar", variant: "text" }, ...acoes],
  });
}

async function alterarStatus(ativo) {
  const sel = el("select", {}, ...["estoque", "reservado", "em_uso", "manutencao", "descartado", "emprestado"].map((s) => el("option", { value: s, ...(ativo.status === s ? { selected: "" } : {}) }, s)));
  dialog({
    title: "Alterar status",
    body: el("div", { class: "field" }, el("label", {}, "Novo status"), sel),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Salvar", variant: "filled", onClick: async (close) => {
        try { await api.patch(`/ativos/${ativo.id}/status`, { status: sel.value }); close(); toast("Status atualizado"); }
        catch (e) { mostrarErro(e); }
      } },
    ],
  });
}

async function atribuir(ativo) {
  const lookups = await loadLookups();
  const sel = el("select", { html: optionsOf(lookups.usuarios, { label: "nome" }) });
  dialog({
    title: "Atribuir a colaborador",
    body: el("div", { class: "field" }, el("label", {}, "Colaborador"), sel),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Atribuir e gerar Termo", variant: "filled", onClick: async (close) => {
        if (!sel.value) { toast("Selecione um colaborador"); return; }
        try { await api.post(`/ativos/${ativo.id}/atribuir`, { usuario_id: Number(sel.value) }); close(); toast("Atribuído — Termo gerado"); }
        catch (e) { mostrarErro(e); }
      } },
    ],
  });
}

async function imprimir(ativo) {
  try {
    const res = await api.post("/print/batch", { ativo_ids: [ativo.id], formato: "zpl", copies: 1 });
    const erro = res.jobs.find((j) => j.status === "error");
    if (erro) toast(mensagemErro(erro.detail, erro.status) || "Falha ao imprimir");
    else toast("Etiqueta enviada para o dispositivo de impressão");
  } catch (e) { mostrarErro(e); }
}

async function leituraContador(ativo) {
  const contador = el("input", { type: "number", min: 0, value: ativo.contador_paginas || 0 });
  dialog({
    title: "Leitura de contador",
    body: el("div", { class: "field" }, el("label", {}, "Contador atual (páginas)"), contador),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Registrar", variant: "filled", onClick: async (close) => {
        try { await api.post(`/ativos/${ativo.id}/leituras`, { contador: Number(contador.value) || 0 }); close(); toast("Leitura registrada"); }
        catch (e) { mostrarErro(e); }
      } },
    ],
  });
}

async function verHistorico(ativo) {
  const movs = await api.get("/movimentacoes", { ativo_id: ativo.id, size: 50 }).catch(() => ({ items: [] }));
  dialog({
    title: "Histórico de movimentações",
    body: el("div", {}, ...(movs.items.length
      ? movs.items.map((m) => el("div", { class: "row between", style: "border-bottom:1px solid var(--md-sys-color-outline-variant);padding:9px 0" },
          el("span", {}, m.tipo), el("span", { class: "muted" }, fmtDate(m.data_mov, true))))
      : [el("p", { class: "muted" }, "Sem movimentações")])),
    actions: [{ label: "Fechar", variant: "text" }],
  });
}

export async function renderScanner(root) {
  ctx.setTitle("Leitura");
  ctx.setFab(null);

  const input = el("input", {
    class: "scanner-input",
    id: "scanner-input",
    type: "text",
    autocomplete: "off",
    autocapitalize: "off",
    spellcheck: "false",
    placeholder: "Aguardando leitura…",
  });
  const status = el("p", { class: "scanner-status" });
  const histBox = el("div", { class: "card", style: "margin-top:26px" });

  const ui = {
    clear: () => { input.value = ""; },
    setStatus: (msg, tipo) => {
      status.className = "scanner-status" + (tipo ? ` ${tipo}` : "");
      status.textContent = msg;
    },
    renderHistorico: () => {
      histBox.innerHTML = "";
      histBox.append(el("div", { class: "section-title" }, "Últimas leituras"));
      if (!historico.length) {
        histBox.append(el("p", { class: "muted", style: "margin:0" }, "Nenhuma leitura nesta sessão."));
        return;
      }
      historico.forEach((a) => {
        const row = el("div", { class: "list-row", style: "cursor:pointer" },
          el("div", { class: "list-main" },
            el("div", { class: "list-title" }, a.patrimonio),
            el("div", { class: "list-sub" }, `${a.modelo || "sem modelo"} · ${a.dominio === "ti" ? "TI" : "Impressora"}`),
          ),
          el("div", { class: "row" },
            el("span", { html: statusBadge(a.status) }),
            el("span", { class: "muted", style: "font-size:12px" }, fmtDate(a.lidoEm, true))),
        );
        row.addEventListener("click", () => abrirCartao(a));
        histBox.append(row);
      });
    },
  };

  // O leitor físico digita o código e envia Enter.
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      processar(input.value, ui);
    }
  });

  root.innerHTML = "";
  root.append(
    el("h1", { class: "page-title" }, "Leitura de ativos"),
    el("p", { class: "page-sub" }, "Use o leitor de QR Code (ele digita o código e pressiona Enter) ou informe o patrimônio / nº de série manualmente."),
    el("div", { class: "scanner-panel card" },
      el("div", { class: "row", style: "justify-content:center;margin-bottom:16px" },
        el("span", { class: "pulse-dot" }), el("span", { class: "muted" }, "Pronto para receber a leitura")),
      input,
      status,
      el("div", { class: "row", style: "justify-content:center;gap:10px;margin-top:20px" },
        el("button", { class: "btn filled", onclick: () => { input.value = ""; input.focus(); ui.setStatus("Pronto — pode ler o próximo código", ""); }, html: icon("check", 18) + " Pronto para leitura" }),
        el("button", { class: "btn outlined", onclick: () => input.focus(), html: icon("edit", 18) + " Digitar identificador" }),
        el("button", { class: "btn text", onclick: () => { historico = []; ui.renderHistorico(); }, html: icon("trash", 18) + " Limpar histórico" }),
      ),
    ),
    histBox,
    secaoEtiquetasBrancas(),
  );

  ui.renderHistorico();
  setTimeout(() => input.focus(), 60);
}
