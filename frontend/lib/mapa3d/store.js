/* Estado do projeto, persistência e histórico ------------------------------ */

import { Emitter, uid } from './util.js';
import { getType, STATUS_MAP } from './catalog.js';

const STORAGE_KEY = 'mapa3d.project.v1';
const HISTORY_LIMIT = 40;

export function createEmptyProject(name = 'Minha fábrica') {
  const now = new Date().toISOString();
  return {
    version: 1,
    name,
    isDemo: false,
    createdAt: now,
    updatedAt: now,
    plan: null,
    equipment: [],
    walls: [],
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

const num = (v, fallback = 0) => (Number.isFinite(Number(v)) ? Number(v) : fallback);
const safeId = (value, prefix) => (/^[A-Za-z0-9_-]{1,80}$/.test(String(value || '')) ? String(value) : uid(prefix));

export function normalizeProject(raw) {
  const base = createEmptyProject();
  if (!raw || typeof raw !== 'object') return base;
  const project = {
    ...base,
    ...raw,
    version: 1,
    name: String(raw.name || base.name).slice(0, 70),
    isDemo: !!raw.isDemo,
    createdAt: raw.createdAt || base.createdAt,
    updatedAt: raw.updatedAt || base.updatedAt,
    equipment: [],
    walls: [],
    settings: { ...base.settings, ...(raw.settings || {}) },
    plan: null,
  };

  if (Array.isArray(raw.equipment)) {
    project.equipment = raw.equipment
      .filter((e) => e && typeof e === 'object' && e.type)
      .map((e) => {
        const type = getType(e.type);
        const status = STATUS_MAP.has(e.status) ? e.status : 'online';
        return {
          id: safeId(e.id, 'eq'),
          type: String(e.type),
          name: String(e.name || type.label),
          tag: String(e.tag || ''),
          sector: String(e.sector || ''),
          status,
          ip: String(e.ip || ''),
          mac: String(e.mac || ''),
          model: String(e.model || ''),
          serial: String(e.serial || ''),
          responsible: String(e.responsible || ''),
          notes: String(e.notes || ''),
          x: num(e.x),
          z: num(e.z),
          rotation: num(e.rotation),
          elevation: num(e.elevation, type.elevation || 0),
          scale: Math.max(0.3, Math.min(3, num(e.scale, 1))),
          createdAt: e.createdAt || new Date().toISOString(),
          updatedAt: e.updatedAt || new Date().toISOString(),
        };
      });
  }

  if (Array.isArray(raw.walls)) {
    project.walls = raw.walls
      .map((w) => {
        const pts = Array.isArray(w?.points)
          ? w.points
              .map((p) => (Array.isArray(p) ? [num(p[0]), num(p[1])] : p && typeof p === 'object' ? [num(p.x), num(p.z)] : null))
              .filter(Boolean)
          : [];
        if (pts.length < 2) return null;
        return {
          id: safeId(w.id, 'wall'),
          points: pts,
          height: Math.max(0.1, num(w.height, 3)),
          thickness: Math.max(0.05, num(w.thickness, 0.16)),
        };
      })
      .filter(Boolean);
  }

  if (raw.plan && typeof raw.plan === 'object' && raw.plan.dataUrl) {
    const dataUrl = String(raw.plan.dataUrl);
    if (/^data:image\/(?:png|jpe?g|webp);base64,/i.test(dataUrl)) {
      const widthPx = Math.max(1, num(raw.plan.widthPx, 1600));
      const heightPx = Math.max(1, num(raw.plan.heightPx, 1000));
      const widthM = Math.max(1, num(raw.plan.widthM, 30));
      project.plan = {
        dataUrl,
        widthPx,
        heightPx,
        widthM,
        heightM: Math.max(0.5, num(raw.plan.heightM, (widthM * heightPx) / widthPx)),
        sourceName: String(raw.plan.sourceName || 'planta'),
        page: num(raw.plan.page, 1),
        createdAt: raw.plan.createdAt || new Date().toISOString(),
      };
    }
  }

  return project;
}

export function createEquipment(typeId, patch = {}) {
  const type = getType(typeId);
  const now = new Date().toISOString();
  return {
    id: uid('eq'),
    type: typeId,
    name: type.label,
    tag: '',
    sector: '',
    status: 'online',
    ip: '',
    mac: '',
    model: '',
    serial: '',
    responsible: '',
    notes: '',
    x: 0,
    z: 0,
    rotation: 0,
    elevation: type.elevation || 0,
    scale: 1,
    createdAt: now,
    updatedAt: now,
    ...patch,
  };
}

export class Store extends Emitter {
  constructor({ storage = globalThis.localStorage } = {}) {
    super();
    this.storage = storage;
    this.project = createEmptyProject();
    this.undoStack = [];
    this.redoStack = [];
    this._lastUndo = null;
    this._saveTimer = null;
    this._dirty = false;
  }

  /* ---------------- persistência ---------------- */

  hasSavedProject() {
    try {
      return !!this.storage.getItem(STORAGE_KEY);
    } catch {
      return false;
    }
  }

  load() {
    try {
      const raw = this.storage.getItem(STORAGE_KEY);
      if (!raw) return false;
      this.project = normalizeProject(JSON.parse(raw));
      this._dirty = false;
      return true;
    } catch (err) {
      console.warn('[Mapa3D] não foi possível ler o projeto salvo', err);
      return false;
    }
  }

  saveLocal({ silent = false } = {}) {
    if (!this.storage) return false;
    try {
      this.storage.setItem(STORAGE_KEY, JSON.stringify(this.project));
      this._dirty = false;
      if (!silent) this.emit('save:state', { state: 'saved' });
      return true;
    } catch (err) {
      console.warn('[Mapa3D] falha ao salvar', err);
      const quota = err && (err.name === 'QuotaExceededError' || err.code === 22 || err.code === 1014);
      this.emit('save:state', {
        state: 'error',
        message: quota
          ? 'Armazenamento local cheio. Exporte o projeto (.mapa3d) para não perder o trabalho.'
          : 'Não foi possível salvar automaticamente neste navegador.',
      });
      return false;
    }
  }

  scheduleSave() {
    this._dirty = true;
    this.emit('save:state', { state: 'saving' });
    clearTimeout(this._saveTimer);
    this._saveTimer = setTimeout(() => {
      this.saveLocal();
      this._saveTimer = null;
    }, 850);
  }

  flushSave() {
    clearTimeout(this._saveTimer);
    this._saveTimer = null;
    if (this._dirty) this.saveLocal({ silent: false });
  }

  /* ---------------- histórico ---------------- */

  _snapshot() {
    const { equipment, walls, settings, name, isDemo } = this.project;
    return JSON.stringify({ equipment, walls, settings, name, isDemo });
  }

  pushUndo(coalesceKey = null) {
    const now = Date.now();
    this.redoStack = [];
    if (coalesceKey && this._lastUndo && this._lastUndo.key === coalesceKey && now - this._lastUndo.time < 1600) {
      this._lastUndo.time = now;
      return;
    }
    this.undoStack.push(this._snapshot());
    if (this.undoStack.length > HISTORY_LIMIT) this.undoStack.shift();
    this._lastUndo = coalesceKey ? { key: coalesceKey, time: now } : null;
    this.emit('history', this.historyState());
  }

  historyState() {
    return { canUndo: this.undoStack.length > 0, canRedo: this.redoStack.length > 0, undo: this.undoStack.length, redo: this.redoStack.length };
  }

  clearHistory() {
    this.undoStack = [];
    this.redoStack = [];
    this._lastUndo = null;
    this.emit('history', this.historyState());
  }

  _restore(snap) {
    const data = JSON.parse(snap);
    this.project.equipment = data.equipment || [];
    this.project.walls = data.walls || [];
    this.project.settings = { ...this.project.settings, ...(data.settings || {}) };
    this.project.name = data.name || this.project.name;
    this.project.isDemo = !!data.isDemo;
    this.project.updatedAt = new Date().toISOString();
  }

  undo() {
    const snap = this.undoStack.pop();
    if (!snap) return false;
    this._lastUndo = null;
    this.redoStack.push(this._snapshot());
    this._restore(snap);
    this.emit('history', this.historyState());
    this.emit('sync');
    this._changed('undo');
    return true;
  }

  redo() {
    const snap = this.redoStack.pop();
    if (!snap) return false;
    this._lastUndo = null;
    this.undoStack.push(this._snapshot());
    this._restore(snap);
    this.emit('history', this.historyState());
    this.emit('sync');
    this._changed('redo');
    return true;
  }

  /* ---------------- notificações ---------------- */

  _changed(type, payload = {}) {
    this.project.updatedAt = new Date().toISOString();
    this.emit('change', { type, ...payload });
    this.scheduleSave();
  }

  markCustom() {
    if (this.project.isDemo) {
      this.project.isDemo = false;
      this.emit('demo:change', false);
    }
  }

  /* ---------------- projeto ---------------- */

  apply(project, { emit = true } = {}) {
    this.project = normalizeProject(project);
    this.clearHistory();
    this._dirty = true;
    if (emit) {
      this.emit('sync');
      this.emit('plan:change', this.project.plan);
      this.emit('settings:change', this.project.settings);
      this.emit('project:load', this.project);
      this.emit('demo:change', this.project.isDemo);
      this._changed('project:load');
    }
    return this.project;
  }

  newProject(name = 'Minha fábrica') {
    this.apply(createEmptyProject(name));
    this.emit('save:state', { state: 'saving' });
    this.saveLocal({ silent: true });
    this.emit('save:state', { state: 'saved' });
  }

  setName(name) {
    const clean = String(name || '').slice(0, 70) || 'Minha fábrica';
    if (clean === this.project.name) return;
    this.project.name = clean;
    this.markCustom();
    this.emit('project:name', clean);
    this._changed('project:name');
  }

  setPlan(plan) {
    this.project.plan = plan;
    this.project.updatedAt = new Date().toISOString();
    this.clearHistory();
    this.emit('plan:change', plan);
    this._changed('plan:change');
  }

  setSettings(patch, { coalesceKey = null } = {}) {
    const next = { ...this.project.settings, ...patch };
    if (JSON.stringify(next) === JSON.stringify(this.project.settings)) return;
    this.pushUndo(coalesceKey);
    this.project.settings = next;
    this.emit('settings:change', next);
    this._changed('settings:change');
  }

  /** Redimensiona a planta e reposiciona tudo proporcionalmente (calibração). */
  scaleBy(ratio) {
    if (!Number.isFinite(ratio) || ratio <= 0) return;
    if (Math.abs(ratio - 1) < 1e-6) return;
    if (this.project.plan) {
      this.project.plan.widthM *= ratio;
      this.project.plan.heightM *= ratio;
    }
    for (const item of this.project.equipment) {
      item.x *= ratio;
      item.z *= ratio;
      item.updatedAt = new Date().toISOString();
    }
    for (const wall of this.project.walls) {
      wall.points = wall.points.map(([x, z]) => [x * ratio, z * ratio]);
    }
    this.markCustom();
    this.clearHistory();
    this.emit('plan:change', this.project.plan);
    this.emit('sync');
    this._changed('plan:scale');
  }

  /* ---------------- equipamentos ---------------- */

  addEquipment(partial, { select = true } = {}) {
    this.pushUndo();
    const item = createEquipment(partial.type || 'desktop', partial);
    this.project.equipment.push(item);
    this.markCustom();
    this.emit('equipment:add', item);
    this._changed('equipment:add', { id: item.id });
    if (select) this.emit('request:select', { kind: 'equipment', id: item.id });
    return item;
  }

  updateEquipment(id, patch, { coalesceKey = null, touch = true } = {}) {
    const item = this.project.equipment.find((e) => e.id === id);
    if (!item) return null;
    const changes = {};
    for (const [key, value] of Object.entries(patch)) {
      if (key === 'id' || key === 'type') continue;
      if (item[key] !== value) changes[key] = value;
    }
    if (!Object.keys(changes).length) return item;
    this.pushUndo(coalesceKey);
    Object.assign(item, changes);
    if (touch) item.updatedAt = new Date().toISOString();
    this.markCustom();
    this.emit('equipment:update', { item, patch: changes });
    this._changed('equipment:update', { id });
    return item;
  }

  removeEquipment(id) {
    const index = this.project.equipment.findIndex((e) => e.id === id);
    if (index < 0) return false;
    this.pushUndo();
    const [item] = this.project.equipment.splice(index, 1);
    this.emit('equipment:remove', { id, item });
    this._changed('equipment:remove', { id });
    return true;
  }

  duplicateEquipment(id) {
    const source = this.project.equipment.find((e) => e.id === id);
    if (!source) return null;
    const copy = createEquipment(source.type, {
      ...source,
      id: uid('eq'),
      name: `${source.name} (cópia)`,
      x: source.x + 1,
      z: source.z + 1,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    });
    this.pushUndo();
    this.project.equipment.push(copy);
    this.markCustom();
    this.emit('equipment:add', copy);
    this._changed('equipment:duplicate', { id: copy.id });
    return copy;
  }

  /* ---------------- paredes ---------------- */

  addWall(points, opts = {}) {
    const clean = points.map(([x, z]) => [Number(x), Number(z)]).filter(([x, z]) => Number.isFinite(x) && Number.isFinite(z));
    if (clean.length < 2) return null;
    const wall = {
      id: uid('wall'),
      points: clean,
      height: opts.height ?? 3,
      thickness: opts.thickness ?? 0.16,
    };
    this.pushUndo();
    this.project.walls.push(wall);
    this.markCustom();
    this.emit('walls:change', this.project.walls);
    this._changed('wall:add', { id: wall.id });
    return wall;
  }

  updateWall(id, patch, { coalesceKey = null } = {}) {
    const wall = this.project.walls.find((w) => w.id === id);
    if (!wall) return null;
    const next = { ...wall, ...patch };
    if (next.height === wall.height && next.thickness === wall.thickness) return wall;
    this.pushUndo(coalesceKey);
    wall.height = Math.max(0.1, Number(next.height) || 3);
    wall.thickness = Math.max(0.05, Number(next.thickness) || 0.16);
    this.emit('walls:change', this.project.walls);
    this._changed('wall:update', { id });
    return wall;
  }

  removeWall(id) {
    const index = this.project.walls.findIndex((w) => w.id === id);
    if (index < 0) return false;
    this.pushUndo();
    this.project.walls.splice(index, 1);
    this.emit('walls:change', this.project.walls);
    this._changed('wall:remove', { id });
    return true;
  }

  findEquipment(id) {
    return this.project.equipment.find((e) => e.id === id) || null;
  }

  findWall(id) {
    return this.project.walls.find((w) => w.id === id) || null;
  }

  /* ---------------- exportação ---------------- */

  toExportObject() {
    return {
      app: 'mapa3d',
      version: 1,
      exportedAt: new Date().toISOString(),
      project: this.project,
    };
  }

  exportJSON() {
    return JSON.stringify(this.toExportObject(), null, 2);
  }

  exportCSV() {
    const head = ['Nome', 'Tipo', 'Categoria', 'TAG', 'Setor', 'Status', 'IP', 'MAC', 'Modelo', 'Nº série', 'Responsável', 'X (m)', 'Z (m)', 'Rotação (°)', 'Elevação (m)', 'Observações'];
    const rows = this.project.equipment.map((e) => {
      const t = getType(e.type);
      return [
        e.name,
        t.label,
        t.cat,
        e.tag,
        e.sector,
        e.status,
        e.ip,
        e.mac,
        e.model,
        e.serial,
        e.responsible,
        e.x.toFixed(2).replace('.', ','),
        e.z.toFixed(2).replace('.', ','),
        e.rotation.toFixed(0),
        e.elevation.toFixed(2).replace('.', ','),
        e.notes,
      ];
    });
    const esc = (v) => {
      let s = String(v ?? '');
      // evita injeção de fórmulas ao abrir o CSV no Excel
      if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
      return `"${s.replace(/"/g, '""')}"`;
    };
    return '\uFEFF' + [head, ...rows].map((r) => r.map(esc).join(';')).join('\r\n');
  }
}

export const STORAGE_PROJECT_KEY = STORAGE_KEY;
