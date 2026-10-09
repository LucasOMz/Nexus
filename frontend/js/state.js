/**
 * Estado global da aplicação, persistido em localStorage.
 * O inventário selecionado é refletido em `data-dominio` (cores) e na URL.
 * @module state
 */

const LS = {
  access: "gp_access",
  refresh: "gp_refresh",
  user: "gp_user",
  dominio: "gp_dominio",
  theme: "gp_theme",
};

function readJSON(key) {
  try { return JSON.parse(localStorage.getItem(key) || "null"); } catch { return null; }
}

const ROTULO_INVENTARIO = {
  ti: "Inventário de TI",
  impressora: "Inventário de Impressoras",
};

export const state = {
  access: localStorage.getItem(LS.access),
  refresh: localStorage.getItem(LS.refresh),
  user: readJSON(LS.user),
  dominio: localStorage.getItem(LS.dominio) || "ti",
  theme: localStorage.getItem(LS.theme) || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"),

  /** Persiste tokens e usuário após login/refresh. */
  setAuth({ access_token, refresh_token, user }) {
    this.access = access_token;
    this.refresh = refresh_token;
    this.user = user;
    localStorage.setItem(LS.access, access_token);
    localStorage.setItem(LS.refresh, refresh_token);
    localStorage.setItem(LS.user, JSON.stringify(user));
  },

  /** Atualiza apenas os dados do usuário (permissões recarregadas). */
  setUser(user) {
    this.user = user;
    localStorage.setItem(LS.user, JSON.stringify(user));
  },

  /** Define o inventário ativo (sem reload). */
  setDominio(d) {
    this.dominio = d;
    localStorage.setItem(LS.dominio, d);
    this.applyDominio();
  },

  setTheme(t) {
    this.theme = t;
    localStorage.setItem(LS.theme, t);
    document.documentElement.setAttribute("data-theme", t);
  },

  applyDominio() {
    document.documentElement.setAttribute("data-dominio", this.dominio);
  },

  applyTheme() {
    document.documentElement.setAttribute("data-theme", this.theme);
  },

  logout() {
    this.access = null;
    this.refresh = null;
    this.user = null;
    localStorage.removeItem(LS.access);
    localStorage.removeItem(LS.refresh);
    localStorage.removeItem(LS.user);
  },

  // ------------------------------------------------------------------
  // Permissões (vêm do backend em `permissoes_efetivas`)
  // ------------------------------------------------------------------
  get perms() {
    return this.user?.permissoes_efetivas || { inventarios: ["ti", "impressora"], modulos: [], pode_escrever: false, pode_excluir: false };
  },
  get isAuthed() { return Boolean(this.access); },
  get isAdmin() { return this.user?.papel === "admin"; },
  /** Id da planta do usuário (null = acesso a todas, caso do administrador). */
  get plantaId() { return this.user?.planta_id ?? null; },
  get canWrite() { return this.isAdmin || Boolean(this.perms.pode_escrever); },
  get canDelete() { return this.isAdmin || Boolean(this.perms.pode_excluir); },
  get isAuditor() { return this.user?.papel === "auditor"; },
  get dominioLabel() { return ROTULO_INVENTARIO[this.dominio] || this.dominio; },

  /** Módulos que este usuário pode acessar. */
  modulosPermitidos() {
    if (this.isAdmin) return ["ativos", "produtos", "movimentacoes", "manutencoes", "scanner", "relatorios", "cadastros", "impressao", "calendario", "reporte"];
    return this.perms.modulos || [];
  },

  /** Inventários que este usuário pode abrir. */
  inventariosPermitidos() {
    if (this.isAdmin) return ["ti", "impressora"];
    const inv = this.perms.inventarios || [];
    return inv.length ? inv : ["ti", "impressora"];
  },

  podeModulo(modulo) {
    return this.isAdmin || this.modulosPermitidos().includes(modulo);
  },

  podeInventario(dominio) {
    return this.inventariosPermitidos().includes(dominio);
  },
};

export { ROTULO_INVENTARIO };
