/**
 * Contexto de UI injetado pelo shell (app.js) e consumido pelas views.
 * Evita import circular entre app.js e os módulos de view.
 * @module context
 */
export const ctx = {
  /** Define o título da página. */
  setTitle: () => {},
  /** Mostra/oculta o FAB estendido ({label, icon, onClick} ou null). */
  setFab: () => {},
  /** Navega para uma rota (#/rota). */
  navigate: () => {},
  /** Liga/desliga o shell (topbar + rail + bottom nav). */
  setChrome: () => {},
  /** Volta ao menu inicial do inventário atual. */
  goHome: () => {},
  /** Re-renderiza a rota atual. */
  rerender: () => {},
};
