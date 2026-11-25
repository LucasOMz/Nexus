/** Adapta o editor 3D ao projeto e aos ativos reais do Nexus. */
import { api } from "../../js/api.js";
import { STATUS_LABEL } from "../../js/ui.js";
import { Store, createEquipment } from "./store.js";

const statusVisual = {
  estoque: "estoque", reservado: "estoque", em_uso: "online",
  manutencao: "manutencao", descartado: "offline", emprestado: "online",
};

function tipoDoAtivo(ativo) {
  if (ativo.dominio === "impressora") return "printer";
  const modelo = ativo.modelo || "";
  if (/notebook|laptop|thinkpad|latitude|vivobook|macbook|elitebook|ideapad/i.test(modelo)) return "notebook";
  if (/servidor|poweredge|proliant/i.test(modelo)) return "server";
  if (/switch|roteador|router|nobreak|rack/i.test(modelo)) {
    if (/switch/i.test(modelo)) return "switch";
    if (/roteador|router/i.test(modelo)) return "router";
    if (/nobreak/i.test(modelo)) return "nobreak";
    return "rack";
  }
  return "desktop";
}

function equipamentoDeAtivo(ativo, pendente) {
  return createEquipment(tipoDoAtivo(ativo), {
    id: String(ativo.id),
    name: ativo.patrimonio || ativo.hostname || ativo.numero_serie || `Ativo #${ativo.id}`,
    tag: ativo.patrimonio || "",
    sector: ativo.departamento || "",
    status: statusVisual[ativo.status] || "estoque",
    statusLabel: STATUS_LABEL[ativo.status],
    mapColor: ativo.dominio === "impressora" ? "#aa88ea" : "#43c4bd",
    ip: ativo.ip || ativo.impressora_ip || "",
    model: ativo.modelo || "",
    serial: ativo.numero_serie || "",
    notes: ativo.localizacao || "",
    x: ativo.x ?? 0,
    z: ativo.z ?? 0,
    rotation: ativo.rotacao ?? 0,
    pendente,
    ativo,
  });
}

function paredesDoProjeto(paredes = []) {
  return paredes.flatMap((parede, indice) => {
    if (!parede) return [];
    const points = parede.points || [[parede.x1, parede.z1], [parede.x2, parede.z2]];
    if (points.length < 2 || !points.every(p => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite))) return [];
    return [{
      id: parede.id || `parede-${indice}`,
      points,
      height: parede.height ?? parede.altura ?? 3,
      thickness: parede.thickness ?? parede.espessura ?? 0.16,
    }];
  });
}

export function plantaDoProjeto(projeto, dataUrl) {
  if (!dataUrl) return null;
  const widthPx = projeto.largura_px || 1024;
  const heightPx = projeto.altura_px || 768;
  const escala = projeto.escala_metros_por_pixel || 0.02;
  return { dataUrl, widthPx, heightPx, widthM: widthPx * escala, heightM: heightPx * escala };
}

const metros = valor => Math.round(valor * 1000) / 1000;

export class StoreNexus extends Store {
  constructor(plantaId, dados, projeto, imagemUrl) {
    super({ storage: null });
    this.plantaId = plantaId;
    this.project.plan = plantaDoProjeto(projeto, imagemUrl);
    this.project.walls = paredesDoProjeto(projeto.paredes);
    this.project.equipment = [
      ...dados.posicionados.map(ativo => equipamentoDeAtivo(ativo, false)),
      ...dados.pendentes.map(ativo => equipamentoDeAtivo(ativo, true)),
    ];
    this.project.settings.showGrid = true;
    this.salvo = this._estadoParaSalvar();
  }

  _estadoParaSalvar() {
    const { plan, walls, equipment } = this.project;
    return {
      projeto: {
        paredes: JSON.parse(JSON.stringify(walls)),
        ...(plan ? {
          largura_px: plan.widthPx,
          altura_px: plan.heightPx,
          escala_metros_por_pixel: plan.widthM / plan.widthPx,
        } : {}),
      },
      posicoes: Object.fromEntries(equipment.map(eq => [eq.id, eq.pendente ? null : {
        x: metros(eq.x),
        z: metros(eq.z),
        rotacao: metros(((eq.rotation % 360) + 360) % 360) % 360,
      }])),
    };
  }

  saveLocal() {
    if (this.gravacao) return this.gravacao.then(() => this.saveLocal());
    const estado = this._estadoParaSalvar();
    const posicoes = Object.fromEntries(Object.entries(estado.posicoes).filter(([id, posicao]) =>
      JSON.stringify(posicao) !== JSON.stringify(this.salvo.posicoes[id])));
    const projeto = JSON.stringify(estado.projeto) !== JSON.stringify(this.salvo.projeto)
      ? estado.projeto : null;
    if (!projeto && !Object.keys(posicoes).length) {
      this._dirty = false;
      this.emit("save:state", { state: "saved" });
      return Promise.resolve();
    }

    this.emit("save:state", { state: "saving" });
    this.gravacao = api.request("PUT", `/mapas/${this.plantaId}/estado`, {
      body: { projeto, posicoes }, planta: this.plantaId, enfileirar: false,
    }).then(() => {
      this.salvo = estado;
      this._dirty = JSON.stringify(this._estadoParaSalvar()) !== JSON.stringify(estado);
      this.emit("save:state", { state: this._dirty ? "saving" : "saved" });
    }).catch(erro => {
      this.emit("save:state", { state: "error", message: erro.message });
      throw erro;
    }).finally(() => { this.gravacao = null; });
    return this.gravacao;
  }

  scheduleSave() {
    this._dirty = true;
    this.emit("save:state", { state: "saving" });
    clearTimeout(this._saveTimer);
    this._saveTimer = setTimeout(() => this.saveLocal().catch(() => {}), 420);
  }

  flushSave() {
    clearTimeout(this._saveTimer);
    return this._dirty ? this.saveLocal() : Promise.resolve();
  }

  atualizarPlanta(projeto, imagemUrl) {
    this.project.plan = plantaDoProjeto(projeto, imagemUrl);
    this.salvo.projeto = this._estadoParaSalvar().projeto;
    this.clearHistory();
    this.emit("plan:change", this.project.plan);
  }

  setSettings(patch) {
    Object.assign(this.project.settings, patch);
    this.emit("settings:change", this.project.settings);
  }

  scaleBy(ratio) {
    const { plan, equipment, walls } = this.project;
    const valido = Number.isFinite(ratio) && ratio > 0 && plan && plan.widthM * ratio / plan.widthPx <= 5
      && equipment.every(eq => eq.pendente || Math.max(Math.abs(eq.x), Math.abs(eq.z)) * ratio <= 500)
      && walls.every(w => w.points.every(p => p.every(n => Math.abs(n * ratio) <= 500)));
    if (!valido) throw new Error("A escala produz medidas fora dos limites do mapa.");
    super.scaleBy(ratio);
  }
}
