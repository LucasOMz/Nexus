/**
 * Store do mapa 3D servido pelo Nexus.
 *
 * ## O que este arquivo faz
 *
 * **Estende o `Store` original do projeto "Mapa 3D"** — 533 linhas de lógica
 * de projeto, histórico (desfazer/refazer) e manipulação de equipamentos —
 * trocando **apenas duas coisas**:
 *
 * 1. `load()`: em vez de `localStorage`, busca o projeto na API do Nexus.
 * 2. `saveLocal()`: em vez de gravar no navegador, envia para a API.
 *
 * Todo o resto (mover, rotacionar, escalar, desfazer) continua igual ao
 * original e funciona de graça.
 *
 * ## As duas traduções
 *
 * * **Ativo do Nexus → equipamento do mapa**: `patrimonio` → `tag`,
 *   `departamento` → `sector`, `mapa_x`/`mapa_z` → `x`/`z`.
 * * **Tipo do catálogo**: `ti` vira `desktop`, `impressora` vira `printer`.
 *
 * Sem essas traduções, o Viewer desenharia quadrados genéricos e as etiquetas
 * ficariam vazias.
 *
 * @module lib/mapa3d/store_nexus
 */
import { api } from "../../js/api.js";
import { Store, createEquipment } from "./store.js";

const TIPO_POR_DOMINIO = {
  ti: "desktop",
  impressora: "printer",
};

const STATUS_POR_VALOR = {
  estoque: "estoque",
  em_uso: "online",
  manutencao: "manutencao",
  descarte: "offline",
  emprestado: "online",
};

/**
 * Traduz um ativo do Nexus para um equipamento do mapa.
 *
 * O `id` vira `String(ativo.id)` para casar com o formato do original
 * (`eq-xxxx`), e é por ele que o `updateEquipment` sabe qual ativo mover.
 */
export function equipamentoDeAtivo(ativo) {
  return createEquipment(TIPO_POR_DOMINIO[ativo.dominio] || "desktop", {
    id: String(ativo.id),
    name: ativo.patrimonio || ativo.numero_serie || `#${ativo.id}`,
    tag: ativo.patrimonio || "",
    sector: ativo.departamento || "",
    // `status` do Nexus: estoque, em_uso, manutencao, descarte.
    status: STATUS_POR_VALOR[ativo.status] || "online",
    ip: ativo.ip || ativo.impressora_ip || "",
    model: ativo.modelo || "",
    serial: ativo.numero_serie || "",
    responsible: ativo.ultimo_usuario || "",
    notes: ativo.localizacao || "",
    x: Number(ativo.x ?? 0),
    z: Number(ativo.z ?? 0),
    rotation: Number(ativo.rotacao ?? 0),
    // Guardado para o clique abrir a ficha certa do Nexus.
    ativoId: ativo.id,
    dominio: ativo.dominio,
  });
}

export class StoreNexus extends Store {
  /**
   * @param {number} plantaId  planta cujo mapa está aberto
   * @param {object} dados     `{posicionados, pendentes}` vindo da API
   * @param {object} projeto   `{imagem, largura_px, altura_px, escala, paredes}`
   */
  constructor(plantaId, dados, projeto) {
    // O `Store` original chama `load()` no construtor; passamos um storage
    // inerte para ele não tentar `localStorage`.
    super({ storage: { getItem: () => null, setItem: () => {} } });

    this.plantaId = plantaId;
    this._projetoApi = projeto || {};
    this._salvando = null;

    // Aplica o projeto já carregado pela tela, sem nova ida à API.
    this.project = this._montarProjeto(dados, projeto);
  }

  _montarProjeto(dados, projeto) {
    const equipamentos = [];

    for (const a of dados?.posicionados || []) {
      equipamentos.push(equipamentoDeAtivo(a));
    }

    // Os pendentes entram no projeto em (0,0) para o Viewer poder
    // desenhá-los; a tela os lista à parte para o técnico arrastar.
    for (const a of dados?.pendentes || []) {
      const eq = equipamentoDeAtivo(a);
      eq.pendente = true;
      equipamentos.push(eq);
    }

    const plan = projeto?.imagem
      ? {
        dataUrl: `/api/v1/mapas/${this.plantaId}/imagem`,
        widthPx: projeto.largura_px || 1024,
        heightPx: projeto.altura_px || 768,
        widthM: (projeto.largura_px || 1024) * (projeto.escala_metros_por_pixel || 0.02),
        heightM: (projeto.altura_px || 768) * (projeto.escala_metros_por_pixel || 0.02),
        sourceName: "planta",
        page: 1,
        createdAt: new Date().toISOString(),
      }
      : null;

    return {
      version: 1,
      name: `Planta ${this.plantaId}`,
      isDemo: false,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      plan,
      equipment: equipamentos,
      walls: Array.isArray(projeto?.paredes) ? projeto.paredes : [],
      settings: {
        showLabels: true,
        showGrid: false,
        showWalls: true,
        snap: true,
        snapSize: 0.25,
        autoRotate: false,
      },
    };
  }

  /* ------------------------------------------------------------ API */

  /**
   * Grava a posição de **um** ativo. Chamado quando o Viewer move algo.
   *
   * Só os posicionados têm `ativoId` válido — os pendentes usam o mesmo id,
   * então a rota serve para os dois.
   */
  async _gravarPosicao(eq) {
    if (!eq?.ativoId) return;
    try {
      await api.patch(`/mapas/ativos/${eq.ativoId}/posicao`, {
        x: Math.round(Number(eq.x) * 100) / 100,
        z: Math.round(Number(eq.z) * 100) / 100,
        rotacao: Math.round(Number(eq.rotation) || 0),
      });
    } catch (e) {
      console.warn("mapa: posição não gravada", e);
    }
  }

  /** Grava paredes e escala — o projeto inteiro, em uma chamada. */
  async _gravarProjeto() {
    const p = this.project;
    const plan = p.plan;

    const corpo = {
      paredes: p.walls,
    };

    if (plan?.widthPx && plan?.widthM) {
      corpo.largura_px = Math.round(plan.widthPx);
      corpo.altura_px = Math.round(plan.heightPx);
      corpo.escala_metros_por_pixel = plan.widthM / plan.widthPx;
    }

    try {
      await api.put(`/mapas/${this.plantaId}`, corpo);
    } catch (e) {
      console.warn("mapa: projeto não gravado", e);
    }
  }

  /* ------------------------------------------ sobrescreve o original */

  /**
   * O original grava no `localStorage` a cada mudança, com debounce de 850ms.
   *
   * Aqui o mesmo debounce vira uma chamada à API — e ele evita que arrastar
   * um equipamento gere 40 requisições.
   */
  saveLocal(_opts = {}) {
    clearTimeout(this._timer);
    this._timer = setTimeout(async () => {
      const mudancas = this._mudancasPendentes || new Set();
      this._mudancasPendentes = new Set();

      for (const eq of mudancas) await this._gravarPosicao(eq);
      if (this._projetoMudou) {
        this._projetoMudou = false;
        await this._gravarProjeto();
      }
      this.emit("save:state", { state: "saved" });
    }, 850);
  }

  /** Marca que um equipamento específico precisa ser gravado. */
  _marcarAtivo(eq) {
    if (!eq) return;
    this._mudancasPendentes = this._mudancasPendentes || new Set();
    this._mudancasPendentes.add(eq);
  }

  /** `updateEquipment` é o que o Viewer chama ao arrastar. */
  updateEquipment(id, patch, opts) {
    const r = super.updateEquipment(id, patch, opts);
    const eq = this.project.equipment.find((x) => x.id === id);
    if (eq) this._marcarAtivo(eq);
    return r;
  }

  addEquipment(partial, opts) {
    const r = super.addEquipment(partial, opts);
    this._projetoMudou = true;
    return r;
  }

  addWall(points, opts) {
    const r = super.addWall(points, opts);
    this._projetoMudou = true;
    return r;
  }

  updateWall(id, patch) {
    const r = super.updateWall(id, patch);
    this._projetoMudou = true;
    return r;
  }

  removeWall(id) {
    const r = super.removeWall(id);
    this._projetoMudou = true;
    return r;
  }

  setPlan(plan) {
    super.setPlan(plan);
    this._projetoMudou = true;
  }

  scaleBy(ratio) {
    const r = super.scaleBy(ratio);
    this._projetoMudou = true;
    return r;
  }
}
