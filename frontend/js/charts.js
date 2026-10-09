/**
 * Gráficos em SVG puro — sem bibliotecas externas (offline-first).
 * Todos retornam uma string de SVG pronta para injetar no DOM.
 * @module charts
 */

/** Paleta para séries categóricas (aquecida, coerente com o tema vermelho). */
export const PALETA = [
  "var(--md-sys-color-primary)",
  "#D97742",
  "var(--inv-accent)",
  "#A0763C",
  "#B58B84",
  "#7D6E6B",
  "#C9A227",
  "var(--cor-saida)",
];

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function vazio() {
  return '<p class="chart-empty">Sem dados para exibir</p>';
}

function limpar(data) {
  return (data || []).filter((d) => d && Number(d.valor) > 0);
}

/**
 * Gráfico de rosca (donut) — ideal para "ativos por status".
 * @param {Array<{rotulo:string,valor:number}>} data
 */
export function donut(data, { size = 190, campo = "" } = {}) {
  const items = limpar(data);
  const total = items.reduce((s, d) => s + Number(d.valor), 0);
  if (!total) return vazio();

  const C = 2 * Math.PI * 40;
  let offset = 0;
  const arcos = items
    .map((d, i) => {
      const len = (Number(d.valor) / total) * C;
      const seg = `<g class="drill" data-drill="${esc(campo)}" data-rotulo="${esc(d.rotulo)}">`
        + `<title>${esc(d.rotulo)}: ${d.valor} — clique para ver a lista</title>`
        + `<circle cx="50" cy="50" r="40" fill="none" stroke="${PALETA[i % PALETA.length]}"
        stroke-width="15" stroke-dasharray="${len.toFixed(2)} ${(C - len).toFixed(2)}"
        stroke-dashoffset="${(-offset).toFixed(2)}" transform="rotate(-90 50 50)" /></g>`;
      offset += len;
      return seg;
    })
    .join("");

  const legenda = items
    .map((d, i) => `<span class="drill" data-drill="${esc(campo)}" data-rotulo="${esc(d.rotulo)}">`
      + `<i style="background:${PALETA[i % PALETA.length]}"></i>${esc(d.rotulo)} · <b>${d.valor}</b></span>`)
    .join("");

  return `
    <div style="display:flex;flex-wrap:wrap;gap:18px;align-items:center">
      <svg viewBox="0 0 100 100" style="width:${size}px;max-width:45%;flex:0 0 auto">
        ${arcos}
        <text x="50" y="47" text-anchor="middle" class="chart-value" style="font-size:15px">${total}</text>
        <text x="50" y="60" text-anchor="middle" class="chart-label">total</text>
      </svg>
      <div class="chart-legend" style="flex-direction:column;gap:7px;margin:0">${legenda}</div>
    </div>`;
}

/**
 * Barras horizontais — ideal para rankings (categorias, localizações).
 */
export function barsH(data, { max, sufixo = "", campo = "" } = {}) {
  const items = limpar(data).slice(0, 9);
  if (!items.length) return vazio();

  const maxV = max || Math.max(...items.map((d) => Number(d.valor)), 1);

  // A largura do gráfico é CALCULADA a partir do maior texto de valor.
  //
  // Antes era fixa em 300, com a barra terminando em 280 e o valor começando em
  // 286 — sobravam 14 unidades. Com valores grandes ("R$ 12.345.678,90") o
  // número escapava da caixa. Agora o desenho cresce o quanto for preciso; como
  // o SVG tem viewBox, ele se ajusta ao espaço do cartão sem cortar nada.
  const LARGURA_ROTULO = 110;
  const LARGURA_BARRA = 150;
  const ESPACO = 8;
  const textos = items.map((d) => String(d.texto !== undefined ? d.texto : d.valor) + sufixo);
  const maiorTexto = Math.max(...textos.map((t) => t.length));
  const larguraValor = Math.min(Math.max(maiorTexto * 6.4, 24), 190);

  const xBarra = LARGURA_ROTULO + 6;
  const xValor = xBarra + LARGURA_BARRA + ESPACO;
  const largura = Math.round(xValor + larguraValor + 4);
  const altura = items.length * 32 + 8;

  const linhas = items
    .map((d, i) => {
      const w = Math.max(3, (Number(d.valor) / maxV) * LARGURA_BARRA);
      const y = i * 32 + 4;
      const texto = `${d.texto !== undefined ? d.texto : d.valor}${sufixo}`;
      // O título guarda o valor COMPLETO: a barra mostra a versão curta.
      const completo = d.completo !== undefined ? d.completo : texto;
      return `<g class="drill" data-drill="${esc(campo)}" data-rotulo="${esc(d.rotulo)}">`
        + `<title>${esc(d.rotulo)}: ${esc(completo)} — clique para ver a lista</title>`
        + `<rect x="0" y="${y}" width="${largura}" height="28" fill="transparent"/>`
        + `<text x="0" y="${y + 15}" class="chart-label">${esc(String(d.rotulo).slice(0, 22))}</text>
        <rect x="${xBarra}" y="${y + 4}" width="${LARGURA_BARRA}" height="14" rx="7" fill="var(--md-sys-color-surface-container-high)"/>
        <rect x="${xBarra}" y="${y + 4}" width="${w.toFixed(1)}" height="14" rx="7" fill="${PALETA[i % PALETA.length]}"/>
        <text x="${xValor}" y="${y + 15}" class="chart-value">${esc(texto)}</text></g>`;
    })
    .join("");

  return `<svg viewBox="0 0 ${largura} ${altura}" style="min-width:280px">${linhas}</svg>`;
}

/**
 * Barras verticais — ideal para valores por faixa (garantias 30/60/90).
 */
export function barsV(data, { sufixo = "", campo = "" } = {}) {
  const items = (data || []).filter(Boolean);
  if (!items.length) return vazio();
  const maxV = Math.max(...items.map((d) => Number(d.valor) || 0), 1);
  const base = 110;
  const largura = 260 / items.length;
  const barras = items
    .map((d, i) => {
      const h = ((Number(d.valor) || 0) / maxV) * 80;
      const x = i * largura + largura * 0.22;
      const w = largura * 0.56;
      return `<g class="drill" data-drill="${esc(campo)}" data-rotulo="${esc(d.rotulo)}">`
        + `<title>${esc(d.rotulo)}: ${d.valor} — clique para ver a lista</title>`
        + `<rect x="${(i * largura).toFixed(1)}" y="0" width="${largura.toFixed(1)}" height="130" fill="transparent"/>`
        + `<rect x="${x.toFixed(1)}" y="${(base - h).toFixed(1)}" width="${w.toFixed(1)}" height="${Math.max(h, 2).toFixed(1)}" rx="6" fill="${PALETA[i % PALETA.length]}"/>
        <text x="${(x + w / 2).toFixed(1)}" y="${(base - h - 6).toFixed(1)}" text-anchor="middle" class="chart-value">${d.texto !== undefined ? d.texto : d.valor}${sufixo}</text>
        <text x="${(x + w / 2).toFixed(1)}" y="${base + 16}" text-anchor="middle" class="chart-label">${esc(d.rotulo)}</text></g>`;
    })
    .join("");
  return `<svg viewBox="0 0 260 132" style="min-width:240px">${barras}</svg>`;
}

/**
 * Linha/área dupla — movimentações por mês (entradas x saídas).
 */
export function linhaMensal(data) {
  const items = (data || []).filter(Boolean);
  if (!items.length) return vazio();

  const W = 320;
  const H = 150;
  const padL = 26;
  const padB = 26;
  const maxV = Math.max(1, ...items.flatMap((d) => [Number(d.entradas) || 0, Number(d.saidas) || 0]));
  const passo = items.length > 1 ? (W - padL - 10) / (items.length - 1) : 0;
  const px = (i) => padL + i * passo;
  const py = (v) => H - padB - ((Number(v) || 0) / maxV) * (H - padB - 16);

  const caminho = (chave) => items.map((d, i) => `${i === 0 ? "M" : "L"}${px(i).toFixed(1)},${py(d[chave]).toFixed(1)}`).join(" ");
  const pontos = (chave) => items.map((d, i) => `<circle cx="${px(i).toFixed(1)}" cy="${py(d[chave]).toFixed(1)}" r="3.5" fill="${chave === "entradas" ? "var(--md-sys-color-primary)" : "var(--cor-saida)"}"/>`).join("");
  const rotulos = items.map((d, i) => `<text x="${px(i).toFixed(1)}" y="${H - 8}" text-anchor="middle" class="chart-label">${esc(String(d.rotulo).slice(2))}</text>`).join("");
  const grade = [0, 0.5, 1].map((f) => `<line x1="${padL}" y1="${py(maxV * f).toFixed(1)}" x2="${W - 8}" y2="${py(maxV * f).toFixed(1)}" stroke="var(--md-sys-color-outline-variant)" stroke-width="1" stroke-dasharray="3 4"/>`).join("");

  return `
    <svg viewBox="0 0 ${W} ${H}" style="min-width:300px">
      ${grade}
      <path d="${caminho("entradas")}" fill="none" stroke="var(--md-sys-color-primary)" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="${caminho("saidas")}" fill="none" stroke="var(--cor-saida)" stroke-width="2.5" stroke-linejoin="round" stroke-dasharray="5 4"/>
      ${pontos("entradas")}${pontos("saidas")}
      ${rotulos}
    </svg>
    <div class="chart-legend">
      <span><i style="background:var(--md-sys-color-primary)"></i>Entradas</span>
      <span><i style="background:var(--cor-saida)"></i>Saídas</span>
    </div>`;
}
