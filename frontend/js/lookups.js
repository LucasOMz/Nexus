/**
 * Cache de entidades de cadastro (lookups) usadas nos formulários.
 * @module lookups
 */
import { api } from "./api.js";
import { state } from "./state.js";

let cache = null;

export async function loadLookups(force = false) {
  const escopo = [state.user?.id, state.plantaAtiva, state.dominio].join(":");
  if (cache?.escopo === escopo && !force) return cache.dados;
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
  const dados = { departamentos, localizacoes, fornecedores, categorias, usuarios, plantas };
  cache = { escopo, dados };
  return dados;
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
