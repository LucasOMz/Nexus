/**
 * Verificação de integridade dos módulos do frontend.
 *
 * Importa TODOS os módulos ES do frontend e falha se algum `import`/`export`
 * estiver quebrado — é o tipo de erro que deixa a tela em branco no navegador
 * sem mensagem clara.
 *
 * Uso (na raiz do projeto):
 *   node tests/check_frontend_modules.mjs
 *
 * Não faz parte da aplicação: é uma ferramenta de verificação.
 */
globalThis.localStorage = {
  _d: {},
  getItem(k) { return this._d[k] ?? null; },
  setItem(k, v) { this._d[k] = String(v); },
  removeItem(k) { delete this._d[k]; },
};
globalThis.matchMedia = () => ({ matches: false, addEventListener() {} });
globalThis.location = { hash: "", search: "", href: "http://localhost/", reload() {} };
globalThis.history = { replaceState() {} };
globalThis.document = {
  documentElement: { setAttribute() {}, getAttribute() { return null; } },
  getElementById() { return null; },
  querySelectorAll() { return []; },
  createElement() {
    return {
      style: {}, append() {}, addEventListener() {}, setAttribute() {}, removeAttribute() {},
      classList: { add() {}, remove() {}, toggle() {} },
    };
  },
  addEventListener() {},
  body: { append() {} },
};
globalThis.window = globalThis;

const modulos = [
  "js/version.js", "js/context.js", "js/state.js", "js/offline.js", "js/api.js",
  "js/ui.js", "js/charts.js", "js/label.js", "js/erros.js", "js/lookups.js", "js/router.js",
  "js/easteregg.js", "js/versao_servidor.js", "js/seletor_ativo.js", "js/notificacoes.js",
  "js/views/calendario.js", "js/views/reporte.js", "js/views/admin_ocs.js", "js/views/admin_banco.js", "js/barra_lateral.js", "js/ordenar.js",
  "js/views/login.js", "js/views/inventario.js", "js/views/dashboard.js",
  "js/views/ativos.js", "js/views/produtos.js", "js/views/movimentacoes.js",
  "js/views/manutencoes.js", "js/views/scanner.js", "js/views/relatorios.js",
  "js/views/cadastros.js", "js/views/admin.js", "js/views/admin_etiquetas.js",
  "js/views/admin_backups.js", "js/views/admin_auth.js", "js/views/admin_auditoria.js",
  "js/views/admin_plantas.js", "js/views/impressao.js",
];

let falhas = 0;
for (const m of modulos) {
  try {
    const mod = await import(`../frontend/${m}`);
    console.log(`OK  ${m.padEnd(32)} -> ${Object.keys(mod).join(", ") || "(sem exports)"}`);
  } catch (e) {
    falhas++;
    console.error(`FALHOU ${m}: ${e.message}`);
  }
}
console.log(falhas === 0 ? `\nTODOS OS ${modulos.length} MÓDULOS CARREGARAM` : `\n${falhas} MÓDULO(S) COM FALHA`);
process.exit(falhas === 0 ? 0 : 1);
