/**
 * Formatação de mensagens de erro da API.
 *
 * O FastAPI devolve dois formatos bem diferentes em `detail`:
 *
 *  * `HTTPException`  → **string**  ("Usuário ou senha inválidos")
 *  * validação (422)  → **lista de objetos**
 *      [{"loc":["body","nome"],"msg":"Field required","type":"missing"}]
 *
 * Jogar a lista direto na tela aparecia como `[object Object],[object Object]`.
 * Aqui ela vira uma mensagem legível, em português, com o campo culpado.
 * @module erros
 */

/**
 * Nome amigável de um campo (aceita caminhos como `impressora.contador_paginas`).
 * @param {string} nome
 * @returns {string}
 */
export function rotuloCampo(nome) {
  if (!nome) return "Requisição";
  return String(nome)
    .split(".")
    .map((parte) => {
      const indice = parte.match(/^(.+)\[(\d+)\]$/);
      if (indice) return `${NOMES_CAMPOS[indice[1]] || indice[1]}[${indice[2]}]`;
      return NOMES_CAMPOS[parte] || parte;
    })
    .join(" › ");
}

/**
 * Dica adicional para os erros que NÃO são culpa de quem preencheu.
 * @param {string} mensagem
 * @returns {string}
 */
export function dicaParaErro(mensagem) {
  const texto = String(mensagem || "").toLowerCase();
  if (texto.includes("campo não reconhecido")) {
    return "Este campo é enviado automaticamente pelo sistema — não é algo que você digitou. "
      + "Isso indica uma inconsistência interna: repasse esta mensagem ao suporte.";
  }
  if (texto.includes("já existe") || texto.includes("já cadastrado")) {
    return "Já existe um registro com esse valor. Use outro nome/código ou edite o registro existente.";
  }
  if (texto.includes("não tem permissão") || texto.includes("permissão insuficiente")) {
    return "Peça ao administrador para liberar este módulo ou a permissão de escrita no seu usuário.";
  }
  if (texto.includes("obrigatório")) {
    return "Preencha os campos indicados acima — eles são de preenchimento obrigatório.";
  }
  return "";
}

/** Nomes amigáveis para os campos mais usados nos formulários. */
const NOMES_CAMPOS = {
  nome: "Nome", email: "E-mail", senha: "Senha", papel: "Perfil",
  patrimonio: "Patrimônio", numero_serie: "Nº de série", modelo: "Modelo", marca: "Marca",
  categoria_id: "Categoria", fornecedor_id: "Fornecedor", localizacao_id: "Localização",
  departamento_id: "Departamento", data_garantia: "Garantia", data_aquisicao: "Data de aquisição",
  valor: "Valor", foto_id: "Foto", observacoes: "Observações", status: "Status", dominio: "Inventário",
  sku: "SKU", unidade: "Unidade", estoque_minimo: "Estoque mínimo", preco_unitario: "Preço unitário",
  tipo_item: "Tipo de item", tipo: "Tipo", tipo_impressao: "Tipo de impressão", conectividade: "Conectividade",
  hostname: "Hostname", ip: "IP", mac_address: "MAC", so: "Sistema operacional", ram_gb: "RAM",
  armazenamento_gb: "Armazenamento", contador_paginas: "Contador de páginas", driver: "Driver",
  ativo_id: "Ativo", produto_id: "Produto", quantidade: "Quantidade", custo: "Custo", tecnico: "Técnico",
  descricao: "Descrição", fornecedor: "Fornecedor", largura_mm: "Largura", altura_mm: "Altura",
  dpi: "DPI", formato: "Formato", printer: "Impressora", copies: "Cópias",
  compartilhamento: "Compartilhamento", agente_url: "URL do agente", fila_cups: "Fila do CUPS",
  ldap_servidor: "Servidor do AD", ldap_porta: "Porta", ldap_base_dn: "Base DN",
  ldap_bind_dn: "Conta de serviço", ldap_filtro_usuario: "Filtro de usuário",
  ldap_grupo_acesso: "Grupo de acesso", ldap_grupo_admin: "Grupo de administradores",
  permissoes: "Permissões", codigo: "Código", payload: "Payload", ativo_ids: "Ativos selecionados",
  confirmacao: "Confirmação", arquivo: "Arquivo", titulo: "Título", rodape: "Rodapé",
  qr_tamanho_mm: "Tamanho do QR", qr_ecc: "Correção de erro", alinhamento: "Alinhamento",
  fonte_mm: "Tamanho da fonte", margem_mm: "Margem", campos: "Campos exibidos",
  impressora: "Impressora", ti: "TI", suprimentos: "Suprimentos", usuario: "Usuário",
};

/** Traduções das mensagens do Pydantic/FastAPI. */
const TRADUCOES = [
  [/^field required$/i, "campo obrigatório"],
  [/^input should be a valid string$/i, "deve ser um texto"],
  [/^input should be a valid integer[,.]?.*/i, "deve ser um número inteiro"],
  [/^input should be a valid number[,.]?.*/i, "deve ser um número"],
  [/^input should be a valid boolean[,.]?.*/i, "deve ser sim ou não"],
  [/^input should be a valid date$/i, "deve ser uma data válida"],
  [/^input should be a valid datetime[,.]?.*/i, "deve ser uma data e hora válidas"],
  [/^input should be a valid email address.*/i, "deve ser um e-mail válido"],
  [/^extra inputs are not permitted$/i, "campo não reconhecido"],
  [/^input should be '(.+)'$/i, (m) => `deve ser um destes valores: ${m[1].replace(/'/g, "")}`],
  [/^string should have at least (\d+) character/i, (m) => `precisa ter pelo menos ${m[1]} caractere(s)`],
  [/^string should have at most (\d+) character/i, (m) => `pode ter no máximo ${m[1]} caractere(s)`],
  [/^input should be greater than or equal to (\d+)/i, (m) => `deve ser maior ou igual a ${m[1]}`],
  [/^input should be less than or equal to (\d+)/i, (m) => `deve ser menor ou igual a ${m[1]}`],
  [/^input should be greater than (\d+)/i, (m) => `deve ser maior que ${m[1]}`],
  [/^input should be less than (\d+)/i, (m) => `deve ser menor que ${m[1]}`],
  [/^list should have at least (\d+) item/i, (m) => `selecione pelo menos ${m[1]} item(ns)`],
  [/^list should have at most (\d+) item/i, (m) => `selecione no máximo ${m[1]} item(ns)`],
  [/^value error, (.+)$/i, (m) => m[1]],
  [/^assertion failed, (.+)$/i, (m) => m[1]],
  [/^input is not a valid (.*)$/i, (m) => `não é um valor válido de ${m[1]}`],
];

/** Aplica a tradução; se não houver padrão conhecido, devolve o texto original. */
function traduzir(mensagem) {
  const texto = String(mensagem || "").trim();
  for (const [padrao, destino] of TRADUCOES) {
    const casado = texto.match(padrao);
    if (casado) return typeof destino === "function" ? destino(casado) : destino;
  }
  return texto;
}

/** Converte `["body","impressora","ip"]` em `Impressora › IP`. */
function nomeDoCampo(loc) {
  if (!Array.isArray(loc) || !loc.length) return "";
  const partes = loc.filter((p) => !["body", "query", "path", "header"].includes(String(p)));
  if (!partes.length) return "Requisição";
  return partes
    .map((p) => (typeof p === "number" ? `[${p}]` : (NOMES_CAMPOS[String(p)] || String(p))))
    .join(" › ")
    .replace(/ › \[/g, "[");
}

/**
 * Transforma o `detail` da API numa mensagem legível.
 * @param {unknown} detail - valor de `detail` devolvido pela API
 * @param {number} [status] - código HTTP (usado no fallback)
 * @returns {string}
 */
export function mensagemErro(detail, status) {
  // 1) String simples (HTTPException).
  if (typeof detail === "string" && detail.trim()) return detail.trim();

  // 2) Lista de erros de validação (422).
  if (Array.isArray(detail)) {
    const partes = detail.map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object") {
        const campo = nomeDoCampo(item.loc);
        const msg = traduzir(String(item.msg ?? item.message ?? ""));
        return campo ? `${campo}: ${msg}` : msg;
      }
      return String(item);
    }).filter(Boolean);
    if (partes.length) return partes.join(" · ");
  }

  // 3) Objeto com msg/detail.
  if (detail && typeof detail === "object") {
    if (typeof detail.msg === "string") return traduzir(detail.msg);
    if (typeof detail.detail === "string") return detail.detail;
    try {
      const texto = JSON.stringify(detail);
      if (texto && texto !== "{}") return texto;
    } catch { /* segue para o fallback */ }
  }

  // 4) Fallback por código HTTP.
  const porStatus = {
    400: "Requisição inválida.",
    401: "Sessão expirada. Entre novamente.",
    403: "Seu usuário não tem permissão para esta ação.",
    404: "Registro não encontrado.",
    409: "Já existe um registro com esses dados.",
    422: "Verifique os campos destacados — há informação inválida ou faltando.",
    429: "Muitas tentativas. Aguarde um instante.",
    500: "Erro interno no servidor. Confira o log do servidor.",
    503: "Serviço indisponível no momento.",
  };
  return porStatus[status ?? 0] || `Não foi possível concluir a operação${status ? ` (HTTP ${status})` : ""}.`;
}

/**
 * Monta um Error legível a partir de uma resposta crua (uploads com FormData,
 * que não passam pelo `api.js`).
 * @param {number} status
 * @param {unknown} corpo - corpo já convertido (objeto) ou null
 * @returns {Error & {status?: number, detail?: unknown, campos?: Array}}
 */
export function erroDeResposta(status, corpo) {
  const detalhe = corpo && typeof corpo === "object" && "detail" in corpo ? corpo.detail : corpo;
  const erro = new Error(mensagemErro(detalhe, status));
  erro.status = status;
  erro.detail = detalhe;
  erro.campos = camposComErro(detalhe);
  return erro;
}

/**
 * Extrai a lista de campos com problema (para destacar no formulário).
 * @param {unknown} detail
 * @returns {Array<{campo: string, mensagem: string}>}
 */
export function camposComErro(detail) {
  if (!Array.isArray(detail)) return [];
  return detail
    .filter((i) => i && typeof i === "object" && Array.isArray(i.loc))
    .map((i) => {
      const partes = i.loc.filter((p) => !["body", "query", "path"].includes(String(p)));
      return { campo: partes.map(String).join("."), mensagem: traduzir(String(i.msg ?? "")) };
    });
}
