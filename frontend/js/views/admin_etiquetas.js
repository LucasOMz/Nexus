/**
 * Administração → Etiquetas.
 * Template por dispositivo, presets de tamanho/DPI, pré-visualização ao vivo,
 * impressão de teste e geração de PDF para imprimir em outra impressora.
 * @module views/admin_etiquetas
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { el, icon, toast, dialog, confirmSheet, emptyState, mostrarErro } from "../ui.js";
import { renderLabelSVG, renderAvisos } from "../label.js";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// Presets de etiqueta comuns no mercado (mm).
const PRESETS = [
  { rotulo: "100 × 50 mm (padrão)", largura: 100, altura: 50 },
  { rotulo: "80 × 40 mm", largura: 80, altura: 40 },
  { rotulo: "60 × 40 mm", largura: 60, altura: 40 },
  { rotulo: "50 × 30 mm", largura: 50, altura: 30 },
  { rotulo: "40 × 25 mm", largura: 40, altura: 25 },
  { rotulo: "30 × 20 mm", largura: 30, altura: 20 },
];

let camposDisponiveis = [];

function configDoForm(form) {
  const fd = new FormData(form);
  const campos = camposDisponiveis.map((c) => c.chave).filter((k) => fd.get(`campo_${k}`));
  return {
    mostrar_qr: Boolean(fd.get("mostrar_qr")),
    qr_tamanho_mm: Number(fd.get("qr_tamanho_mm")) || 36,
    qr_ecc: fd.get("qr_ecc") || "M",
    qr_posicao: fd.get("qr_posicao") || "esquerda",
    alinhamento: fd.get("alinhamento") || "left",
    fonte_mm: Number(fd.get("fonte_mm")) || 4,
    fonte_escala_secundaria: Number(fd.get("fonte_escala")) || 0.62,
    espacamento_mm: Number(fd.get("espacamento_mm")) || 1.2,
    margem_mm: Number(fd.get("margem_mm")) || 3,
    prefixo_patrimonio: fd.get("prefixo_patrimonio") || "",
    titulo: fd.get("titulo") || "",
    rodape: fd.get("rodape") || "",
    mostrar_patrimonio: Boolean(fd.get("mostrar_patrimonio")),
    mostrar_patrimonio_negrito: Boolean(fd.get("mostrar_patrimonio_negrito")),
    borda: Boolean(fd.get("borda")),
    densidade: Number(fd.get("densidade")) || 0,
    velocidade: Number(fd.get("velocidade")) || 2,
    campos,
  };
}

async function atualizarPreview(form, painel, avisosBox, formatoEl) {
  const config = configDoForm(form);
  config.largura_mm = Number(form.querySelector('[name="largura_mm"]').value) || 100;
  config.altura_mm = Number(form.querySelector('[name="altura_mm"]').value) || 50;
  config.dpi = Number(form.querySelector('[name="dpi"]').value) || 203;
  try {
    const res = await api.post("/print/preview", { config, formato: formatoEl.value });
    painel.innerHTML = renderLabelSVG(res.layout);
    avisosBox.innerHTML = renderAvisos(res.layout);
  } catch (e) {
    painel.innerHTML = `<p class="muted">${esc(e.message)}</p>`;
    avisosBox.innerHTML = "";
  }
}

function abrirTemplate(template) {
  const t = template || { nome: "", largura_mm: 100, altura_mm: 50, dpi: 203, padrao: false, config: {} };
  const cfg = t.config || {};
  const camposMarcados = cfg.campos || ["modelo", "serie"];

  const form = el("form", {}, );
  form.innerHTML = `
    <div class="form-grid">
      <div class="field"><label>Nome do template *</label><input name="nome" required value="${esc(t.nome)}" placeholder="Ex.: Etiqueta Zebra 100x50"></div>
      <div class="field"><label>Preset de tamanho</label>
        <select name="preset">
          <option value="">Personalizado…</option>
          ${PRESETS.map((p) => `<option value="${p.largura}x${p.altura}">${p.rotulo}</option>`).join("")}
        </select>
      </div>
      <div class="field"><label>Largura (mm)</label><input type="number" step="0.1" name="largura_mm" value="${t.largura_mm}"></div>
      <div class="field"><label>Altura (mm)</label><input type="number" step="0.1" name="altura_mm" value="${t.altura_mm}"></div>
      <div class="field"><label>DPI da impressora</label>
        <select name="dpi">
          <option value="203" ${t.dpi === 203 ? "selected" : ""}>203 dpi (8 dots/mm)</option>
          <option value="300" ${t.dpi === 300 ? "selected" : ""}>300 dpi (11,8 dots/mm)</option>
          <option value="600" ${t.dpi === 600 ? "selected" : ""}>600 dpi</option>
        </select>
        <span class="hint">Se a etiqueta sai pequena/grande demais, o DPI está errado.</span>
      </div>
      <div class="field"><label>Inventário</label>
        <select name="dominio">
          <option value="">Ambos</option>
          <option value="ti" ${t.dominio === "ti" ? "selected" : ""}>TI</option>
          <option value="impressora" ${t.dominio === "impressora" ? "selected" : ""}>Impressoras</option>
        </select>
      </div>
    </div>

    <div class="form-section"><h4>QR Code</h4>
      <div class="form-grid">
        <div class="field"><label class="switch"><input type="checkbox" name="mostrar_qr" ${cfg.mostrar_qr !== false ? "checked" : ""}> Exibir QR Code</label></div>
        <div class="field"><label>Posição</label>
          <select name="qr_posicao"><option value="esquerda" ${cfg.qr_posicao !== "direita" ? "selected" : ""}>Esquerda</option><option value="direita" ${cfg.qr_posicao === "direita" ? "selected" : ""}>Direita</option></select></div>
        <div class="field"><label>Tamanho do QR (mm)</label><input type="number" step="1" name="qr_tamanho_mm" value="${cfg.qr_tamanho_mm ?? 36}"></div>
        <div class="field"><label>Correção de erro</label>
          <select name="qr_ecc">${["L", "M", "Q", "H"].map((n) => `<option ${(cfg.qr_ecc || "M") === n ? "selected" : ""}>${n}</option>`).join("")}</select>
          <span class="hint">Maior = mais resistente a sujeira, porém QR maior.</span></div>
      </div>
    </div>

    <div class="form-section"><h4>Texto</h4>
      <div class="form-grid">
        <div class="field"><label>Título (linha fixa no topo)</label><input name="titulo" value="${esc(cfg.titulo)}" placeholder="Ex.: PREFEITURA MUNICIPAL"></div>
        <div class="field"><label>Rodapé (linha fixa)</label><input name="rodape" value="${esc(cfg.rodape)}"></div>
        <div class="field"><label>Prefixo do patrimônio</label><input name="prefixo_patrimonio" value="${esc(cfg.prefixo_patrimonio)}" placeholder="Ex.: PATRIMÔNIO: "></div>
        <div class="field"><label>Alinhamento</label>
          <select name="alinhamento">
            <option value="left" ${(cfg.alinhamento || "left") === "left" ? "selected" : ""}>Esquerda</option>
            <option value="center" ${cfg.alinhamento === "center" ? "selected" : ""}>Centralizado</option>
            <option value="right" ${cfg.alinhamento === "right" ? "selected" : ""}>Direita</option>
          </select></div>
        <div class="field"><label>Tamanho da fonte principal (mm)</label><input type="number" step="0.2" name="fonte_mm" value="${cfg.fonte_mm ?? 4}"></div>
        <div class="field"><label>Fonte secundária (fator)</label><input type="number" step="0.05" name="fonte_escala" value="${cfg.fonte_escala_secundaria ?? 0.62}"></div>
        <div class="field"><label>Margem (mm)</label><input type="number" step="0.5" name="margem_mm" value="${cfg.margem_mm ?? 3}"></div>
        <div class="field"><label>Espaçamento entre linhas (mm)</label><input type="number" step="0.2" name="espacamento_mm" value="${cfg.espacamento_mm ?? 1.2}"></div>
        <div class="field"><label class="switch"><input type="checkbox" name="mostrar_patrimonio" ${cfg.mostrar_patrimonio !== false ? "checked" : ""}> Exibir patrimônio</label></div>
        <div class="field"><label class="switch"><input type="checkbox" name="mostrar_patrimonio_negrito" ${cfg.mostrar_patrimonio_negrito !== false ? "checked" : ""}> Patrimônio em negrito</label></div>
        <div class="field"><label class="switch"><input type="checkbox" name="borda" ${cfg.borda ? "checked" : ""}> Moldura</label></div>
      </div>
      <h4 style="margin-top:14px">Campos exibidos</h4>
      <div class="perm-grid">
        ${camposDisponiveis.map((c) => `
          <label class="perm-item ${camposMarcados.includes(c.chave) ? "checked" : ""}">
            <input type="checkbox" name="campo_${c.chave}" ${camposMarcados.includes(c.chave) ? "checked" : ""}>
            <span>${esc(c.rotulo)}</span>
          </label>`).join("")}
      </div>
    </div>

    <div class="form-section"><h4>Impressora</h4>
      <div class="form-grid">
        <div class="field"><label>Densidade (ZPL ^MD)</label><input type="number" name="densidade" value="${cfg.densidade ?? 0}"></div>
        <div class="field"><label>Velocidade (ZPL ^PR)</label><input type="number" name="velocidade" value="${cfg.velocidade ?? 2}"></div>
      </div>
    </div>

    <div class="form-section"><h4>Padrão</h4>
      <label class="switch"><input type="checkbox" name="padrao" ${t.padrao ? "checked" : ""}> Usar como template padrão do sistema</label>
    </div>`;

  // Painel de pré-visualização ao vivo.
  const painel = el("div", { style: "position:sticky;top:10px" });
  const avisosBox = el("div");
  const formatoEl = el("select", {}, ...[["zpl", "ZPL (Zebra)"], ["tspl", "TSPL (TSC/Elgin)"], ["pdf", "PDF"]].map(([v, r]) => el("option", { value: v }, r)));

  const corpo = el("div", { style: "display:grid;grid-template-columns:minmax(0,1.15fr) minmax(240px,.85fr);gap:24px" },
    el("div", {}, form),
    el("div", {},
      el("div", { class: "row between", style: "margin-bottom:8px" },
        el("strong", {}, "Pré-visualização"),
        el("div", { class: "row", style: "gap:6px" }, el("span", { class: "muted", style: "font-size:12px" }, "Formato:"), formatoEl),
      ),
      painel,
      avisosBox,
      el("div", { class: "row", style: "margin-top:14px;gap:8px" },
        el("button", { class: "btn outlined small", type: "button", onclick: () => baixarPdf(form), html: icon("download", 18) + " Baixar PDF" }),
        el("button", { class: "btn tonal small", type: "button", onclick: () => imprimirTeste(form), html: icon("print", 18) + " Imprimir teste" }),
      ),
      el("p", { class: "muted", style: "font-size:12px;margin-top:10px" }, "O PDF é gerado no tamanho exato da etiqueta — dá para imprimir em qualquer impressora, inclusive de escritório."),
    ),
  );

  // Eventos: qualquer mudança recalcula a pré-visualização.
  let timer = null;
  const agendar = () => {
    painel.querySelectorAll(".perm-item input").forEach((i) => i.closest(".perm-item").classList.toggle("checked", i.checked));
    clearTimeout(timer);
    timer = setTimeout(() => atualizarPreview(form, painel, avisosBox, formatoEl), 220);
  };
  form.addEventListener("input", agendar);
  form.addEventListener("change", (ev) => {
    if (ev.target.name === "preset" && ev.target.value) {
      const [largura, altura] = ev.target.value.split("x");
      form.querySelector('[name="largura_mm"]').value = largura;
      form.querySelector('[name="altura_mm"]').value = altura;
    }
    agendar();
  });
  formatoEl.addEventListener("change", agendar);

  async function montarPayload(formato) {
    const config = configDoForm(form);
    config.largura_mm = Number(form.querySelector('[name="largura_mm"]').value) || 100;
    config.altura_mm = Number(form.querySelector('[name="altura_mm"]').value) || 50;
    config.dpi = Number(form.querySelector('[name="dpi"]').value) || 203;
    return { config, formato };
  }

  async function baixarPdf(form) {
    const { config } = await montarPayload("pdf");
    try {
      const res = await fetch("/api/v1/print/preview/pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: "Bearer " + state.access },
        body: JSON.stringify({ config, formato: "pdf" }),
      });
      if (!res.ok) throw new Error("Falha ao gerar o PDF");
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "etiqueta.pdf";
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    } catch (e) { mostrarErro(e); }
  }

  async function imprimirTeste(form) {
    const disp = await api.get("/print/dispositivos").catch(() => []);
    if (!disp.length) { toast("Cadastre um dispositivo em Administração → Impressão"); return; }
    const sel = el("select", {}, ...disp.map((d) => el("option", { value: d.id, ...(d.padrao ? { selected: "" } : {}) }, `${d.nome}${d.padrao ? " (padrão)" : ""}`)));
    dialog({
      title: "Imprimir etiqueta de teste",
      body: el("div", {},
        el("p", { class: "muted" }, "Serão usados dados de exemplo (TIAT0001)."),
        el("div", { class: "field" }, el("label", {}, "Dispositivo"), sel),
      ),
      actions: [
        { label: "Cancelar", variant: "text" },
        { label: "Imprimir", variant: "filled", onClick: async (close) => {
          try {
            // Salva o template antes de testar, para o teste usar o que está na tela.
            await salvar(form, true);
            const r = await api.post(`/print/teste?dispositivo_id=${sel.value}`, undefined);
            const job = r.jobs?.[0] || {};
            toast(job.status === "error" ? (job.detail || "Falha ao imprimir") : "Etiqueta de teste enviada");
            close();
          } catch (e) { mostrarErro(e); }
        } },
      ],
    });
  }

  async function salvar(form, silencioso = false) {
    const fd = new FormData(form);
    const payload = {
      nome: fd.get("nome"),
      descricao: null,
      largura_mm: Number(fd.get("largura_mm")) || 100,
      altura_mm: Number(fd.get("altura_mm")) || 50,
      dpi: Number(fd.get("dpi")) || 203,
      dominio: fd.get("dominio") || null,
      padrao: Boolean(fd.get("padrao")),
      config: configDoForm(form),
    };
    payload.config.largura_mm = payload.largura_mm;
    payload.config.altura_mm = payload.altura_mm;
    payload.config.dpi = payload.dpi;
    if (!payload.nome) throw new Error("Informe o nome do template");
    if (t.id) await api.put(`/admin/etiquetas/${t.id}`, payload);
    else {
      const criado = await api.post("/admin/etiquetas", payload);
      t.id = criado.id;
    }
    if (!silencioso) toast("Template salvo");
  }

  const dlg = dialog({
    title: template ? `Editar etiqueta: ${template.nome}` : "Nova etiqueta",
    body: corpo,
    wide: true,
    actions: [
      { label: "Fechar", variant: "text" },
      { label: "Salvar", variant: "filled", onClick: async (close) => {
        try { await salvar(form); close(); renderTemplates(document.getElementById("view")); }
        catch (e) { mostrarErro(e); }
      } },
    ],
  });
  dlg.dlg.style.maxWidth = "1100px";
  agendar();
}

// ---------------------------------------------------------------------------
// Lista de templates
// ---------------------------------------------------------------------------
export async function renderTemplates(root) {
  camposDisponiveis = (await api.get("/admin/etiquetas/campos").catch(() => ({ campos: [] }))).campos || [];
  const templates = await api.get("/admin/etiquetas").catch(() => []);

  root.innerHTML = "";
  root.append(el("div", { class: "card" },
    el("div", { class: "row between" },
      el("div", {},
        el("div", { class: "section-title", style: "margin:0" }, "Templates de etiqueta"),
        el("div", { class: "muted", style: "font-size:13px" }, "Defina o tamanho, o DPI e o que aparece em cada etiqueta. Pode haver um template por impressora."),
      ),
      el("button", { class: "btn tonal small", onclick: () => abrirTemplate(null), html: icon("add", 18) + " Novo template" }),
    ),
  ));

  const lista = el("div", { class: "card" });
  if (!templates.length) {
    lista.append(emptyState("qr", "Nenhum template", "Crie o primeiro template de etiqueta para configurar a impressão."));
  }
  templates.forEach((t) => {
    lista.append(el("div", { class: "list-row" },
      el("div", { class: "list-main" },
        el("div", { class: "list-title" }, `${t.nome}${t.padrao ? " · padrão" : ""}`),
        el("div", { class: "list-sub" }, `${t.largura_mm} × ${t.altura_mm} mm · ${t.dpi} dpi${t.dominio ? ` · ${t.dominio}` : ""}`),
      ),
      el("div", { class: "row" },
        el("button", { class: "iconbtn", title: "Editar", onclick: () => abrirTemplate(t), html: icon("edit", 20) }),
        el("button", { class: "iconbtn", title: "Excluir", onclick: async () => {
          if (await confirmSheet("Excluir template", `Excluir "${t.nome}"?`)) {
            try { await api.del(`/admin/etiquetas/${t.id}`); toast("Excluído"); renderTemplates(document.getElementById("view")); }
            catch (e) { mostrarErro(e); }
          }
        }, html: icon("trash", 20) }),
      ),
    ));
  });
  root.append(lista);
}
