/**
 * Renderiza a geometria da etiqueta (vinda do backend) como SVG.
 *
 * Como a geometria é a MESMA usada para gerar ZPL/TSPL/PDF, a pré-visualização
 * corresponde ao que sai na impressora — inclusive os avisos de texto que não cabe.
 * @module label
 */

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/**
 * Desenha a etiqueta em SVG, em escala (1 unidade do viewBox = 1 mm).
 * @param {{largura_mm:number, altura_mm:number, elementos:Array}} layout
 * @returns {string} SVG
 */
export function renderLabelSVG(layout) {
  if (!layout || !layout.elementos) return "";
  const largura = layout.largura_mm || 100;
  const altura = layout.altura_mm || 50;
  const partes = [];

  for (const el of layout.elementos) {
    if (el.tipo === "qr") {
      if (el.qr_data_url) {
        partes.push(`<image x="${el.x_mm}" y="${el.y_mm}" width="${el.tamanho_mm}" height="${el.tamanho_mm}" href="${el.qr_data_url}" preserveAspectRatio="none"/>`);
      } else {
        partes.push(
          `<rect x="${el.x_mm}" y="${el.y_mm}" width="${el.tamanho_mm}" height="${el.tamanho_mm}" fill="#eee" stroke="#999" stroke-width="0.3"/>`,
          `<text x="${el.x_mm + el.tamanho_mm / 2}" y="${el.y_mm + el.tamanho_mm / 2}" text-anchor="middle" font-size="${el.tamanho_mm / 5}" fill="#666" font-family="Arial">QR</text>`,
        );
      }
      partes.push(`<text x="${el.x_mm + el.tamanho_mm / 2}" y="${el.y_mm + el.tamanho_mm + 2.4}" text-anchor="middle" font-size="1.8" fill="#999" font-family="Arial">${el.ecc || "M"}</text>`);
    } else if (el.tipo === "texto") {
      const fonte = (el.altura_mm || 3) * 0.92;
      partes.push(
        `<text x="${el.x_mm}" y="${(el.y_mm + (el.altura_mm || 3) * 0.82).toFixed(2)}" font-size="${fonte.toFixed(2)}"` +
        ` font-weight="${el.negrito ? 700 : 400}" fill="#000" font-family="Helvetica, Arial, sans-serif">${esc(el.texto)}</text>`,
      );
    } else if (el.tipo === "borda") {
      partes.push(`<rect x="${el.x_mm}" y="${el.y_mm}" width="${el.largura_mm}" height="${el.altura_mm}" fill="none" stroke="#000" stroke-width="0.4"/>`);
    }
  }

  return (
    `<svg viewBox="0 0 ${largura} ${altura}" xmlns="http://www.w3.org/2000/svg" ` +
    `style="width:100%;height:auto;background:#fff;border-radius:8px;border:1px solid #ccc;display:block">` +
    partes.join("") +
    "</svg>"
  );
}

/** Lista de avisos da pré-visualização (texto que não cabe, QR pequeno...). */
export function renderAvisos(layout) {
  const avisos = (layout && layout.avisos) || [];
  if (!avisos.length) return "";
  return `<ul style="margin:10px 0 0;padding-left:18px;color:var(--cor-aviso);font-size:13px">${avisos.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>`;
}

/** Rótulos das opções (usados nos formulários da tela de Etiquetas). */
export const POSICOES_QR = [
  { valor: "esquerda", rotulo: "QR à esquerda" },
  { valor: "direita", rotulo: "QR à direita" },
];

export const ALINHAMENTOS = [
  { valor: "left", rotulo: "Esquerda" },
  { valor: "center", rotulo: "Centralizado" },
  { valor: "right", rotulo: "Direita" },
];
