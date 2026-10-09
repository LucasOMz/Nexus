/**
 * Cache de entidades de cadastro (lookups) usadas nos formulários.
 * @module lookups
 */
import { api } from "./api.js";

let cache = null;

export async function loadLookups(force = false) {
  if (cache && !force) return cache;
  const [departamentos, localizacoes, fornecedores, categorias, usuarios, plantas] = await Promise.all([
    api.get("/departamentos"),
    api.get("/localizacoes"),
    api.get("/fornecedores"),
    api.get("/categorias"),
    api.get("/usuarios"),
    // Só o administrador enxerga o cadastro de plantas; para os demais a lista
    // vem vazia e o campo simplesmente não aparece com opções.
    api.get("/admin/plantas").catch(() => []),
  ]);
  cache = { departamentos, localizacoes, fornecedores, categorias, usuarios, plantas };
  return cache;
}

export function optionsOf(list, { placeholder = "Selecione…", value = "id", label = "nome" } = {}) {
  let html = `<option value="">${placeholder}</option>`;
  for (const it of list) {
    html += `<option value="${it[value]}">${escapeHtml(String(it[label]))}</option>`;
  }
  return html;
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
