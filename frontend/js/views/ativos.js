/**
 * Ativos patrimoniais: tabela, filtros, CRUD (com foto do banco de fotos),
 * QR Code, impressão em dispositivo cadastrado, status, atribuição e detalhe.
 * @module views/ativos
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { ctx } from "../context.js";
import { el, icon, toast, dialog, confirmSheet, emptyState, skeleton, fmtDate, fmtMoney, statusBadge, mostrarErro } from "../ui.js";
import { loadLookups, optionsOf } from "../lookups.js";
import { erroDeResposta } from "../erros.js";
import { renderLabelSVG, renderAvisos } from "../label.js";

// Itens por página. 25 é o padrão; 50 ajuda quando a lista é longa.
const TAMANHOS_PAGINA = [25, 50];
let pageSize = 25;
/**
 * Ativo a DESTACAR na lista, quando se chega aqui por um link de outra tela
 * (ex.: clicar num item dentro do filtro dos Relatórios).
 */
let destaqueId = null;

/**
 * Lê `?busca=` e `?destaque=` da URL e limpa a barra de endereço.
 *
 * A limpeza evita que o destaque se repita ao navegar entre páginas, e mantém
 * o botão "voltar" do navegador previsível.
 */
function aplicarDestaqueDaUrl() {
  const alvo = /[?&]destaque=(\d+)/.exec(location.hash);
  const busca = /[?&]busca=([^&]+)/.exec(location.hash);
  if (!alvo && !busca) return;
  if (busca) filtroSearch = decodeURIComponent(busca[1]);
  if (alvo) destaqueId = Number(alvo[1]);
  history.replaceState(null, "", "#/ativos");
}
let page = 1;
let filtroStatus = "";
let filtroSearch = "";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
export const fotoUrl = (id) => (id ? `/api/v1/admin/fotos/${id}/arquivo?token=${encodeURIComponent(state.access)}` : "");

function extFields(dominio, ativo) {
  const ti = ativo?.ti || {};
  const imp = ativo?.impressora || {};
  if (dominio === "ti") {
    return `
      <div class="form-section">
        <h4>Especificações de TI</h4>
        <div class="form-grid">
          <div class="field"><label>Hostname</label><input name="hostname" value="${esc(ti.hostname)}"></div>
          <div class="field"><label>MAC Address</label><input name="mac_address" value="${esc(ti.mac_address)}" placeholder="AA:BB:CC:DD:EE:FF"></div>
          <div class="field"><label>IP</label><input name="ip" value="${esc(ti.ip)}"></div>
          <div class="field"><label>Sistema Operacional</label><input name="so" value="${esc(ti.so)}"></div>
          <div class="field"><label>CPU</label><input name="cpu" value="${esc(ti.cpu)}"></div>
          <div class="field"><label>Domínio AD</label><input name="dominio_ad" value="${esc(ti.dominio_ad)}"></div>
          <div class="field"><label>RAM (GB)</label><input type="number" name="ram_gb" value="${ti.ram_gb ?? ""}"></div>
          <div class="field"><label>Armazenamento (GB)</label><input type="number" name="armazenamento_gb" value="${ti.armazenamento_gb ?? ""}"></div>
        </div>
      </div>`;
  }
  return `
    <div class="form-section">
      <h4>Especificações da Impressora</h4>
      <div class="form-grid">
        <div class="field"><label>IP</label><input name="ip" value="${esc(imp.ip)}"></div>
        <div class="field"><label>Hostname</label><input name="hostname" value="${esc(imp.hostname)}"></div>
        <div class="field"><label>Driver</label><input name="driver" value="${esc(imp.driver)}"></div>
        <div class="field"><label>Tipo de impressão</label>
          <select name="tipo_impressao">${["laser","jato","termica","matricial","plotter"].map((t) => `<option ${imp.tipo_impressao === t ? "selected" : ""}>${t}</option>`).join("")}</select></div>
        <div class="field"><label>Conectividade</label>
          <select name="conectividade">${["usb","rede","wifi","paralela","serial"].map((t) => `<option ${imp.conectividade === t ? "selected" : ""}>${t}</option>`).join("")}</select></div>
        <div class="field"><label>Colorida</label>
          <select name="colorida"><option value="false">Não</option><option value="true" ${imp.colorida ? "selected" : ""}>Sim</option></select></div>
        <div class="field"><label>Contador de páginas</label><input type="number" name="contador_paginas" value="${imp.contador_paginas ?? 0}"></div>
      </div>
    </div>`;
}

function commonFields(ativo, lookups, fotos) {
  const a = ativo || {};
  const opcoesFoto = ['<option value="">Sem foto</option>']
    .concat((fotos || []).map((f) => `<option value="${f.id}" ${a.foto_id === f.id ? "selected" : ""}>${esc(f.nome)}</option>`))
    .join("");
  return `
    <div class="form-grid">
      <div class="field"><label>Patrimônio *</label><input name="patrimonio" required value="${esc(a.patrimonio)}"></div>
      <div class="field"><label>Modelo</label><input name="modelo" value="${esc(a.modelo)}"></div>
      <div class="field"><label>Marca</label><input name="marca" value="${esc(a.marca)}"></div>
      <div class="field"><label>Nº de Série</label><input name="numero_serie" value="${esc(a.numero_serie)}"></div>
      <div class="field"><label>Categoria</label><select name="categoria_id">${optionsOf(lookups.categorias)}</select></div>
      <div class="field"><label>Localização</label><select name="localizacao_id">${optionsOf(lookups.localizacoes)}</select></div>
      <div class="field"><label>Departamento</label><select name="departamento_id">${optionsOf(lookups.departamentos)}</select></div>
      <div class="field"><label>Status</label>
        <select name="status">${["estoque","reservado","em_uso","manutencao","descartado","emprestado"].map((s) => `<option ${a.status === s ? "selected" : ""}>${s}</option>`).join("")}</select></div>
      <div class="field"><label>Garantia</label><input type="date" name="data_garantia" value="${esc(a.data_garantia)}"></div>
      <div class="field"><label>Valor (R$)</label><input type="number" step="0.01" name="valor" value="${a.valor ?? ""}"></div>
      <div class="field span-2"><label>Foto do ativo (Banco de Fotos)</label>
        <select name="foto_id">${opcoesFoto}</select>
        <span class="hint">As fotos são cadastradas em Administração → Banco de Fotos.</span>
      </div>
      <div class="field span-2"><label>Observações</label><textarea name="observacoes">${esc(a.observacoes)}</textarea></div>
    </div>`;
}

function collectForm(form) {
  const data = Object.fromEntries(new FormData(form).entries());
  for (const k of ["valor", "ram_gb", "armazenamento_gb", "contador_paginas", "categoria_id", "localizacao_id", "departamento_id", "foto_id"]) {
    data[k] = (data[k] === "" || data[k] === undefined) ? null : Number(data[k]);
  }
  data.colorida = data.colorida === "true";
  return data;
}

function buildPayload(data) {
  const payload = {
    patrimonio: data.patrimonio, modelo: data.modelo || null, marca: data.marca || null,
    numero_serie: data.numero_serie || null, categoria_id: data.categoria_id,
    localizacao_id: data.localizacao_id, departamento_id: data.departamento_id,
    status: data.status, data_garantia: data.data_garantia || null,
    valor: data.valor, observacoes: data.observacoes || null, foto_id: data.foto_id,
    dominio: state.dominio, tipo_item: "ativo",
  };
  if (state.dominio === "ti") {
    payload.ti = { hostname: data.hostname || null, mac_address: data.mac_address || null, ip: data.ip || null, so: data.so || null, dominio_ad: data.dominio_ad || null, cpu: data.cpu || null, ram_gb: data.ram_gb, armazenamento_gb: data.armazenamento_gb };
  } else {
    payload.impressora = { ip: data.ip || null, hostname: data.hostname || null, driver: data.driver || null, tipo_impressao: data.tipo_impressao || "laser", colorida: data.colorida, contador_paginas: data.contador_paginas || 0, conectividade: data.conectividade || "rede" };
  }
  return payload;
}

async function openForm(ativo, lookups, opcoes = {}) {
  const isEdit = Boolean(ativo);
  const qrPayload = opcoes.qrPayload || null;
  let fotos = [];
  try { fotos = await api.get("/admin/fotos", { dominio: state.dominio }); } catch { fotos = []; }

  const form = el("form", { html: commonFields(ativo, lookups, fotos) + extFields(state.dominio, ativo) });
  if (isEdit) {
    form.querySelector('[name="categoria_id"]').value = ativo.categoria_id || "";
    form.querySelector('[name="localizacao_id"]').value = ativo.localizacao_id || "";
    form.querySelector('[name="departamento_id"]').value = ativo.departamento_id || "";
    form.querySelector('[name="foto_id"]').value = ativo.foto_id || "";
  }

  // Veio de uma etiqueta em branco lida: avisa de forma destacada.
  const aviso = qrPayload ? el("div", {
    class: "card",
    style: "margin:0 0 16px;background:var(--md-sys-color-secondary-container);color:var(--md-sys-color-on-secondary-container)",
  }, el("div", { style: "font-weight:700;margin-bottom:4px" }, `Etiqueta em branco: ${opcoes.codigo || ""}`),
     el("div", { style: "font-size:13px" }, "Ao salvar, esta etiqueta fica vinculada ao equipamento. Depois disso a leitura abre o ativo normalmente.")) : null;

  dialog({
    title: isEdit ? "Editar ativo" : (qrPayload ? "Cadastrar equipamento" : "Novo ativo"),
    body: el("div", {}, aviso, form),
    wide: true,
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Salvar", variant: "filled", onClick: async (close) => {
        const payload = buildPayload(collectForm(form));
        if (qrPayload) payload.qr_payload = qrPayload;
        try {
          const salvo = isEdit ? await api.put(`/ativos/${ativo.id}`, payload) : await api.post("/ativos", payload);
          close();
          toast(isEdit ? "Ativo atualizado" : (qrPayload ? "Equipamento cadastrado" : "Ativo criado"));
          opcoes.onSaved?.(salvo);
          if (!opcoes.semAtualizar) refreshView();
        } catch (e) { mostrarErro(e, isEdit ? "salvar as alterações do ativo" : "cadastrar o ativo"); }
      } },
    ],
  });
}

function refreshView() {
  const root = document.getElementById("view");
  if (root) renderAtivos(root);
}

/**
 * Abre o cadastro de ativo já vinculado a uma ETIQUETA EM BRANCO lida.
 *
 * Usado pela tela de Leitura: ao ler um QR sem dono, o operador cai direto no
 * formulário e a etiqueta é vinculada ao salvar.
 * @param {string} qrPayload - payload lido (TIZERADO:...)
 * @param {string} codigo - código curto, só para exibir
 * @param {(ativo: object) => void} [onSaved]
 */
export async function abrirNovoAtivoComQR(qrPayload, codigo, onSaved) {
  const lookups = await loadLookups();
  openForm(null, lookups, { qrPayload, codigo, onSaved, semAtualizar: true });
}

/**
 * Mostra o QR Code do ativo — e a ETIQUETA PADRÃO montada, quando existe.
 *
 * A geometria vem do mesmo motor usado na impressão (`/print/preview`), então
 * o que aparece aqui é exatamente o que sai na impressora. Sem template padrão
 * cadastrado, mostra apenas o QR Code.
 */
async function acaoQR(ativo) {
  try {
    const qr = await api.post(`/qrcode/generate/${ativo.id}`);

    let layout = null;
    try {
      const preview = await api.post("/print/preview", { ativo_id: ativo.id, formato: "zpl" });
      layout = preview.layout;
    } catch {
      layout = null; // sem template cadastrado (ou sem dispositivo) → só o QR
    }

    const corpo = layout
      ? el("div", {},
          el("p", { class: "muted", style: "margin:0 0 10px;font-size:13px" },
            `Etiqueta padrão — ${layout.largura_mm} × ${layout.altura_mm} mm a ${layout.dpi} dpi:`),
          el("div", { class: "label-preview", html: renderLabelSVG(layout) }),
          renderAvisos(layout) ? el("div", { html: renderAvisos(layout) }) : null,
          el("details", { style: "margin-top:12px" },
            el("summary", { class: "muted", style: "font-size:12.5px" }, "Ver só o QR Code"),
            el("div", { class: "qr-preview", style: "margin-top:10px" },
              el("img", { src: qr.qr_data_url, alt: "QR" }),
              el("p", { class: "mono", style: "text-align:center;font-size:12px;word-break:break-all" }, qr.qr_payload),
            ),
          ),
        )
      : el("div", {},
          el("div", { class: "qr-preview" },
            el("img", { src: qr.qr_data_url, alt: "QR" }),
            el("p", { class: "mono", style: "text-align:center;word-break:break-all" }, qr.qr_payload),
          ),
          el("p", { class: "muted", style: "font-size:12.5px;margin:12px 0 0" },
            "Nenhuma etiqueta padrão cadastrada — mostrando apenas o QR Code. "
            + "Crie um template em Administração → Etiquetas para ver a etiqueta montada aqui."),
        );

    dialog({
      title: `QR Code — ${ativo.patrimonio}`,
      body: corpo,
      wide: Boolean(layout),
      actions: [
        { label: "Fechar", variant: "text" },
        { label: "Baixar PDF", variant: "outlined", onClick: async (close) => {
          try { await baixarEtiquetasPdf([ativo]); close(); toast("PDF gerado"); }
          catch (e) { mostrarErro(e, "gerar o PDF da etiqueta"); }
        } },
        { label: "Imprimir", variant: "filled", onClick: (close) => { close(); escolherDispositivo([ativo]); } },
      ],
    });
  } catch (e) { mostrarErro(e, "gerar o QR Code"); }
}

/** Baixa o PDF das etiquetas dos ativos indicados (impressão manual). */
async function baixarEtiquetasPdf(ativos) {
  const ids = ativos.map((a) => a.id).join(",");
  const url = `/api/v1/print/etiquetas.pdf?ids=${encodeURIComponent(ids)}`;
  const res = await fetch(url, { headers: { Authorization: "Bearer " + state.access } });
  if (!res.ok) throw erroDeResposta(res.status, await res.json().catch(() => null));
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = ativos.length === 1 ? `etiqueta_${ativos[0].patrimonio}.pdf` : "etiquetas.pdf";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

/** Deixa o operador escolher o dispositivo cadastrado antes de imprimir. */
async function escolherDispositivo(ativos) {
  let dispositivos = [];
  try { dispositivos = await api.get("/print/dispositivos", { dominio: state.dominio }); }
  catch (e) { mostrarErro(e); return; }

  // Sem dispositivo cadastrado ainda dá para gerar o PDF (imprimir em outra
  // impressora, inclusive de escritório).
  if (!dispositivos.length) {
    dialog({
      title: "Nenhum dispositivo de impressão",
      body: el("p", { class: "muted" },
        "Cadastre o destino em Administração → Impressão (fila compartilhada \\\\servidor\\impressora, agente ou CUPS). "
        + "Enquanto isso, você pode baixar o PDF da etiqueta para imprimir em qualquer impressora."),
      actions: [
        { label: "Fechar", variant: "text" },
        { label: "Baixar PDF", variant: "filled", onClick: async (close) => {
          try { await baixarEtiquetasPdf(ativos); close(); toast("PDF gerado"); }
          catch (e) { mostrarErro(e, "gerar o PDF das etiquetas"); }
        } },
      ],
    });
    return;
  }

  const padrao = dispositivos.find((d) => d.padrao);
  const sel = el("select", {}, ...dispositivos.map((d) => el("option", { value: d.id, ...(padrao && d.id === padrao.id ? { selected: "" } : {}) }, `${d.nome}${d.padrao ? " (padrão)" : ""}`)));
  const partes = el("input", { type: "number", min: 1, max: 10, value: 1 });
  // Só ZPL/TSPL aqui: PDF não é comando de impressora — para isso existe o
  // botão "Baixar PDF".
  const formato = el("select", {}, ...["zpl", "tspl"].map((f) => el("option", { value: f }, f.toUpperCase())));

  dialog({
    title: `Imprimir ${ativos.length} etiqueta(s)`,
    body: el("div", {},
      el("div", { class: "field" }, el("label", {}, "Dispositivo de impressão"), sel),
      el("div", { class: "form-grid" },
        el("div", { class: "field" }, el("label", {}, "Formato"), formato),
        el("div", { class: "field" }, el("label", {}, "Cópias"), partes),
      ),
      el("p", { class: "muted", style: "font-size:12.5px;margin:4px 0 0" },
        "Para imprimir em uma impressora comum, use “Baixar PDF” — o arquivo sai no tamanho exato da etiqueta."),
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Baixar PDF", variant: "outlined", onClick: async (close) => {
        try { await baixarEtiquetasPdf(ativos); close(); toast("PDF gerado"); }
        catch (e) { mostrarErro(e, "gerar o PDF das etiquetas"); }
      } },
      { label: "Imprimir", variant: "filled", onClick: async (close) => {
        close();
        try {
          const res = await api.post("/print/batch", {
            ativo_ids: ativos.map((a) => a.id),
            formato: formato.value,
            copies: Number(partes.value) || 1,
            dispositivo_id: Number(sel.value),
          });
          const erros = res.jobs.filter((j) => j.status === "error");
          if (erros.length) toast(`${erros.length} etiqueta(s) falharam: ${erros[0].detail || ""}`, "Tentar novamente", () => escolherDispositivo(ativos));
          else toast(`${res.jobs.length} etiqueta(s) enviada(s)`);
        } catch (e) { mostrarErro(e, "imprimir as etiquetas"); }
      } },
    ],
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
        // Emprestar tem fluxo próprio: precisa de chamado e data de devolução.
        if (sel.value === "emprestado") { close(); abrirEmprestimo(ativo); return; }
        try { await api.patch(`/ativos/${ativo.id}/status`, { status: sel.value }); close(); toast("Status atualizado"); refreshView(); }
        catch (e) { mostrarErro(e); }
      } },
    ],
  });
}

/**
 * Registra a saída por empréstimo.
 *
 * O número do chamado é obrigatório — é o registro de quem autorizou a saída —
 * e a devolução prevista alimenta o Calendário.
 */
async function abrirEmprestimo(ativo) {
  const hoje = new Date();
  const daqui = new Date(hoje.getTime() + 7 * 86400000);
  const comoData = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

  let usuarios = [];
  try { usuarios = (await api.get("/usuarios")).filter((u) => u.ativo !== false); } catch { usuarios = []; }

  const chamado = el("input", { placeholder: "Ex.: CH-2026-0042", autocomplete: "off" });
  const devolucao = el("input", { type: "date", value: comoData(daqui), min: comoData(hoje) });
  const paraSel = el("select", {},
    el("option", { value: "" }, "Não informado"),
    ...usuarios.map((u) => el("option", { value: u.id }, `${u.nome} — ${u.email}`)),
  );
  const obs = el("textarea", { placeholder: "Observações (opcional)", rows: "2" });

  const botao = el("button", {
    class: "btn filled",
    disabled: true,
    onclick: async () => {
      const texto = chamado.value.trim();
      if (!texto) { toast("Informe o número do chamado"); return; }
      if (!devolucao.value) { toast("Informe a data de devolução prevista"); return; }
      try {
        await api.post(`/ativos/${ativo.id}/emprestimo`, {
          numero_chamado: texto,
          devolucao_prevista: devolucao.value,
          usuario_id: paraSel.value ? Number(paraSel.value) : null,
          observacoes: obs.value || null,
        });
        fechar();
        toast(`Emprestado — chamado ${texto}`, "Ver calendário", () => { location.hash = "#/calendario"; });
        refreshView();
      } catch (e) { mostrarErro(e, "registrar o empréstimo"); }
    },
  }, "Registrar empréstimo");

  chamado.addEventListener("input", () => {
    botao.disabled = chamado.value.trim().length === 0 || !devolucao.value;
  });
  devolucao.addEventListener("change", () => {
    botao.disabled = chamado.value.trim().length === 0 || !devolucao.value;
  });

  const { close: fechar } = dialog({
    title: `Emprestar ${ativo.patrimonio}`,
    body: el("div", {},
      el("div", { class: "field" }, el("label", {}, "Número do chamado *"), chamado),
      el("div", { class: "field" }, el("label", {}, "Devolução prevista *"), devolucao),
      el("div", { class: "field" }, el("label", {}, "Emprestado para"), paraSel),
      el("div", { class: "field" }, el("label", {}, "Observações"), obs),
      el("p", { class: "muted", style: "font-size:12.5px;margin:6px 0 0" },
        "O empréstimo aparece no Calendário, com a data prevista de devolução."),
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { elemento: botao },
    ],
  });

  setTimeout(() => chamado.focus(), 50);
}

async function atribuir(ativo, lookups) {
  const sel = el("select", { html: optionsOf(lookups.usuarios, { label: "nome" }) });
  dialog({
    title: "Atribuir a colaborador",
    body: el("div", { class: "field" }, el("label", {}, "Colaborador"), sel),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Atribuir e gerar Termo", variant: "filled", onClick: async (close) => {
        if (!sel.value) { toast("Selecione um colaborador"); return; }
        try { await api.post(`/ativos/${ativo.id}/atribuir`, { usuario_id: Number(sel.value) }); close(); toast("Atribuído — Termo gerado"); refreshView(); }
        catch (e) { mostrarErro(e); }
      } },
    ],
  });
}

function openDetail(ativo, lookups) {
  const isTI = ativo.dominio === "ti";
  const ext = isTI ? ativo.ti : ativo.impressora;
  const locNome = lookups.localizacoes.find((l) => l.id === ativo.localizacao_id)?.nome;
  const info = [
    ["Inventário", ativo.dominio === "ti" ? "TI" : "Impressora"], ["Status", ativo.status],
    ["Modelo", ativo.modelo || "—"], ["Marca", ativo.marca || "—"],
    ["Nº de Série", ativo.numero_serie || "—"], ["Garantia", ativo.data_garantia ? fmtDate(ativo.data_garantia) : "—"],
    ["Valor", fmtMoney(ativo.valor)], ["Localização", locNome || "—"],
  ];
  if (ext) {
    for (const [k, v] of Object.entries(ext)) {
      if (k !== "ativo_id") info.push([k.replace(/_/g, " "), v === null || v === "" ? "—" : String(v)]);
    }
  }
  const rows = info.map(([k, v]) => el("div", { class: "row between", style: "border-bottom:1px solid var(--md-sys-color-outline-variant);padding:8px 0" },
    el("span", { class: "muted" }, k), el("span", {}, v)));

  dialog({
    title: `Patrimônio ${ativo.patrimonio}`,
    body: el("div", {},
      ativo.foto_id ? el("img", { class: "photo-preview mb", src: fotoUrl(ativo.foto_id), alt: "Foto do ativo" }) : null,
      el("div", { style: "margin:6px 0 10px", html: statusBadge(ativo.status) }),
      ...rows,
    ),
    actions: [
      { label: "Fechar", variant: "text" },
      ...(state.canWrite ? [
        { label: "QR", variant: "outlined", onClick: () => acaoQR(ativo) },
        { label: "Imprimir", variant: "outlined", onClick: () => escolherDispositivo([ativo]) },
        { label: "Status", variant: "outlined", onClick: () => alterarStatus(ativo) },
        { label: "Atribuir", variant: "outlined", onClick: () => atribuir(ativo, lookups) },
        { label: "Editar", variant: "tonal", onClick: () => openForm(ativo, lookups) },
      ] : []),
      ...(state.canDelete ? [{ label: "Excluir", variant: "danger", onClick: () => excluirAtivo(ativo) }] : []),
    ],
  });
}

/**
 * Exclui o ativo (exclusão lógica: sai das listas e dos relatórios).
 *
 * Exige permissão de exclusão — que o administrador libera por usuário em
 * Administração → Usuários & Permissões. A ação fica registrada na auditoria.
 */
async function excluirAtivo(ativo) {
  const confirmado = await confirmSheet(
    "Excluir ativo",
    `Excluir o patrimônio ${ativo.patrimonio}${ativo.modelo ? ` (${ativo.modelo})` : ""}? `
    + "Ele sai das listas e relatórios. O histórico permanece na auditoria.",
  );
  if (!confirmado) return;
  try {
    await api.del(`/ativos/${ativo.id}`);
    toast(`Ativo ${ativo.patrimonio} excluído`);
    refreshView();
  } catch (e) {
    mostrarErro(e, "excluir o ativo");
  }
}

// ---------------------------------------------------------------------------
// Seleção em lote (somente administrador)
// ---------------------------------------------------------------------------
// O administrador pode marcar vários ativos e excluir de uma vez. A seleção
// sobrevive à troca de página, para pegar itens de páginas diferentes.
let selecionados = new Set();
/** Quando true, a exclusão atinge TODOS os itens do filtro atual, não só os marcados. */
let selecionarTudoDoFiltro = false;

function limparSelecao() {
  selecionados = new Set();
  selecionarTudoDoFiltro = false;
}

/** Primeira confirmação: sim ou não. */
function confirmarExclusao(quantidade) {
  return confirmSheet(
    "Excluir ativos",
    `Excluir ${quantidade} ativo(s)? Eles saem das listas e dos relatórios; o histórico permanece na auditoria.`,
  );
}

/**
 * Segunda confirmação: exige digitar SIM (em maiúsculas).
 *
 * Segunda trava de propósito: exclusão em lote é irreversível pela tela, então
 * um clique errado não pode bastar.
 */
function confirmarDigitando(quantidade) {
  return new Promise((resolve) => {
    const campo = el("input", { placeholder: "SIM", autocomplete: "off" });
    dialog({
      title: "Confirmação final",
      body: el("div", {},
        el("p", { style: "margin-top:0;font-weight:600" },
          `Você realmente deseja deletar ${quantidade} itens?`),
        el("p", { class: "muted", style: "font-size:13px" },
          "Esta exclusão não pode ser desfeita pela tela. Digite "
          + "SIM em letras maiúsculas para confirmar."),
        el("div", { class: "field" }, campo),
        quantidade > 20
          ? el("p", { class: "muted", style: "font-size:12.5px" },
              "Como são mais de 20 itens, um backup do banco será gerado automaticamente antes da exclusão.")
          : null,
      ),
      actions: [
        { label: "Cancelar", variant: "text", onClick: (close) => { close(); resolve(false); } },
        { label: "Deletar", variant: "danger", onClick: (close) => {
          if (campo.value.trim() !== "SIM") {
            toast("Digite SIM em maiúsculas para confirmar");
            campo.focus();
            return; // mantém a janela aberta
          }
          close();
          resolve(true);
        } },
      ],
    });
    setTimeout(() => campo.focus(), 50);
  });
}

/** Executa a exclusão em lote, com as duas confirmações. */
async function excluirSelecionados(quantidade, refresh) {
  if (!await confirmarExclusao(quantidade)) return;
  if (!await confirmarDigitando(quantidade)) return;

  const corpo = selecionarTudoDoFiltro
    ? { todos_do_filtro: true, dominio: state.dominio, status: filtroStatus || null, search: filtroSearch || null }
    : { ids: [...selecionados] };

  try {
    const res = await api.post("/ativos/excluir-lote", corpo);
    limparSelecao();
    page = 1;
    toast(
      `${res.excluidos} ativo(s) excluído(s)`
      + (res.backup_gerado ? " — backup de segurança gerado" : ""),
    );
    refresh();
  } catch (e) {
    mostrarErro(e, "excluir os ativos selecionados");
  }
}

async function renderList(root, lookups) {
  root.innerHTML = "";
  const q = { dominio: state.dominio, page, size: pageSize };
  if (filtroStatus) q.status = filtroStatus;
  if (filtroSearch) q.search = filtroSearch;

  let data;
  try {
    data = await api.get("/ativos", q);
  } catch (e) { root.append(emptyState("ativos", "Erro", e.message)); return; }

  if (!data.items.length) { root.append(emptyState("ativos", "Nenhum ativo", "Cadastre o primeiro ativo deste inventário.")); return; }

  // Exclusão em lote é privilégio do administrador.
  const podeLote = state.isAdmin;
  const idsDaPagina = data.items.map((a) => a.id);

  // Guardamos cada linha e sua caixa para atualizar a seleção NO LUGAR.
  // Redesenhar a lista inteira a cada clique devolvia a rolagem ao topo,
  // obrigando a pessoa a descer tudo de novo para marcar o próximo item.
  const linhas = [];
  const hostBarra = el("div", { id: "ativos-selecao" });
  let linhaDestacada = null;

  function desenharBarra() {
    hostBarra.innerHTML = "";
    if (!podeLote) return;
    const totalSel = selecionarTudoDoFiltro ? data.total : selecionados.size;
    const paginaInteira = idsDaPagina.length > 0 && idsDaPagina.every((id) => selecionados.has(id));

    if (totalSel > 0) {
      hostBarra.append(el("div", { class: "selection-bar" },
        el("span", { class: "selection-count" }, `${totalSel} selecionado(s)`),
        selecionarTudoDoFiltro
          ? el("span", { class: "muted", style: "font-size:12.5px" }, `— todos os ${data.total} do filtro atual`)
          : null,
        el("span", { class: "spacer" }),
        el("button", { class: "btn text small", onclick: () => { limparSelecao(); atualizarSelecao(); } }, "Limpar seleção"),
        el("button", {
          class: "btn danger small",
          onclick: () => excluirSelecionados(totalSel, () => renderList(root, lookups)),
          html: icon("trash", 16) + " Excluir selecionados",
        }),
      ));
    }

    if (!selecionarTudoDoFiltro && paginaInteira && data.total > idsDaPagina.length) {
      hostBarra.append(el("div", { class: "selection-hint" },
        el("span", {}, `Os ${idsDaPagina.length} itens desta página estão marcados.`),
        el("button", {
          class: "btn text small",
          onclick: () => { selecionarTudoDoFiltro = true; atualizarSelecao(); },
        }, `Selecionar todos os ${data.total} do filtro`),
      ));
    }
  }

  /** Reflete a seleção na tela sem redesenhar a lista (mantém a rolagem). */
  function atualizarSelecao() {
    const marcados = idsDaPagina.filter((id) => selecionados.has(id)).length;
    if (caixaTodos) {
      caixaTodos.checked = marcados > 0 && marcados === idsDaPagina.length;
      caixaTodos.indeterminate = marcados > 0 && marcados < idsDaPagina.length;
    }
    linhas.forEach(({ tr, cx, id }) => {
      const marcado = selecionados.has(id);
      cx.checked = marcado;
      tr.classList.toggle("row-selected", marcado);
    });
    desenharBarra();
  }

  // Caixa do cabeçalho: marca/desmarca a página inteira. Fica "indeterminada"
  // quando só parte dos itens está marcada.
  let caixaTodos = null;
  if (podeLote) {
    caixaTodos = el("input", { type: "checkbox", title: "Selecionar todos desta página" });
    caixaTodos.addEventListener("change", () => {
      selecionarTudoDoFiltro = false;
      if (caixaTodos.checked) idsDaPagina.forEach((id) => selecionados.add(id));
      else idsDaPagina.forEach((id) => selecionados.delete(id));
      atualizarSelecao();
    });
  }

  const cabecalhos = podeLote ? ["", "", "Patrimônio", "Planta", "Modelo", "Status", "Localização", "Garantia", "Ações"]
                              : ["", "Patrimônio", "Planta", "Modelo", "Status", "Localização", "Garantia", "Ações"];

  const table = el("table", { class: "data" },
    el("thead", {}, el("tr", {}, ...cabecalhos.map((h, i) => {
      if (podeLote && i === 0) return el("th", { style: "width:36px" }, caixaTodos);
      return el("th", {}, h);
    }))),
    el("tbody", {}, ...data.items.map((a) => {
      const loc = lookups.localizacoes.find((l) => l.id === a.localizacao_id)?.nome;

      // A caixa é criada ANTES da linha e ligada a ela só depois. Referenciar
      // `tr` dentro da montagem lançaria "Cannot access 'tr' before
      // initialization" (a variável ainda está sendo atribuída) e a lista
      // inteira deixaria de renderizar.
      const caixaLinha = podeLote
        ? el("input", { type: "checkbox", onclick: (e) => e.stopPropagation() })
        : null;

      // Item vindo de um link de outra tela (relatório): fica marcado.
      const destacado = destaqueId !== null && a.id === destaqueId;

      const tr = el("tr", { class: destacado ? "row-destaque" : "" },
        ...(caixaLinha ? [el("td", { style: "padding-right:0" }, caixaLinha)] : []),        el("td", { style: "padding-right:0" }, a.foto_id
          ? el("img", { src: fotoUrl(a.foto_id), alt: "", style: "width:38px;height:38px;object-fit:cover;border-radius:8px;display:block" })
          : el("div", { style: "width:38px;height:38px;border-radius:8px;background:var(--md-sys-color-surface-container-high)" })),
        el("td", { style: "font-weight:600" }, a.patrimonio),
        el("td", {}, a.planta_sigla
          ? el("span", { class: "chip" }, a.planta_sigla)
          : el("span", { class: "muted" }, "—")),
        el("td", {}, a.modelo || "—"),
        el("td", { html: statusBadge(a.status) }),
        el("td", {}, loc || "—"),
        el("td", {}, a.data_garantia ? fmtDate(a.data_garantia) : "—"),
        el("td", { class: "actions" },
          ...(state.canWrite ? [
            el("button", { class: "iconbtn", title: "QR", onclick: (e) => { e.stopPropagation(); acaoQR(a); }, html: icon("qr") }),
            el("button", { class: "iconbtn", title: "Imprimir", onclick: (e) => { e.stopPropagation(); escolherDispositivo([a]); }, html: icon("print") }),
          ] : []),
          ...(state.canDelete ? [
            el("button", { class: "iconbtn danger", title: "Excluir", onclick: (e) => { e.stopPropagation(); excluirAtivo(a); }, html: icon("trash") }),
          ] : []),
        ),
      );
      // Só agora `tr` existe: dá para ligar a caixa e guardar a referência.
      if (caixaLinha) {
        caixaLinha.addEventListener("change", () => {
          selecionarTudoDoFiltro = false;
          if (caixaLinha.checked) selecionados.add(a.id); else selecionados.delete(a.id);
          atualizarSelecao();
        });
        linhas.push({ tr, cx: caixaLinha, id: a.id });
      }
      tr.addEventListener("click", () => openDetail(a, lookups));
      if (destacado) linhaDestacada = tr;
      return tr;
    })),
  );

  // Rola até o item destacado, para ele aparecer sem a pessoa procurar.
  if (linhaDestacada) {
    setTimeout(() => {
      linhaDestacada.scrollIntoView({ block: "center", behavior: "smooth" });
      // O destaque some depois de um tempo: é uma pista, não um estado.
      setTimeout(() => linhaDestacada.classList.remove("row-destaque"), 4000);
      destaqueId = null;
      linhaDestacada = null;
    }, 80);
  }

  // A barra reage à seleção sem redesenhar a lista.
  atualizarSelecao();

  root.append(
    hostBarra,
    el("div", { class: "table-wrap" }, table),
    el("div", { class: "pagination" },
      el("button", { class: "iconbtn", disabled: page <= 1, onclick: () => { page--; renderList(root, lookups); }, html: icon("chevL") }),
      el("span", {}, `Página ${data.page} de ${data.pages || 1} (${data.total} itens)`),
      el("button", { class: "iconbtn", disabled: page >= data.pages, onclick: () => { page++; renderList(root, lookups); }, html: icon("chevR") }),
    ),
  );
}

export async function renderAtivos(root) {
  ctx.setTitle("Ativos");
  ctx.setFab(null);

  // Vindo de um link (ex.: clique num item do relatório), aplica o filtro e o
  // destaque ANTES de montar a tela.
  aplicarDestaqueDaUrl();

  let lookups = null;
  let listRoot = null;
  function refresh() { if (listRoot && lookups) renderList(listRoot, lookups); }

  const statusFiltro = sessionStorage.getItem("filtro_status");
  if (statusFiltro) { filtroStatus = statusFiltro; sessionStorage.removeItem("filtro_status"); }

  const statuses = ["estoque", "em_uso", "manutencao", "reservado", "emprestado", "descartado"];

  // O `refresh()` redesenha apenas a LISTA — a barra de ferramentas é criada
  // uma vez só. Por isso os botões precisam ter o estado atualizado na mão,
  // senão o filtro funciona mas a marcação continua na opção anterior.
  const chipsStatus = [];
  const botoesTamanho = [];

  function atualizarToolbar() {
    chipsStatus.forEach(([valor, botao]) => botao.classList.toggle("selected", filtroStatus === valor));
    botoesTamanho.forEach(([valor, botao]) => botao.classList.toggle("selected", pageSize === valor));
  }

  /** Troca o filtro de status e sincroniza a marcação visual. */
  function trocarStatus(valor) {
    filtroStatus = valor;
    page = 1;
    atualizarToolbar();
    refresh();
  }

  // Seletor de itens por página. Ao trocar, volta para a primeira página para
  // não cair num número de página que não existe mais.
  const seletorTamanho = el("div", { class: "page-size", title: "Itens por página" },
    el("span", { class: "muted", style: "font-size:12.5px" }, "Itens:"),
    ...TAMANHOS_PAGINA.map((n) => {
      const botao = el("button", {
        class: "chip small" + (pageSize === n ? " selected" : ""),
        onclick: () => {
          if (pageSize === n) return;
          pageSize = n;
          page = 1;
          atualizarToolbar();
          refresh();
        },
      }, String(n));
      botoesTamanho.push([n, botao]);
      return botao;
    }),
  );

  const campoBusca = el("input", {
    class: "search-input",
    placeholder: "Buscar patrimônio, modelo, série…",
    value: filtroSearch,
    oninput: (e) => { filtroSearch = e.target.value; page = 1; refresh(); },
  });

  const chipTodos = el("button", {
    class: "chip" + (filtroStatus === "" ? " selected" : ""),
    onclick: () => trocarStatus(""),
  }, "Todos");
  chipsStatus.push(["", chipTodos]);

  const toolbar = el("div", { class: "toolbar" },
    el("div", { class: "grow" }, campoBusca),
    el("div", { class: "row", style: "gap:6px" },
      chipTodos,
      ...statuses.map((s) => {
        const botao = el("button", {
          class: "chip" + (filtroStatus === s ? " selected" : ""),
          onclick: () => trocarStatus(s),
        }, s.replace(/_/g, " "));
        chipsStatus.push([s, botao]);
        return botao;
      }),
    ),
    seletorTamanho,
  );

  atualizarToolbar();

  root.innerHTML = "";
  root.append(
    el("h1", { class: "page-title" }, `${state.dominioLabel} — Ativos`),
    toolbar,
    el("div", { id: "ativos-list" }, skeleton(6)),
  );

  listRoot = root.querySelector("#ativos-list");
  lookups = await loadLookups();
  ctx.setFab(state.canWrite ? { label: "Novo Ativo", icon: "add", onClick: () => openForm(null, lookups) } : null);
  await renderList(listRoot, lookups);
}
