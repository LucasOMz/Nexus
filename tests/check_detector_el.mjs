// Confere se o detector de concatenacao ainda pega o bug original.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const BUG = [
  'el("div", { class: "muted" },',
  "  `${r.usuario_nome}`",
  "  + ` · ${fmtDate(r.criado_em, true)}`)",
  '+ (r.tela ? ` · tela: ${r.tela}` : ""),',
].join("\n");

const OK = [
  'el("div", { class: "muted" },',
  "  `${a}`",
  "  + ` · ${b}`",
  "  + (t.motivo ? ` (${t.motivo})` : \"\")",
  "  + ` · fim`),",
].join("\n");

function detectar(src) {
  const linhas = src.split("\n");
  let profundidade = 0;
  const achados = [];
  for (let i = 0; i < linhas.length - 1; i++) {
    const a = linhas[i].trimEnd();
    const b = linhas[i + 1].trimStart();
    profundidade += (linhas[i].match(/\(/g) || []).length - (linhas[i].match(/\)/g) || []).length;
    if (a.endsWith(")") && b.startsWith("+") && profundidade === 0) {
      achados.push(i + 1);
    }
  }
  return achados;
}

const noBug = detectar(BUG);
const noOk = detectar(OK);

console.log("  padrao COM bug  -> detectado:", noBug.length > 0 ? `sim (linha ${noBug[0]})` : "NAO");
console.log("  padrao CORRETO  -> detectado:", noOk.length > 0 ? `sim (linha ${noOk[0]}) FALSO POSITIVO` : "nao");

if (noBug.length === 0 || noOk.length > 0) {
  console.log("\nDETECTOR INUTIL - corrija a verificacao");
  process.exit(1);
}
console.log("\nDetector OK: pega o bug e nao acusa o codigo correto");
