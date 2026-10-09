/**
 * Roteador por hash (SPA-like, sem reload).
 * @module router
 */

export class Router {
  constructor() {
    this.routes = new Map();
    this.onChange = null;
  }

  add(path, handler) { this.routes.set(path, handler); return this; }

  start() {
    window.addEventListener("hashchange", () => this._resolve());
    this._resolve();
  }

  go(path) { location.hash = "#/" + path; }

  _resolve() {
    // O Dashboard foi incorporado a Relatórios: é a tela padrão do inventário.
    const raw = (location.hash || "#/relatorios").replace(/^#\/?/, "");
    const path = raw.split("?")[0] || "relatorios";
    const handler = this.routes.get(path) || this.routes.get("relatorios");
    handler?.(path);
    this.onChange?.(path);
  }
}
