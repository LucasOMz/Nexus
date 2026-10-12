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
  paleta: "gp_paleta",
  fundo: "gp_fundo",
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
  paleta: localStorage.getItem(LS.paleta) || "nexus",
  fundo: localStorage.getItem(LS.fundo) || "verde",
  theme: localStorage.getItem(LS.theme) || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"),

  /** Persiste tokens e usuário após login/refresh. */
  setAuth({ access_token, refresh_token, user }) {
    this.access = access_token;
    this.refresh = refresh_token;
    this.user = user;
    localStorage.setItem(LS.access, access_token);
    localStorage.setItem(LS.refresh, refresh_token);
    localStorage.setItem(LS.user, JSON.stringify(user));
    // O tema vem na conta: aplicar aqui faz a tela abrir no tema da pessoa,
    // inclusive num computador onde ela nunca entrou.
    //
    // `salvar=false` porque este tema VEIO do servidor — regravá-lo seria
    // escrita inútil a cada login.
    if (user?.tema) this.setTheme(user.tema, false);
    if (user?.paleta) this.setPaleta(user.paleta, false);
    if (user?.fundo) this.setFundo(user.fundo, false);
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

  setTheme(t, salvar = true) {
    this.theme = t;
    localStorage.setItem(LS.theme, t);
    document.documentElement.setAttribute("data-theme", t);
    // A preferência vai para a CONTA, não só para este navegador: trocar de
    // computador não deveria obrigar a reconfigurar a tela.
    //
    // `salvar=false` é usado ao APLICAR o tema que veio do servidor no login —
    // senão cada entrada regravaria o que já estava gravado.
    if (salvar && this.access) {
      import("./api.js")
        .then(({ api }) => api.put("/auth/preferencias", { tema: t }))
        .catch(() => { /* preferência é conforto: falhar aqui não trava nada */ });
    }
  },

  applyPaleta() {
    // O atributo existe mesmo quando a paleta é a padrão: sem ele, trocar de
    // verde para o padrão não limparia o estilo anterior.
    document.documentElement.setAttribute("data-paleta", this.paleta || "nexus");
  },

  /**
   * Cor de FUNDO — o TERCEIRO eixo.
   *
   * Independente do destaque de propósito: antes a cor de destaque arrastava
   * o fundo junto, e não dava para ter destaque azul sobre fundo verde.
   */
  setFundo(f, salvar = true) {
    this.fundo = f;
    localStorage.setItem(LS.fundo, f);
    this.applyFundo();
    if (salvar && this.access) {
      import("./api.js")
        .then(({ api }) => api.put("/auth/preferencias", { fundo: f }))
        .catch(() => { /* preferência é conforto: falhar aqui não trava nada */ });
    }
  },

  applyFundo() {
    document.documentElement.setAttribute("data-fundo", this.fundo || "verde");
  },

  /**
   * Cor de destaque — o SEGUNDO eixo visual.
   *
   * Separado do claro/escuro de propósito: são decisões independentes, e
   * juntar as duas num só campo obrigaria a repetir cada cor nos dois modos.
   */
  setPaleta(p, salvar = true) {
    this.paleta = p;
    localStorage.setItem(LS.paleta, p);
    this.applyPaleta();
    if (salvar && this.access) {
      import("./api.js")
        .then(({ api }) => api.put("/auth/preferencias", { paleta: p }))
        .catch(() => { /* preferência é conforto: falhar aqui não trava nada */ });
    }
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

  /**
   * Permissão que não é por módulo nem booleana — hoje só
   * licencas.ver_chave.
   *
   * ## Por que a tela precisa saber
   *
   * O botão Revelar aparecia para todo mundo e só falhava depois, com 403.
   * Botão que existe e não funciona é pior que botão ausente: a pessoa
   * clica, leva um erro que não explica nada, e conclui que o sistema está
   * quebrado — em vez de entender que não tem o acesso.
   *
   * A checagem aqui é de CONVENIÊNCIA. Quem manda é o backend: esconder o
   * botão não protege nada, só evita o clique inútil.
   */
  podeExtra(permissao) {
    if (this.isAdmin) return true;
    const efetivas = this.user?.permissoes_efetivas || this.user?.permissoes || {};
    const extras = efetivas.permissoes_extra || [];
    return Array.isArray(extras) && extras.includes(permissao);
  },
};

export { ROTULO_INVENTARIO };
