/**
 * Helpers de UI Material 3: ícones SVG, criação de elementos, snackbar,
 * diálogos/bottom sheets, formatação e estados vazios.
 * @module ui
 */

import { dicaParaErro, rotuloCampo } from "./erros.js";

/** Conjunto de ícones em traço (24x24), sem dependências externas. */
const ICONS = {
  dashboard: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  ativos: '<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>',
  produtos: '<path d="M21 8l-9-5-9 5v8l9 5 9-5z"/><path d="M3 8l9 5 9-5"/><line x1="12" y1="13" x2="12" y2="21"/>',
  movimentacoes: '<path d="M7 16V4"/><path d="M3 8l4-4 4 4"/><path d="M17 8v12"/><path d="M21 16l-4 4-4-4"/>',
  manutencoes: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9L17 7M7 17l-2.1 2.1"/>',
  scanner: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 14h3v3h-3z"/><path d="M21 17h-3"/><path d="M14 21h7"/>',
  relatorios: '<line x1="4" y1="20" x2="20" y2="20"/><rect x="6" y="12" width="3" height="8" rx="1"/><rect x="11" y="8" width="3" height="12" rx="1"/><rect x="16" y="4" width="3" height="16" rx="1"/>',
  calendario: '<rect x="3" y="5" width="18" height="16" rx="2"/><line x1="3" y1="10" x2="21" y2="10"/><line x1="8" y1="3" x2="8" y2="7"/><line x1="16" y1="3" x2="16" y2="7"/><circle cx="8.5" cy="14.5" r="1"/><circle cx="12" cy="14.5" r="1"/><circle cx="15.5" cy="14.5" r="1"/>',
  reporte: '<path d="M12 3 2 20h20L12 3z"/><line x1="12" y1="9" x2="12" y2="14"/><circle cx="12" cy="17" r="1"/>',
  grip: '<circle cx=9 cy=6 r=1.4/><circle cx=15 cy=6 r=1.4/><circle cx=9 cy=12 r=1.4/><circle cx=15 cy=12 r=1.4/><circle cx=9 cy=18 r=1.4/><circle cx=15 cy=18 r=1.4/>',
  star: '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
  bell: '<path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
  cadastros: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.5 3-6 6.5-6s6.5 2.5 6.5 6"/><circle cx="17.5" cy="9" r="2.5"/><path d="M15.5 13.5c2.7 0 6 1.5 6 6"/>',
  logout: '<path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><path d="M16 17l5-5-5-5"/><line x1="21" y1="12" x2="9" y2="12"/>',
  menu: '<line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4"/>',
  moon: '<path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z"/>',
  refresh: '<path d="M21 12a9 9 0 11-3-6.7"/><path d="M21 3v6h-6"/>',
  search: '<circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.5" y2="16.5"/>',
  add: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z"/>',
  trash: '<path d="M3 6h18"/><path d="M8 6V4a1 1 0 011-1h6a1 1 0 011 1v2"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/>',
  print: '<path d="M6 9V3h12v6"/><rect x="4" y="9" width="16" height="8" rx="2"/><path d="M6 14h12v7H6z"/>',
  qr: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 14h3v3h-3z"/><path d="M21 17h-3"/><path d="M14 21h7"/>',
  close: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
  camera: '<path d="M3 8a2 2 0 012-2h2l2-2h6l2 2h2a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><circle cx="12" cy="12.5" r="3.5"/>',
  download: '<path d="M12 3v12"/><path d="M6 11l6 6 6-6"/><path d="M4 21h16"/>',
  check: '<path d="M20 6L9 17l-5-5"/>',
  chevL: '<path d="M15 18l-6-6 6-6"/>',
  chevR: '<path d="M9 18l6-6-6-6"/>',
  back: '<line x1="19" y1="12" x2="5" y2="12"/><path d="M12 19l-7-7 7-7"/>',
  doc: '<path d="M14 3H6a2 2 0 00-2 2v14a2 2 0 002 2h12a2 2 0 002-2V9z"/><path d="M14 3v6h6"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.5-7 8-7s8 3 8 7"/>',
  filter: '<path d="M4 5h16l-6 7v6l-4 2v-8z"/>',
  historico: '<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15.5 14"/>',
  plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
  contagens: '<path d="M9 4h6a1 1 0 011 1v1H8V5a1 1 0 011-1z"/><path d="M8 5H6a1 1 0 00-1 1v13a1 1 0 001 1h12a1 1 0 001-1V6a1 1 0 00-1-1h-2"/><path d="M9 13l2 2 4-4"/>',
  down: '<path d="M12 5v14"/><polyline points="5 12 12 19 19 12"/>',
  up: '<path d="M12 19V5"/><polyline points="19 12 12 5 5 12"/>',
  chevron: '<polyline points="6 9 12 15 18 9"/>',
  swap: '<path d="M7 16V4"/><path d="M3 8l4-4 4 4"/><path d="M17 8v12"/><path d="M21 16l-4 4-4-4"/>',
  counter: '<path d="M8 20h8"/><path d="M12 20v-4"/><circle cx="12" cy="9" r="6"/>',
  home: '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9L17 7M7 17l-2.1 2.1"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.8"/><path d="M3 17l5-5 4 4 3-3 6 6"/>',
  server: '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><line x1="7" y1="7.5" x2="7.01" y2="7.5"/><line x1="7" y1="16.5" x2="7.01" y2="16.5"/>',
  shield: '<path d="M12 3l8 3v6c0 5-3.4 8-8 9-4.6-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
};

export function icon(name, size = 22) {
  const inner = ICONS[name] || "";
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${inner}</svg>`;
}

/**
 * Converte strings vazias em `null`.
 *
 * Formulários HTML mandam `""` para campos não preenchidos. Em campos opcionais
 * tipados (e-mail, número, data), isso gera erro de validação no backend.
 * @param {Record<string, unknown>} obj
 */
export function semVazios(obj) {
  const saida = {};
  for (const [chave, valor] of Object.entries(obj || {})) {
    saida[chave] = valor === "" ? null : valor;
  }
  return saida;
}

/** Cria um elemento DOM com atributos e filhos. */export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    // Atributos BOOLEANOS (disabled, checked, required, selected, readonly…):
    // `setAttribute("disabled", false)` grava disabled="false" — e o HTML
    // considera o elemento desabilitado só pela PRESENÇA do atributo. Era por
    // isso que os botões de paginação dos Ativos nunca funcionavam.
    else if (v === false || v === undefined || v === null) node.removeAttribute(k);
    else if (v === true) node.setAttribute(k, "");
    else node.setAttribute(k, v);
  }
  for (const c of children) {
    if (c == null) continue;
    node.append(c.nodeType ? c : document.createTextNode(c));
  }
  return node;
}

/**
 * Mostra um erro de forma útil.
 *
 * Erro de validação (com campos) abre um **diálogo** com o campo e o motivo —
 * a snackbar some rápido demais e não cabia a lista. Os demais viram snackbar.
 * @param {any} erro - ApiError (pode ter `campos`)
 * @param {string} [contexto] - o que se estava tentando fazer ("salvar o ativo")
 */
export function mostrarErro(erro, contexto = "") {
  const campos = erro?.campos || [];
  const mensagem = erro?.message || String(erro || "Erro inesperado");

  if (!campos.length) {
    toast(contexto ? `${contexto}: ${mensagem}` : mensagem);
    return;
  }

  const dica = dicaParaErro(mensagem) || dicaParaErro(campos.map((c) => c.mensagem).join(" "));
  dialog({
    title: contexto ? `Não foi possível ${contexto}` : "Não foi possível concluir",
    body: el("div", {},
      el("p", { class: "muted", style: "margin-top:0" }, "O sistema recusou os dados abaixo:"),
      ...campos.map((c) => el("div", { class: "list-row" },
        el("div", { class: "list-main" },
          el("div", { class: "list-title" }, rotuloCampo(c.campo)),
          el("div", { class: "list-sub" }, c.mensagem),
        ),
      )),
      dica ? el("p", { style: "margin:14px 0 0;font-size:13px;color:var(--cor-aviso)" }, dica) : null,
      el("p", { class: "muted", style: "font-size:12px;margin:14px 0 0" },
        `Se o problema continuar, informe esta mensagem ao suporte${erro?.status ? ` (código ${erro.status})` : ""}.`),
    ),
    actions: [{ label: "Entendi", variant: "filled" }],
  });
}

let snackbarEl = null;
/**
 * Exibe uma Snackbar M3 com ação opcional (ex.: Repetir).
 *
 * Mensagens longas (erros de validação com vários campos) ficam mais tempo na
 * tela — antes elas sumiam antes de dar tempo de ler. Clicar dispensa.
 */
export function toast(message, actionLabel, actionFn, duration) {
  snackbarEl?.remove();
  const texto = String(message ?? "");
  snackbarEl = el("div", { class: "snackbar", role: "status" }, texto);
  if (actionLabel && actionFn) {
    const b = el("button", {}, actionLabel);
    b.addEventListener("click", (ev) => { ev.stopPropagation(); actionFn(); snackbarEl?.remove(); });
    snackbarEl.append(b);
  }
  const fechar = el("button", { class: "snackbar-close", title: "Fechar", "aria-label": "Fechar" }, "✕");
  fechar.addEventListener("click", () => snackbarEl?.remove());
  snackbarEl.append(fechar);
  snackbarEl.addEventListener("click", () => snackbarEl?.remove());
  document.body.append(snackbarEl);
  // Tempo proporcional ao tamanho: ~4s para textos curtos, até 14s nos longos.
  const tempo = duration ?? Math.min(14000, Math.max(4500, 3500 + texto.length * 90));
  setTimeout(() => snackbarEl?.remove(), tempo);
}

/** Abre um diálogo M3 (bottom sheet no mobile). */
export function dialog({ title, body, actions = [], wide = false }) {
  const overlay = el("div", { class: "overlay" });
  const actionsHtml = el("div", { class: "dialog-actions" });
  const dlg = el("div", { class: "dialog" + (wide ? " wide" : "") },
    el("h2", {}, title),
    el("div", { class: "dialog-body" }, body),
    actionsHtml,
  );
  overlay.append(dlg);
  document.body.append(overlay);

  const close = () => overlay.remove();
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
  for (const a of actions) {
    // `elemento` permite passar um botão já montado — usado quando o botão
    // precisa ficar desabilitado até o formulário ser preenchido.
    if (a.elemento) {
      actionsHtml.append(a.elemento);
      continue;
    }
    const btn = el("button", { class: "btn " + (a.variant || "text"), onclick: () => { a.onClick ? a.onClick(close) : close(); } }, a.label);
    actionsHtml.append(btn);
  }
  return { overlay, dlg, close };
}

/** Confirmação destrutiva via Bottom Sheet / Dialog. Retorna Promise<boolean>. */
export function confirmSheet(title, message, { confirmLabel = "Confirmar", danger = true } = {}) {
  return new Promise((resolve) => {
    let settled = false;
    const done = (v) => { if (!settled) { settled = true; resolve(v); } };
    dialog({
      title,
      body: el("p", { class: "muted" }, message),
      actions: [
        { label: "Cancelar", variant: "text", onClick: (c) => { c(); done(false); } },
        { label: confirmLabel, variant: danger ? "danger" : "filled", onClick: (c) => { c(); done(true); } },
      ],
    });
  });
}

/** Estado vazio padrão. */
export function emptyState(iconName, title, text) {
  return el("div", { class: "empty", html: `${icon(iconName, 72)}<h3>${title}</h3><p>${text || ""}</p>` });
}

/** Skeleton de carregamento. */
export function skeleton(rows = 5) {
  const wrap = el("div", { class: "card" });
  for (let i = 0; i < rows; i++) {
    wrap.append(el("div", { class: "skeleton", style: `height:18px;margin:10px 0;width:${90 - (i * 7)}%` }));
  }
  return wrap;
}

/** Formata data ISO. */
export function fmtDate(iso, withTime = false) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return "—";
  return d.toLocaleDateString("pt-BR", withTime ? { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" } : { day: "2-digit", month: "2-digit", year: "numeric" });
}

/** Formata valor monetário. */
export function fmtMoney(v) {
  if (v === null || v === undefined || v === "") return "—";
  return Number(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

/**
 * Versão CURTA do valor monetário, para caber nos gráficos.
 *
 * Com milhares de ativos, o total por categoria passa de milhões e o texto
 * completo ("R$ 12.345.678,90") escapava da caixa do gráfico. Aqui vira
 * "R$ 12,3 mi" — o número exato continua disponível no tooltip da barra.
 */
export function fmtMoneyCurto(v) {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v) || 0;
  const abs = Math.abs(n);
  const casas = (x) => x.toLocaleString("pt-BR", { maximumFractionDigits: 1 });
  if (abs >= 1e9) return `R$ ${casas(n / 1e9)} bi`;
  if (abs >= 1e6) return `R$ ${casas(n / 1e6)} mi`;
  if (abs >= 1e4) return `R$ ${casas(n / 1e3)} mil`;
  return fmtMoney(n);
}

const STATUS_LABEL = {
  estoque: "Em estoque", reservado: "Reservado", em_uso: "Em uso",
  manutencao: "Manutenção", descartado: "Descartado", emprestado: "Emprestado",
};

/** Badge de status de ativo. */
export function statusBadge(status) {
  return `<span class="badge ${status}"><span class="dot"></span>${STATUS_LABEL[status] || status}</span>`;
}
