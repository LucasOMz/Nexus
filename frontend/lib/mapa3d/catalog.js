/* Catálogo de equipamentos ------------------------------------------------- */

export const CATEGORIES = [
  { id: 'rede', label: 'TI & Rede', color: '#38bdf8', short: 'TI' },
  { id: 'producao', label: 'Produção', color: '#f59e0b', short: 'PROD' },
  { id: 'infra', label: 'Infraestrutura', color: '#a78bfa', short: 'INFRA' },
  { id: 'seguranca', label: 'Segurança', color: '#fb7185', short: 'SEG' },
  { id: 'logistica', label: 'Logística', color: '#34d399', short: 'LOG' },
];

export const CATEGORY_MAP = new Map(CATEGORIES.map((c) => [c.id, c]));

export const STATUSES = [
  { id: 'online', label: 'Online', color: '#34d399', description: 'Operando normalmente' },
  { id: 'manutencao', label: 'Manutenção', color: '#fbbf24', description: 'Em manutenção' },
  { id: 'offline', label: 'Offline', color: '#fb7185', description: 'Parado / sem conexão' },
  { id: 'estoque', label: 'Estoque', color: '#60a5fa', description: 'Reserva / não instalado' },
];

export const STATUS_MAP = new Map(STATUSES.map((s) => [s.id, s]));

/**
 * Metadados dos tipos de equipamento.
 * dims = [largura, altura, profundidade] aproximadas em metros (para exibição).
 * elevation = altura padrão do piso em metros (itens de teto/parede).
 */
export const EQUIPMENT_TYPES = [
  // ---------------- TI & Rede ----------------
  {
    id: 'desktop', label: 'Computador', cat: 'rede', desc: 'Estação de trabalho', dims: [0.9, 1.15, 0.6],
    keywords: 'pc desktop computador estação workstation',
  },
  {
    id: 'notebook', label: 'Notebook', cat: 'rede', desc: 'Estação móvel', dims: [0.45, 0.32, 0.35],
    keywords: 'notebook laptop portátil',
  },
  {
    id: 'server', label: 'Servidor', cat: 'rede', desc: 'Servidor torre', dims: [0.55, 0.95, 0.7],
    keywords: 'servidor server torre',
  },
  {
    id: 'rack', label: 'Rack de rede', cat: 'rede', desc: 'Armário de 19"', dims: [0.65, 1.9, 0.85],
    keywords: 'rack armário datacenter',
  },
  {
    id: 'switch', label: 'Switch', cat: 'rede', desc: 'Switch gerenciável', dims: [0.48, 0.15, 0.3],
    keywords: 'switch comutador rede',
  },
  {
    id: 'router', label: 'Roteador', cat: 'rede', desc: 'Roteador / firewall', dims: [0.36, 0.32, 0.28],
    keywords: 'roteador router firewall',
  },
  {
    id: 'ap', label: 'Access point Wi-Fi', cat: 'rede', desc: 'Ponto de acesso (teto)', dims: [0.4, 0.12, 0.4],
    elevation: 2.9, labelBelow: true,
    keywords: 'access point ap wifi wi-fi antena teto',
  },
  {
    id: 'antenna', label: 'Antena Wi-Fi', cat: 'rede', desc: 'Antena setorial externa', dims: [0.5, 2.5, 0.5],
    keywords: 'antena setorial wifi wi-fi outdoor',
  },
  {
    id: 'printer', label: 'Impressora', cat: 'rede', desc: 'Impressora de rede', dims: [0.55, 0.7, 0.5],
    keywords: 'impressora printer multifuncional',
  },
  {
    id: 'nobreak', label: 'Nobreak', cat: 'rede', desc: 'UPS / estabilizador', dims: [0.25, 0.45, 0.38],
    keywords: 'nobreak ups energia',
  },
  {
    id: 'phone', label: 'Telefone IP', cat: 'rede', desc: 'Telefone VoIP', dims: [0.24, 0.12, 0.22],
    keywords: 'telefone ip voip ramal',
  },

  // ---------------- Produção ----------------
  {
    id: 'cnc', label: 'Centro de usinagem CNC', cat: 'producao', desc: 'Usinagem automatizada', dims: [2.3, 2.1, 1.7],
    keywords: 'cnc usinagem fresadora máquina',
  },
  {
    id: 'conveyor', label: 'Esteira transportadora', cat: 'producao', desc: 'Linha de transporte', dims: [2.7, 0.95, 0.8],
    keywords: 'esteira transportadora correia linha',
  },
  {
    id: 'lathe', label: 'Torno mecânico', cat: 'producao', desc: 'Torno paralelo', dims: [2.1, 1.35, 0.9],
    keywords: 'torno mecânico usinagem',
  },
  {
    id: 'press', label: 'Prensa hidráulica', cat: 'producao', desc: 'Prensagem de peças', dims: [1.5, 2.4, 1.2],
    keywords: 'prensa hidráulica estamparia',
  },
  {
    id: 'workbench', label: 'Bancada de trabalho', cat: 'producao', desc: 'Bancada com ferramentas', dims: [1.9, 1.6, 0.85],
    keywords: 'bancada mesa trabalho ferramentas',
  },

  // ---------------- Infraestrutura ----------------
  {
    id: 'panel', label: 'Painel elétrico', cat: 'infra', desc: 'Quadro de distribuição', dims: [0.9, 2.1, 0.45],
    keywords: 'painel elétrico quadro distribuição energia',
  },
  {
    id: 'compressor', label: 'Compressor de ar', cat: 'infra', desc: 'Ar comprimido', dims: [1.3, 1.1, 0.8],
    keywords: 'compressor ar comprimido',
  },
  {
    id: 'ac', label: 'Ar-condicionado', cat: 'infra', desc: 'Split de parede', dims: [1.0, 0.32, 0.25],
    elevation: 2.6, labelBelow: true,
    keywords: 'ar condicionado split climatização',
  },
  {
    id: 'lamp', label: 'Luminária industrial', cat: 'infra', desc: 'Iluminação suspensa', dims: [0.6, 0.8, 0.6],
    elevation: 4.0, labelBelow: true,
    keywords: 'luminária lâmpada iluminação luz',
  },

  // ---------------- Segurança ----------------
  {
    id: 'camera', label: 'Câmera IP', cat: 'seguranca', desc: 'CFTV (teto)', dims: [0.3, 0.3, 0.4],
    elevation: 2.8, labelBelow: true,
    keywords: 'câmera ip cftv vigilância',
  },
  {
    id: 'sensor', label: 'Sensor de presença', cat: 'seguranca', desc: 'Sensor infravermelho', dims: [0.14, 0.1, 0.14],
    elevation: 3.0, labelBelow: true,
    keywords: 'sensor presença infravermelho',
  },
  {
    id: 'extinguisher', label: 'Extintor', cat: 'seguranca', desc: 'Extintor de incêndio', dims: [0.3, 0.85, 0.3],
    keywords: 'extintor incêndio fogo',
  },
  {
    id: 'hydrant', label: 'Hidrante', cat: 'seguranca', desc: 'Abrigo de mangueira', dims: [0.55, 1.1, 0.35],
    keywords: 'hidrante mangueira incêndio',
  },

  // ---------------- Logística ----------------
  {
    id: 'pallet', label: 'Pallet com caixas', cat: 'logistica', desc: 'Carga paletizada', dims: [1.2, 1.3, 1.0],
    keywords: 'pallet caixa estoque carga',
  },
  {
    id: 'forklift', label: 'Empilhadeira', cat: 'logistica', desc: 'Empilhadeira industrial', dims: [1.4, 2.4, 2.4],
    keywords: 'empilhadeira forklift logística',
  },
];

export const TYPE_MAP = new Map(EQUIPMENT_TYPES.map((t) => [t.id, t]));

export function getType(id) {
  return TYPE_MAP.get(id) || {
    id: id || 'desconhecido',
    label: 'Equipamento',
    cat: 'infra',
    desc: 'Item genérico',
    dims: [0.8, 0.8, 0.8],
  };
}

export function categoryOf(typeId) {
  return CATEGORY_MAP.get(getType(typeId).cat) || CATEGORIES[0];
}

export function statusOf(id) {
  return STATUS_MAP.get(id) || STATUSES[0];
}

export function typesByCategory() {
  return CATEGORIES.map((cat) => ({
    ...cat,
    types: EQUIPMENT_TYPES.filter((t) => t.cat === cat.id),
  }));
}
