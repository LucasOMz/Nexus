/**
 * Testes do formatador de erros do frontend.
 *
 * Garante que a mensagem mostrada ao usuário é legível — antes, erros de
 * validação do FastAPI (que vêm como LISTA de objetos) apareciam na tela como
 * "[object Object],[object Object]".
 *
 * Uso: node tests/check_erros.mjs
 */
import { mensagemErro, camposComErro } from "../frontend/js/erros.js";

let falhas = 0;
let total = 0;

function verificar(nome, obtido, esperado) {
  total++;
  const ok = typeof esperado === "function" ? esperado(obtido) : obtido === esperado;
  if (ok) {
    console.log(`OK   ${nome}`);
  } else {
    falhas++;
    console.error(`FALHOU ${nome}\n       obtido:   ${JSON.stringify(obtido)}\n       esperado: ${JSON.stringify(esperado)}`);
  }
}

// 1) O caso que o usuário relatou: lista de erros de validação (422).
const validacao = [
  { type: "value_error", loc: ["body", "email"], msg: "value is not a valid email address: An email address must have an @-sign." },
  { type: "missing", loc: ["body", "nome"], msg: "Field required" },
];
const saida = mensagemErro(validacao, 422);
verificar("lista de erros vira texto legível", saida, (s) => typeof s === "string" && !s.includes("[object Object]"));
verificar("traz o campo e a mensagem traduzida", saida, (s) => s.includes("E-mail") && s.includes("campo obrigatório"));
verificar("une os erros numa linha", saida, (s) => s.includes(" · "));

// 2) HTTPException: string simples passa direto.
verificar("string passa direto", mensagemErro("Patrimônio já cadastrado", 409), "Patrimônio já cadastrado");

// 3) Traduções comuns do Pydantic.
verificar("e-mail inválido", mensagemErro([{ loc: ["body", "email"], msg: "Input should be a valid email address" }], 422),
  (s) => s.includes("deve ser um e-mail válido"));
verificar("inteiro inválido", mensagemErro([{ loc: ["body", "ram_gb"], msg: "Input should be a valid integer, unable to parse string as an integer" }], 422),
  (s) => s.includes("RAM") && s.includes("número inteiro"));
verificar("extra não permitido", mensagemErro([{ loc: ["body", "xyz"], msg: "Extra inputs are not permitted" }], 422),
  (s) => s.includes("campo não reconhecido"));
verificar("mínimo de caracteres", mensagemErro([{ loc: ["body", "nome"], msg: "String should have at least 6 characters" }], 422),
  (s) => s.includes("pelo menos 6"));
verificar("maior ou igual", mensagemErro([{ loc: ["body", "estoque_minimo"], msg: "Input should be greater than or equal to 0" }], 422),
  (s) => s.includes("maior ou igual a 0"));

// 4) Objeto aninhado (ex.: campo da extensão da impressora).
verificar("campo aninhado", mensagemErro([{ loc: ["body", "impressora", "contador_paginas"], msg: "Input should be a valid integer" }], 422),
  (s) => s.includes("Impressora") && s.includes("Contador de páginas"));

// 5) Fallbacks quando não vem detalhe.
verificar("fallback 403", mensagemErro(null, 403), (s) => s.includes("permissão"));
verificar("fallback 500", mensagemErro(undefined, 500), (s) => s.includes("log do servidor"));
verificar("nunca devolve objeto", mensagemErro({ foo: "bar" }, 500), (s) => typeof s === "string" && !s.includes("[object Object]"));
verificar("lista vazia usa fallback", mensagemErro([], 422), (s) => typeof s === "string" && s.length > 0);

// 6) Extração dos campos com erro (para destacar no formulário).
const campos = camposComErro(validacao);
verificar("camposComErro extrai os campos", campos, (c) => c.length === 2 && c[0].campo === "email" && c[1].campo === "nome");

console.log(falhas === 0 ? `\nTODOS OS ${total} CASOS PASSARAM` : `\n${falhas} DE ${total} FALHARAM`);
process.exit(falhas === 0 ? 0 : 1);
