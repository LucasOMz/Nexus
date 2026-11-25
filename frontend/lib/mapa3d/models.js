/* Modelos 3D procedurais dos equipamentos --------------------------------
   Cada modelo é construído em metros, com o piso em y = 0 e a frente para +Z.
   -------------------------------------------------------------------------- */

import * as THREE from '../three.module.js';

const matCache = new Map();
const basicCache = new Map();
const screenCache = new Map();
const textureCache = new Map();
const sphereGeo = new THREE.SphereGeometry(1, 10, 8);
const ringGeo = new THREE.RingGeometry(0.42, 0.5, 48);
sphereGeo.userData.shared = true;
ringGeo.userData.shared = true;

function M(color, opts = {}) {
  const key = [
    color,
    opts.roughness ?? 0.55,
    opts.metalness ?? 0.32,
    opts.emissive ?? 0,
    opts.emissiveIntensity ?? 1,
    opts.transparent ? 1 : 0,
    opts.opacity ?? 1,
    opts.side ?? 0,
    opts.depthWrite === false ? 0 : 1,
  ].join('|');
  let m = matCache.get(key);
  if (!m) {
    m = new THREE.MeshStandardMaterial({
      color: new THREE.Color(color),
      roughness: opts.roughness ?? 0.55,
      metalness: opts.metalness ?? 0.32,
      emissive: opts.emissive ?? 0x000000,
      emissiveIntensity: opts.emissiveIntensity ?? 1,
      transparent: !!opts.transparent,
      opacity: opts.opacity ?? 1,
      side: opts.side ?? THREE.FrontSide,
      depthWrite: opts.depthWrite !== false,
    });
    matCache.set(key, m);
  }
  return m;
}

function basic(color) {
  if (!basicCache.has(color)) {
    basicCache.set(color, new THREE.MeshBasicMaterial({ color: new THREE.Color(color), toneMapped: false }));
  }
  return basicCache.get(color);
}

function box(parent, w, h, d, material, x = 0, y = 0, z = 0, opts = {}) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
  mesh.position.set(x, y, z);
  if (opts.rx) mesh.rotation.x = opts.rx;
  if (opts.ry) mesh.rotation.y = opts.ry;
  if (opts.rz) mesh.rotation.z = opts.rz;
  mesh.castShadow = opts.cast !== false;
  mesh.receiveShadow = opts.receive !== false;
  parent.add(mesh);
  return mesh;
}

function cyl(parent, rTop, rBottom, h, material, x = 0, y = 0, z = 0, opts = {}) {
  const geo = new THREE.CylinderGeometry(rTop, rBottom, h, opts.segments || 20, 1, !!opts.open);
  const mesh = new THREE.Mesh(geo, material);
  mesh.position.set(x, y, z);
  if (opts.rx) mesh.rotation.x = opts.rx;
  if (opts.ry) mesh.rotation.y = opts.ry;
  if (opts.rz) mesh.rotation.z = opts.rz;
  mesh.castShadow = opts.cast !== false;
  mesh.receiveShadow = opts.receive !== false;
  parent.add(mesh);
  return mesh;
}

function sphere(parent, r, material, x = 0, y = 0, z = 0, opts = {}) {
  const mesh = new THREE.Mesh(sphereGeo, material);
  mesh.scale.set(r, opts.ry || r, r);
  mesh.position.set(x, y, z);
  mesh.castShadow = opts.cast !== false;
  mesh.receiveShadow = opts.receive !== false;
  parent.add(mesh);
  return mesh;
}

function led(parent, color, x, y, z, r = 0.012) {
  const mesh = new THREE.Mesh(sphereGeo, basic(color));
  mesh.scale.setScalar(r);
  mesh.position.set(x, y, z);
  parent.add(mesh);
  return mesh;
}

function screen(parent, w, h, x, y, z, accent = '#22d3ee', opts = {}) {
  const mat = screenMaterial(accent, opts.variant || 'monitor');
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h), mat);
  mesh.position.set(x, y, z);
  if (opts.rx) mesh.rotation.x = opts.rx;
  if (opts.ry) mesh.rotation.y = opts.ry;
  if (opts.rz) mesh.rotation.z = opts.rz;
  parent.add(mesh);
  return mesh;
}

function screenMaterial(accent, variant) {
  const key = `${accent}|${variant}`;
  if (screenCache.has(key)) return screenCache.get(key);
  const c = document.createElement('canvas');
  c.width = 256;
  c.height = 160;
  const ctx = c.getContext('2d');
  const bg = ctx.createLinearGradient(0, 0, 0, 160);
  bg.addColorStop(0, '#071420');
  bg.addColorStop(1, '#04101a');
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, 256, 160);

  ctx.fillStyle = accent;
  ctx.globalAlpha = 0.22;
  ctx.fillRect(0, 0, 256, 18);
  ctx.globalAlpha = 1;
  ctx.fillStyle = accent;
  ctx.fillRect(10, 6, 34, 5);
  ctx.globalAlpha = 0.5;
  for (let i = 0; i < 4; i++) ctx.fillRect(200 + i * 11, 6, 6, 5);
  ctx.globalAlpha = 1;

  if (variant === 'chart') {
    const bars = [44, 78, 34, 96, 58, 118, 72];
    bars.forEach((h, i) => {
      ctx.fillStyle = i % 2 ? 'rgba(52,211,153,.75)' : accent;
      ctx.globalAlpha = 0.55 + (i % 3) * 0.12;
      ctx.fillRect(16 + i * 32, 142 - h, 20, h);
    });
    ctx.globalAlpha = 1;
  } else if (variant === 'rack') {
    for (let i = 0; i < 8; i++) {
      ctx.fillStyle = 'rgba(148,163,184,.22)';
      ctx.fillRect(12, 30 + i * 15, 200, 8);
      ctx.fillStyle = accent;
      ctx.globalAlpha = 0.4 + (i % 3) * 0.2;
      ctx.fillRect(218, 32 + i * 15, 4, 4);
      ctx.globalAlpha = 1;
    }
  } else {
    ctx.globalAlpha = 0.55;
    ctx.fillStyle = accent;
    ctx.fillRect(14, 34, 86, 6);
    ctx.fillRect(14, 48, 58, 4);
    ctx.globalAlpha = 0.22;
    ctx.fillStyle = '#94a3b8';
    for (let i = 0; i < 7; i++) ctx.fillRect(14, 66 + i * 11, 120 + ((i * 37) % 70), 4);
    ctx.globalAlpha = 1;
    ctx.strokeStyle = accent;
    ctx.globalAlpha = 0.5;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(150, 118);
    ctx.lineTo(168, 100);
    ctx.lineTo(184, 108);
    ctx.lineTo(204, 76);
    ctx.lineTo(226, 86);
    ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.fillStyle = accent;
    ctx.beginPath();
    ctx.arc(226, 86, 3, 0, Math.PI * 2);
    ctx.fill();
  }

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  const mat = new THREE.MeshStandardMaterial({
    map: tex,
    emissive: 0xffffff,
    emissiveMap: tex,
    emissiveIntensity: variant === 'rack' ? 0.55 : 0.8,
    roughness: 0.35,
    metalness: 0.1,
  });
  screenCache.set(key, mat);
  return mat;
}

function stripeMaterial() {
  if (textureCache.has('stripe')) return textureCache.get('stripe');
  const c = document.createElement('canvas');
  c.width = 128;
  c.height = 64;
  const ctx = c.getContext('2d');
  ctx.fillStyle = '#facc15';
  ctx.fillRect(0, 0, 128, 64);
  ctx.fillStyle = '#111827';
  for (let x = -64; x < 160; x += 32) {
    ctx.beginPath();
    ctx.moveTo(x, 64);
    ctx.lineTo(x + 16, 64);
    ctx.lineTo(x + 48, 0);
    ctx.lineTo(x + 32, 0);
    ctx.closePath();
    ctx.fill();
  }
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  const mat = new THREE.MeshStandardMaterial({ map: tex, roughness: 0.7, metalness: 0.1 });
  textureCache.set('stripe', mat);
  return mat;
}

function ensurePulse(group) {
  if (!group.userData.pulseRings) group.userData.pulseRings = [];
  return group.userData.pulseRings;
}

function radioRing(parent, radius, color, y, opacity = 0.3) {
  const mat = new THREE.MeshBasicMaterial({
    color: new THREE.Color(color),
    transparent: true,
    opacity,
    side: THREE.DoubleSide,
    depthWrite: false,
    toneMapped: false,
  });
  const mesh = new THREE.Mesh(new THREE.TorusGeometry(radius, 0.006, 6, 40), mat);
  mesh.rotation.x = Math.PI / 2;
  mesh.position.y = y;
  parent.add(mesh);
  return mesh;
}

function newGroup(typeId) {
  const g = new THREE.Group();
  g.userData.typeId = typeId;
  return g;
}

const C = {
  shell: '#cbd5e1',
  shellDark: '#94a3b8',
  dark: '#1e293b',
  darker: '#0f172a',
  steel: '#64748b',
  steelLight: '#94a3b8',
  black: '#0b1220',
  white: '#e2e8f0',
  red: '#dc2626',
  redDark: '#991b1b',
  yellow: '#f59e0b',
  green: '#16a34a',
  wood: '#a16207',
  cardboard: '#b45309',
  glass: '#7dd3fc',
  cyan: '#22d3ee',
  blue: '#3b82f6',
};

/* ============================ TI & REDE ============================ */

function desktop() {
  const g = newGroup('desktop');
  const shell = M('#1f2937', { roughness: 0.5, metalness: 0.45 });
  const panel = M('#0f172a', { roughness: 0.35, metalness: 0.55 });

  // Gabinete
  box(g, 0.2, 0.44, 0.42, shell, 0.27, 0.24, 0);
  box(g, 0.17, 0.35, 0.006, panel, 0.27, 0.25, 0.213);
  led(g, '#34d399', 0.33, 0.4, 0.219, 0.008);
  box(g, 0.03, 0.04, 0.01, M('#334155'), 0.21, 0.4, 0.218);
  for (let i = 0; i < 3; i++) box(g, 0.16, 0.004, 0.3, M('#0b1220', { roughness: 0.9 }), 0.27, 0.45, 0, { cast: false });

  // Monitor
  cyl(g, 0.12, 0.13, 0.012, panel, -0.06, 0.008, 0.02);
  box(g, 0.055, 0.2, 0.04, shell, -0.06, 0.11, -0.01);
  box(g, 0.54, 0.33, 0.028, panel, -0.06, 0.39, 0.0);
  screen(g, 0.49, 0.275, -0.06, 0.39, 0.016, '#22d3ee');
  led(g, '#34d399', 0.17, 0.25, 0.015, 0.006);

  // Teclado e mouse
  box(g, 0.32, 0.014, 0.12, M('#111827'), -0.04, 0.008, 0.27);
  for (let r = 0; r < 3; r++) {
    for (let k = 0; k < 9; k++) {
      box(g, 0.024, 0.003, 0.02, M('#334155'), -0.17 + k * 0.032, 0.017, 0.24 + r * 0.03, { cast: false });
    }
  }
  box(g, 0.055, 0.02, 0.085, shell, 0.23, 0.012, 0.27, { ry: 0.1 });
  return g;
}

function notebook() {
  const g = newGroup('notebook');
  const shell = M('#334155', { roughness: 0.42, metalness: 0.55 });
  box(g, 0.36, 0.018, 0.26, shell, 0, 0.012, 0);
  box(g, 0.3, 0.003, 0.1, M('#0f172a'), 0, 0.022, 0.03, { cast: false });

  const lid = new THREE.Group();
  lid.position.set(0, 0.02, -0.13);
  lid.rotation.x = -0.2;
  g.add(lid);
  box(lid, 0.36, 0.23, 0.012, shell, 0, 0.115, 0);
  screen(lid, 0.325, 0.195, 0, 0.115, 0.007, '#22d3ee');
  return g;
}

function server() {
  const g = newGroup('server');
  const shell = M('#1e293b', { roughness: 0.4, metalness: 0.55 });
  box(g, 0.5, 0.05, 0.62, M('#0f172a'), 0, 0.025, 0);
  box(g, 0.46, 0.72, 0.58, shell, 0, 0.41, 0);
  box(g, 0.42, 0.62, 0.008, M('#0b1220', { roughness: 0.3, metalness: 0.4 }), 0, 0.43, 0.295);
  for (let i = 0; i < 6; i++) {
    box(g, 0.36, 0.06, 0.012, M('#334155', { metalness: 0.6 }), 0, 0.2 + i * 0.085, 0.3, { cast: false });
    led(g, i === 2 ? '#fbbf24' : '#34d399', 0.15, 0.2 + i * 0.085, 0.308, 0.007);
  }
  for (let i = 0; i < 4; i++) box(g, 0.3, 0.005, 0.4, M('#0f172a'), 0, 0.79, 0, { cast: false });
  // pés
  [[-0.2, 0.28], [0.2, 0.28], [-0.2, -0.28], [0.2, -0.28]].forEach(([x, z]) => cyl(g, 0.02, 0.025, 0.04, M('#111827'), x, 0.02, z));
  return g;
}

function rack() {
  const g = newGroup('rack');
  const frame = M('#1f2937', { roughness: 0.38, metalness: 0.6 });
  const glass = M(C.glass, { transparent: true, opacity: 0.13, roughness: 0.05, metalness: 0.25, side: THREE.DoubleSide, depthWrite: false });

  box(g, 0.62, 0.05, 0.82, M('#0f172a'), 0, 0.04, 0);
  box(g, 0.035, 1.82, 0.82, frame, -0.3, 0.95, 0);
  box(g, 0.035, 1.82, 0.82, frame, 0.3, 0.95, 0);
  box(g, 0.6, 0.035, 0.82, frame, 0, 1.86, 0);
  box(g, 0.6, 1.8, 0.035, frame, 0, 0.95, -0.4);
  box(g, 0.56, 1.72, 0.012, glass, 0, 0.95, 0.405);
  box(g, 0.04, 1.72, 0.04, frame, -0.27, 0.95, 0.4);
  box(g, 0.04, 1.72, 0.04, frame, 0.27, 0.95, 0.4);

  for (let i = 0; i < 7; i++) {
    const y = 0.26 + i * 0.225;
    box(g, 0.48, 0.16, 0.54, M('#111827', { metalness: 0.4 }), 0, y, 0.02);
    box(g, 0.44, 0.12, 0.01, M('#1e293b'), 0, y, 0.295);
    led(g, i === 3 ? '#fbbf24' : '#34d399', 0.19, y + 0.03, 0.302, 0.007);
    led(g, '#38bdf8', 0.16, y + 0.03, 0.302, 0.005);
  }
  cyl(g, 0.13, 0.13, 0.02, M('#0f172a'), 0, 1.88, 0);
  for (let i = 0; i < 5; i++) box(g, 0.26, 0.004, 0.02, M('#334155'), 0, 1.892, -0.08 + i * 0.04, { cast: false });
  return g;
}

function switchModel() {
  const g = newGroup('switch');
  const shell = M('#1f2937', { roughness: 0.4, metalness: 0.55 });
  box(g, 0.46, 0.075, 0.28, shell, 0, 0.105, 0);
  box(g, 0.44, 0.012, 0.26, M('#0f172a'), 0, 0.065, 0);
  [[-0.18, 0.15], [0.18, 0.15], [-0.18, -0.15], [0.18, -0.15]].forEach(([x, z]) => cyl(g, 0.018, 0.02, 0.02, M('#111827'), x, 0.01, z));
  box(g, 0.4, 0.03, 0.01, M('#0b1220'), 0, 0.115, 0.141);
  for (let i = 0; i < 12; i++) {
    box(g, 0.02, 0.016, 0.008, M('#334155'), -0.19 + i * 0.032, 0.108, 0.147, { cast: false });
    led(g, i % 4 === 0 ? '#38bdf8' : '#34d399', -0.19 + i * 0.032, 0.13, 0.148, 0.0045);
  }
  led(g, '#34d399', 0.19, 0.125, 0.148, 0.006);
  led(g, '#fbbf24', 0.16, 0.125, 0.148, 0.006);
  return g;
}

function router() {
  const g = newGroup('router');
  const shell = M('#1f2937', { roughness: 0.4, metalness: 0.5 });
  box(g, 0.32, 0.1, 0.24, shell, 0, 0.08, 0);
  box(g, 0.29, 0.02, 0.21, M('#0f172a'), 0, 0.035, 0);
  [[-0.11, -0.06], [0, -0.08], [0.11, -0.06]].forEach(([x, z], i) => {
    const a = cyl(g, 0.008, 0.008, 0.2, M('#111827'), x, 0.22, z, { rx: -0.18 });
    a.rotation.z = (i - 1) * 0.08;
  });
  for (let i = 0; i < 4; i++) led(g, i === 0 ? '#38bdf8' : '#34d399', -0.1 + i * 0.05, 0.115, 0.121, 0.006);
  return g;
}

function ap() {
  const g = newGroup('ap');
  const shell = M('#e2e8f0', { roughness: 0.5, metalness: 0.2 });
  cyl(g, 0.06, 0.07, 0.02, M('#94a3b8'), 0, 0.01, 0);
  cyl(g, 0.19, 0.19, 0.05, shell, 0, -0.03, 0, { segments: 36 });
  cyl(g, 0.175, 0.175, 0.004, M('#0f172a'), 0, -0.057, 0, { segments: 36 });
  const ring = new THREE.Mesh(new THREE.TorusGeometry(0.13, 0.006, 8, 40), basic('#22d3ee'));
  ring.rotation.x = Math.PI / 2;
  ring.position.y = -0.06;
  g.add(ring);
  led(g, '#34d399', 0.06, -0.03, 0.18, 0.008);

  const rings = ensurePulse(g);
  [[0.26, 0.26], [0.36, 0.16], [0.46, 0.08]].forEach(([r, o]) => {
    const rr = radioRing(g, r, '#22d3ee', -0.075, o);
    rr.userData.phase = r * 6;
    rings.push(rr);
  });
  return g;
}

function antenna() {
  const g = newGroup('antenna');
  const metal = M('#94a3b8', { roughness: 0.4, metalness: 0.7 });
  box(g, 0.28, 0.035, 0.28, M('#1f2937'), 0, 0.02, 0);
  cyl(g, 0.03, 0.045, 2.15, metal, 0, 1.1, 0);
  box(g, 0.05, 0.05, 0.05, M('#334155'), 0, 1.95, 0);
  const panel = box(g, 0.3, 0.5, 0.07, M('#e2e8f0', { roughness: 0.5 }), 0, 2.0, 0.07, { rx: -0.08 });
  box(panel, 0.26, 0.44, 0.01, M('#dbeafe'), 0, 0, 0.04, { cast: false });
  cyl(g, 0.012, 0.012, 1.9, M('#111827'), 0.04, 1.05, -0.06);
  const rings = ensurePulse(g);
  [0.3, 0.5].forEach((r, i) => {
    const rr = radioRing(g, r, '#38bdf8', 2.25 + i * 0.08, 0.22);
    rr.userData.phase = i * 2;
    rings.push(rr);
  });
  led(g, '#34d399', 0.02, 1.9, 0.12, 0.01);
  return g;
}

function camera() {
  const g = newGroup('camera');
  cyl(g, 0.07, 0.08, 0.025, M('#e2e8f0'), 0, -0.012, 0);
  cyl(g, 0.025, 0.03, 0.09, M('#94a3b8'), 0, -0.06, 0);
  const head = new THREE.Group();
  head.position.set(0, -0.14, 0);
  head.rotation.x = 0.38;
  g.add(head);
  box(head, 0.15, 0.14, 0.3, M('#e2e8f0', { roughness: 0.45, metalness: 0.2 }), 0, 0, 0);
  box(head, 0.16, 0.045, 0.31, M('#cbd5e1'), 0, 0.085, 0.01);
  cyl(head, 0.055, 0.06, 0.05, M('#0f172a'), 0, 0, 0.16, { rx: Math.PI / 2 });
  cyl(head, 0.04, 0.04, 0.02, basic('#0ea5e9'), 0, 0, 0.185, { rx: Math.PI / 2 });
  for (let i = 0; i < 6; i++) {
    const a = (i / 6) * Math.PI * 2;
    led(head, '#f87171', Math.cos(a) * 0.042, Math.sin(a) * 0.042, 0.155, 0.007);
  }
  led(g, '#34d399', 0.05, -0.1, 0.1, 0.006);
  const rings = ensurePulse(g);
  const rr = radioRing(g, 0.3, '#f87171', -0.34, 0.15);
  rr.userData.phase = 1;
  rings.push(rr);
  return g;
}

function printer(compact = false) {
  const g = newGroup('printer');
  const carcaca = M('#dfded8', { roughness: 0.66, metalness: 0 });
  const tampa = M('#f5f2eb', { roughness: 0.62, metalness: 0 });
  const grafite = M('#28313b', { roughness: 0.78, metalness: 0 });
  const carenagem = compact ? box : carenagemImpressora;

  carenagem(g, 0.51, 0.045, 0.46, grafite, 0, 0.0225, 0);
  carenagem(g, 0.55, 0.3, 0.51, carcaca, 0, 0.19, 0);
  box(g, 0.53, 0.18, 0.13, grafite, 0, 0.42, -0.18);
  for (const x of [-0.23, 0.23]) box(g, 0.09, 0.18, 0.49, carcaca, x, 0.42, 0);
  carenagem(g, 0.57, 0.076, 0.54, tampa, 0, 0.548, -0.008);
  carenagem(g, 0.50, 0.044, 0.39, tampa, 0, 0.608, -0.06);
  box(g, 0.40, 0.018, 0.35, grafite, 0, 0.348, 0.085);
  box(g, 0.21, 0.004, 0.22, basic('#fdfdf8'), -0.025, 0.36, 0.187, { rx: -0.035, cast: false });
  if (compact) return g;

  const gaveta = M('#c6cbd0', { roughness: 0.66, metalness: 0 });
  for (const y of [0.106, 0.22]) {
    carenagem(g, 0.49, 0.104, 0.026, gaveta, 0, y, 0.264);
    box(g, 0.14, 0.018, 0.004, grafite, 0, y + 0.022, 0.278, { cast: false });
  }
  box(g, 0.468, 0.012, 0.345, grafite, 0, 0.589, -0.06);
  const painel = carenagem(g, 0.145, 0.07, 0.032, grafite, 0.20, 0.495, 0.265);
  painel.rotation.x = -0.25;
  box(painel, 0.086, 0.041, 0.003, basic('#79a9bf'), -0.015, 0.005, 0.017, { cast: false });
  box(painel, 0.019, 0.014, 0.003, tampa, 0.049, 0.005, 0.017, { cast: false });
  for (let i = 0; i < 3; i++) {
    box(g, 0.104 - i * 0.017, 0.001, 0.005, basic('#93a4b0'), -0.045, 0.361 + i * 0.0005, 0.22 + i * 0.015, { cast: false });
  }
  return g;
}

function carenagemImpressora(parent, w, h, d, material, x, y, z) {
  const bevel = Math.min(0.009, w / 8, h / 4, d / 4);
  const largura = w / 2 - bevel;
  const fundo = d / 2 - bevel;
  const forma = new THREE.Shape();
  forma.moveTo(-largura, -fundo);
  forma.lineTo(largura, -fundo);
  forma.lineTo(largura, fundo);
  forma.lineTo(-largura, fundo);
  forma.closePath();
  const corpo = new THREE.ExtrudeGeometry(forma, {
    depth: h - 2 * bevel, bevelSize: bevel, bevelThickness: bevel, bevelSegments: 2,
  });
  corpo.rotateX(-Math.PI / 2);
  corpo.center();
  const mesh = new THREE.Mesh(corpo, material);
  mesh.position.set(x, y, z);
  parent.add(mesh);
  return mesh;
}

function nobreak() {
  const g = newGroup('nobreak');
  const shell = M('#1f2937', { roughness: 0.45, metalness: 0.45 });
  box(g, 0.22, 0.38, 0.32, shell, 0, 0.19, 0);
  box(g, 0.2, 0.09, 0.01, M('#0f172a'), 0, 0.32, 0.161);
  screen(g, 0.1, 0.045, 0, 0.32, 0.167, '#34d399');
  led(g, '#34d399', -0.07, 0.32, 0.168, 0.006);
  led(g, '#fbbf24', 0.07, 0.32, 0.168, 0.006);
  for (let i = 0; i < 3; i++) box(g, 0.05, 0.03, 0.01, M('#334155'), -0.06 + i * 0.06, 0.12, 0.164, { cast: false });
  for (let i = 0; i < 4; i++) box(g, 0.16, 0.004, 0.005, M('#0f172a'), 0, 0.06 + i * 0.012, 0.162, { cast: false });
  return g;
}

function phone() {
  const g = newGroup('phone');
  const shell = M('#1f2937', { roughness: 0.5, metalness: 0.3 });
  box(g, 0.22, 0.04, 0.18, shell, 0, 0.02, 0);
  box(g, 0.07, 0.02, 0.045, M('#e2e8f0'), 0, 0.055, -0.055);
  box(g, 0.05, 0.02, 0.04, M('#e2e8f0'), 0.075, 0.055, -0.055);
  box(g, 0.15, 0.012, 0.02, M('#e2e8f0'), 0.03, 0.062, -0.055);
  screen(g, 0.06, 0.032, 0, 0.044, 0.091, '#22d3ee');
  for (let r = 0; r < 2; r++) for (let k = 0; k < 3; k++) box(g, 0.018, 0.004, 0.012, M('#475569'), -0.03 + k * 0.03, 0.041, 0.03 + r * 0.03, { cast: false });
  return g;
}

/* ============================ PRODUÇÃO ============================ */

function cnc() {
  const g = newGroup('cnc');
  const shell = M('#dbe3ec', { roughness: 0.45, metalness: 0.3 });
  const dark = M('#1e293b', { roughness: 0.5, metalness: 0.5 });

  box(g, 2.2, 0.25, 1.6, M('#334155', { roughness: 0.55, metalness: 0.5 }), 0, 0.125, 0);
  box(g, 2.24, 0.07, 1.64, stripeMaterial(), 0, 0.035, 0);
  box(g, 2.08, 1.55, 1.5, shell, 0, 1.03, 0);
  box(g, 1.86, 1.35, 0.02, M('#0f172a'), 0, 1.03, 0.755, { cast: false });

  // Janela com interior iluminado
  box(g, 1.38, 0.98, 0.04, M('#7dd3fc', { transparent: true, opacity: 0.16, roughness: 0.05, metalness: 0.2, depthWrite: false }), -0.18, 1.17, 0.77);
  box(g, 1.3, 0.9, 0.02, M('#0b1622', { emissive: 0x0e7490, emissiveIntensity: 0.32 }), -0.18, 1.17, 0.735, { cast: false });
  box(g, 0.62, 0.06, 0.5, M('#64748b', { metalness: 0.7 }), -0.18, 0.78, 0.48);
  cyl(g, 0.07, 0.07, 0.42, M('#cbd5e1', { metalness: 0.8, roughness: 0.3 }), -0.18, 1.22, 0.48);
  cyl(g, 0.035, 0.035, 0.18, M('#f59e0b', { metalness: 0.6 }), -0.18, 1.02, 0.48);
  box(g, 0.06, 0.6, 0.04, M('#334155'), -0.75, 1.0, 0.76);

  // Painel de comando
  const cp = new THREE.Group();
  cp.position.set(0.62, 1.25, 0.82);
  cp.rotation.x = -0.1;
  g.add(cp);
  box(cp, 0.56, 0.4, 0.12, dark, 0, 0, 0);
  screen(cp, 0.36, 0.24, -0.07, 0.02, 0.065, '#22d3ee', { variant: 'chart' });
  for (let i = 0; i < 3; i++) cyl(cp, 0.022, 0.022, 0.02, i === 0 ? M('#dc2626') : M('#334155'), 0.18, 0.1 - i * 0.09, 0.065, { rx: Math.PI / 2 });

  // Detalhes
  box(g, 2.12, 0.05, 1.54, M('#94a3b8'), 0, 1.82, 0);
  cyl(g, 0.05, 0.05, 0.12, M('#f59e0b', { emissive: 0xf59e0b, emissiveIntensity: 0.25 }), 0.7, 1.92, 0.4);
  for (let i = 0; i < 5; i++) box(g, 0.012, 0.34, 0.5, M('#94a3b8'), 1.045, 1.03, -0.45 + i * 0.22, { cast: false });
  for (let i = 0; i < 4; i++) cyl(g, 0.03, 0.035, 0.1, dark, -0.9 + i * 0.6, 0.06, 0.7);
  return g;
}

function conveyor() {
  const g = newGroup('conveyor');
  const steel = M('#94a3b8', { roughness: 0.4, metalness: 0.7 });
  box(g, 2.5, 0.05, 0.58, M('#111827', { roughness: 0.9 }), 0, 0.57, 0);
  box(g, 2.5, 0.08, 0.05, steel, 0, 0.63, 0.31);
  box(g, 2.5, 0.08, 0.05, steel, 0, 0.63, -0.31);
  for (let i = 0; i < 9; i++) cyl(g, 0.028, 0.028, 0.54, M('#475569'), -1.1 + i * 0.275, 0.545, 0, { rx: Math.PI / 2, segments: 10, cast: false });
  [[-1.23, 0], [1.23, 0]].forEach(([x]) => cyl(g, 0.075, 0.075, 0.62, steel, x, 0.57, 0, { rx: Math.PI / 2 }));
  [[-1.1, 0.27], [1.1, 0.27], [-1.1, -0.27], [1.1, -0.27]].forEach(([x, z]) => box(g, 0.07, 0.53, 0.07, steel, x, 0.265, z));
  box(g, 0.35, 0.35, 0.22, M('#1f2937'), 1.05, 0.85, 0.42);
  screen(g, 0.16, 0.1, 1.05, 0.87, 0.535, '#22d3ee');
  cyl(g, 0.025, 0.025, 0.35, steel, 1.05, 0.68, 0.42);
  cyl(g, 0.09, 0.09, 0.18, M('#334155'), -1.24, 0.57, 0.38, { rx: Math.PI / 2 });

  // Caixas sobre a esteira
  box(g, 0.34, 0.28, 0.34, M(C.cardboard, { roughness: 0.85 }), -0.55, 0.75, 0);
  box(g, 0.35, 0.02, 0.35, M('#d6b17a'), -0.55, 0.89, 0, { cast: false });
  box(g, 0.26, 0.22, 0.26, M(C.cardboard, { roughness: 0.85 }), 0.5, 0.72, 0.02);
  return g;
}

function lathe() {
  const g = newGroup('lathe');
  const steel = M('#94a3b8', { roughness: 0.35, metalness: 0.8 });
  const body = M('#334155', { roughness: 0.5, metalness: 0.55 });
  [[-0.7], [0.7]].forEach(([x]) => box(g, 0.32, 0.55, 0.62, body, x, 0.275, 0));
  box(g, 2.0, 0.18, 0.56, body, 0, 0.64, 0);
  box(g, 1.9, 0.05, 0.5, M('#1e293b'), 0, 0.745, 0, { cast: false });
  box(g, 0.42, 0.58, 0.56, M('#475569'), -0.75, 0.95, 0);
  cyl(g, 0.19, 0.19, 0.13, steel, -0.54, 0.95, 0, { rz: Math.PI / 2 });
  for (let i = 0; i < 3; i++) {
    const a = (i / 3) * Math.PI * 2;
    box(g, 0.05, 0.08, 0.05, M('#64748b'), -0.47, 0.95 + Math.sin(a) * 0.12, Math.cos(a) * 0.12);
  }
  box(g, 0.3, 0.35, 0.38, body, 0.68, 0.9, 0);
  cyl(g, 0.045, 0.045, 0.22, steel, 0.52, 0.95, 0, { rz: Math.PI / 2 });
  box(g, 0.26, 0.16, 0.4, M('#475569'), 0.05, 0.82, 0);
  box(g, 0.1, 0.22, 0.12, M('#1f2937'), 0.05, 0.98, 0.08);
  box(g, 0.3, 0.26, 0.05, M('#1f2937'), 0.72, 1.12, 0.28);
  screen(g, 0.2, 0.13, 0.72, 1.13, 0.31, '#22d3ee');
  cyl(g, 0.13, 0.13, 0.4, body, -0.85, 0.95, -0.3, { rz: Math.PI / 2 });
  led(g, '#34d399', -0.85, 1.08, -0.15, 0.01);
  return g;
}

function press() {
  const g = newGroup('press');
  const steel = M('#94a3b8', { roughness: 0.4, metalness: 0.75 });
  const body = M('#334155', { roughness: 0.5, metalness: 0.55 });
  box(g, 1.4, 0.28, 1.0, body, 0, 0.14, 0);
  box(g, 1.42, 0.06, 1.02, stripeMaterial(), 0, 0.31, 0);
  [[-0.55, 0.36], [0.55, 0.36], [-0.55, -0.36], [0.55, -0.36]].forEach(([x, z]) => cyl(g, 0.06, 0.07, 1.75, steel, x, 1.16, z));
  box(g, 1.42, 0.3, 1.02, body, 0, 2.05, 0);
  box(g, 0.9, 0.55, 0.66, M('#475569'), 0, 1.15, 0);
  box(g, 0.9, 0.08, 0.7, steel, 0, 1.43, 0);
  box(g, 0.9, 0.12, 0.7, steel, 0, 0.72, 0);
  box(g, 0.7, 0.3, 0.5, M('#1f2937'), 0, 0.52, 0);
  box(g, 0.36, 0.4, 0.28, body, 0.85, 1.0, 0.34);
  screen(g, 0.2, 0.13, 0.85, 1.03, 0.485, '#22d3ee');
  cyl(g, 0.045, 0.045, 0.03, M('#dc2626'), 0.96, 0.86, 0.485, { rx: Math.PI / 2 });
  box(g, 0.05, 0.9, 0.8, M('#7dd3fc', { transparent: true, opacity: 0.12, depthWrite: false }), -0.72, 0.95, 0.3, { cast: false });
  led(g, '#fbbf24', 0.78, 1.2, 0.48, 0.012);
  return g;
}

function workbench() {
  const g = newGroup('workbench');
  const wood = M('#b08d57', { roughness: 0.85, metalness: 0.05 });
  const steel = M('#475569', { roughness: 0.45, metalness: 0.65 });
  box(g, 1.8, 0.08, 0.8, wood, 0, 0.9, 0);
  [[-0.8, 0.32], [0.8, 0.32], [-0.8, -0.32], [0.8, -0.32]].forEach(([x, z]) => box(g, 0.07, 0.86, 0.07, steel, x, 0.43, z));
  box(g, 1.62, 0.04, 0.66, steel, 0, 0.3, 0);
  box(g, 1.6, 0.6, 0.025, M('#64748b', { roughness: 0.9 }), 0, 1.28, -0.38);
  for (let r = 0; r < 4; r++) for (let c = 0; c < 8; c++) box(g, 0.012, 0.012, 0.004, M('#1f2937'), -0.6 + c * 0.17, 1.05 + r * 0.12, -0.394, { cast: false });
  box(g, 0.5, 0.55, 0.6, M('#334155'), 0.55, 0.58, 0);
  for (let i = 0; i < 3; i++) box(g, 0.44, 0.006, 0.01, M('#0f172a'), 0.55, 0.4 + i * 0.16, 0.305, { cast: false });
  box(g, 0.18, 0.12, 0.22, M('#1f2937'), -0.55, 0.99, 0.12);
  box(g, 0.06, 0.16, 0.06, steel, -0.55, 1.08, -0.06);
  box(g, 0.2, 0.04, 0.24, steel, -0.55, 1.17, 0.04);
  box(g, 0.32, 0.14, 0.18, M('#dc2626', { roughness: 0.6 }), 0.1, 1.01, 0.1);
  box(g, 0.28, 0.02, 0.06, M('#111827'), 0.1, 1.08, 0.1, { cast: false });
  for (let i = 0; i < 4; i++) box(g, 0.14, 0.18, 0.02, M(['#1d4ed8', '#b91c1c', '#047857', '#a16207'][i], { roughness: 0.6 }), -0.15 + i * 0.16, 1.25, -0.36, { cast: false });
  return g;
}

/* ============================ INFRAESTRUTURA ============================ */

function panel() {
  const g = newGroup('panel');
  const shell = M('#cbd5e1', { roughness: 0.5, metalness: 0.3 });
  box(g, 0.86, 0.08, 0.34, M('#334155'), 0, 0.04, 0);
  box(g, 0.8, 1.85, 0.32, shell, 0, 0.98, 0);
  box(g, 0.37, 1.68, 0.02, M('#e2e8f0'), -0.2, 0.98, 0.17);
  box(g, 0.37, 1.68, 0.02, M('#e2e8f0'), 0.2, 0.98, 0.17);
  box(g, 0.012, 0.1, 0.03, M('#475569'), -0.03, 0.98, 0.185);
  box(g, 0.012, 0.1, 0.03, M('#475569'), 0.03, 0.98, 0.185);
  for (let i = 0; i < 5; i++) box(g, 0.24, 0.008, 0.01, M('#94a3b8'), 0, 0.35 + i * 0.045, 0.181, { cast: false });
  screen(g, 0.15, 0.1, 0.2, 1.5, 0.185, '#34d399', { variant: 'chart' });
  box(g, 0.12, 0.12, 0.005, M('#facc15'), -0.2, 1.7, 0.184, { cast: false });
  box(g, 0.09, 0.09, 0.004, M('#111827'), -0.2, 1.7, 0.188, { cast: false });
  cyl(g, 0.04, 0.04, 0.35, M('#64748b'), -0.2, 2.05, 0.04);
  led(g, '#34d399', 0.3, 1.78, 0.184, 0.008);
  return g;
}

function compressor() {
  const g = newGroup('compressor');
  const body = M('#334155', { roughness: 0.45, metalness: 0.6 });
  const steel = M('#94a3b8', { roughness: 0.35, metalness: 0.8 });
  cyl(g, 0.3, 0.3, 1.05, M('#1f2937', { roughness: 0.4, metalness: 0.65 }), -0.05, 0.42, 0, { rz: Math.PI / 2 });
  sphere(g, 0.3, M('#1f2937', { roughness: 0.4, metalness: 0.65 }), -0.575, 0.42, 0, { ry: 0.3 });
  sphere(g, 0.3, M('#1f2937', { roughness: 0.4, metalness: 0.65 }), 0.475, 0.42, 0, { ry: 0.3 });
  [[-0.45, 0.22], [0.35, 0.22], [-0.45, -0.22], [0.35, -0.22]].forEach(([x, z]) => box(g, 0.1, 0.12, 0.1, body, x, 0.06, z));
  box(g, 0.42, 0.32, 0.36, body, -0.08, 0.86, 0);
  for (let i = 0; i < 5; i++) box(g, 0.3, 0.01, 0.02, M('#0f172a'), -0.08, 0.76 + i * 0.045, 0.185, { rz: 0.2, cast: false });
  box(g, 0.32, 0.28, 0.28, M('#475569'), 0.36, 0.86, 0);
  cyl(g, 0.12, 0.12, 0.12, steel, 0.16, 0.86, 0.14, { rx: Math.PI / 2 });
  cyl(g, 0.035, 0.035, 0.55, steel, 0.4, 1.05, 0.1, { rx: Math.PI / 2 });
  cyl(g, 0.04, 0.04, 0.22, steel, 0.42, 1.2, 0.1);
  cyl(g, 0.075, 0.075, 0.03, M('#e2e8f0'), 0.42, 1.32, 0.1, { rx: Math.PI / 2 });
  box(g, 0.06, 0.15, 0.03, M('#facc15'), -0.05, 1.1, 0.19, { rx: 0.15, cast: false });
  led(g, '#34d399', 0.2, 1.12, 0.17, 0.01);
  return g;
}

function ac() {
  const g = newGroup('ac');
  const shell = M('#f1f5f9', { roughness: 0.6, metalness: 0.1 });
  box(g, 0.98, 0.28, 0.22, shell, 0, 0, 0);
  box(g, 0.98, 0.02, 0.24, M('#cbd5e1'), 0, 0.15, 0);
  box(g, 0.86, 0.1, 0.01, M('#0f172a'), 0, -0.03, 0.115);
  for (let i = 0; i < 5; i++) box(g, 0.82, 0.008, 0.02, M('#cbd5e1'), 0, -0.07 + i * 0.02, 0.13, { cast: false });
  screen(g, 0.08, 0.025, 0.38, 0.07, 0.116, '#34d399');
  led(g, '#34d399', 0.3, 0.07, 0.116, 0.006);
  box(g, 0.3, 0.04, 0.08, M('#94a3b8'), 0, 0.17, -0.02);
  for (let i = 0; i < 2; i++) cyl(g, 0.02, 0.02, 0.25, M('#e2e8f0'), -0.35 + i * 0.1, -0.2, -0.1);
  return g;
}

function lamp() {
  const g = newGroup('lamp');
  cyl(g, 0.07, 0.09, 0.025, M('#334155'), 0, -0.012, 0);
  cyl(g, 0.012, 0.012, 0.38, M('#475569'), 0, -0.2, 0);
  cyl(g, 0.05, 0.3, 0.2, M('#1f2937', { roughness: 0.4, metalness: 0.7, side: THREE.DoubleSide }), 0, -0.48, 0, { open: true, segments: 28 });
  cyl(g, 0.27, 0.27, 0.02, M('#fff7d6', { emissive: 0xfff2c4, emissiveIntensity: 1.6, roughness: 0.4 }), 0, -0.575, 0);
  const light = new THREE.PointLight(0xfff0c9, 9, 11, 2);
  light.position.set(0, -0.68, 0);
  light.castShadow = false;
  g.add(light);
  const rings = ensurePulse(g);
  const rr = radioRing(g, 0.42, '#fde68a', -0.62, 0.12);
  rr.userData.phase = 3;
  rings.push(rr);
  return g;
}

/* ============================ SEGURANÇA ============================ */

function extinguisher() {
  const g = newGroup('extinguisher');
  const red = M('#dc2626', { roughness: 0.45, metalness: 0.25 });
  box(g, 0.22, 0.36, 0.04, M('#334155'), 0, 0.5, -0.13);
  cyl(g, 0.1, 0.105, 0.48, red, 0, 0.3, 0);
  cyl(g, 0.04, 0.05, 0.06, M('#111827'), 0, 0.57, 0);
  box(g, 0.08, 0.05, 0.08, M('#111827'), 0, 0.62, 0);
  box(g, 0.14, 0.018, 0.03, M('#111827'), 0.02, 0.66, 0);
  cyl(g, 0.012, 0.012, 0.28, M('#111827'), 0.07, 0.51, 0.05, { rz: 0.5 });
  cyl(g, 0.02, 0.03, 0.06, M('#111827'), 0.15, 0.37, 0.08);
  box(g, 0.16, 0.12, 0.005, M('#f8fafc'), 0, 0.32, 0.101, { cast: false });
  box(g, 0.1, 0.015, 0.006, M('#dc2626'), 0, 0.32, 0.105, { cast: false });
  led(g, '#34d399', -0.05, 0.6, 0.06, 0.006);
  return g;
}

function hydrant() {
  const g = newGroup('hydrant');
  const red = M('#b91c1c', { roughness: 0.5, metalness: 0.3 });
  box(g, 0.52, 0.92, 0.3, red, 0, 0.46, 0);
  box(g, 0.4, 0.62, 0.02, M('#7dd3fc', { transparent: true, opacity: 0.25, roughness: 0.1, depthWrite: false }), 0, 0.48, 0.16);
  const coil = new THREE.Mesh(new THREE.TorusGeometry(0.14, 0.03, 8, 32), M('#7f1d1d', { roughness: 0.7 }));
  coil.position.set(0, 0.47, 0.03);
  g.add(coil);
  cyl(g, 0.035, 0.035, 0.12, M('#94a3b8'), 0.13, 0.47, 0.13, { rx: Math.PI / 2 });
  box(g, 0.5, 0.03, 0.32, M('#facc15'), 0, 0.93, 0, { cast: false });
  box(g, 0.06, 0.24, 0.04, M('#1f2937'), 0, 1.06, 0);
  box(g, 0.1, 0.05, 0.04, M('#dc2626'), 0, 0.8, 0.16);
  return g;
}

function sensor() {
  const g = newGroup('sensor');
  cyl(g, 0.07, 0.075, 0.025, M('#f1f5f9'), 0, -0.012, 0);
  const dome = new THREE.Mesh(new THREE.SphereGeometry(0.06, 16, 10, 0, Math.PI * 2, 0, Math.PI / 2), M('#f8fafc', { roughness: 0.3 }));
  dome.scale.y = 0.75;
  dome.rotation.x = Math.PI;
  dome.position.y = -0.035;
  dome.castShadow = true;
  g.add(dome);
  led(g, '#f87171', 0.035, -0.045, 0.03, 0.006);
  const rings = ensurePulse(g);
  const rr = radioRing(g, 0.22, '#f87171', -0.06, 0.14);
  rr.userData.phase = 0.5;
  rings.push(rr);
  return g;
}

/* ============================ LOGÍSTICA ============================ */

function pallet() {
  const g = newGroup('pallet');
  const wood = M('#a16207', { roughness: 0.9, metalness: 0.02 });
  const woodLight = M('#c08552', { roughness: 0.9, metalness: 0.02 });
  const cardboard = M('#b45309', { roughness: 0.85, metalness: 0.02 });
  for (let i = 0; i < 3; i++) box(g, 1.2, 0.1, 0.12, wood, 0, 0.05, -0.36 + i * 0.36);
  for (let i = 0; i < 5; i++) box(g, 1.16, 0.035, 0.14, woodLight, 0, 0.12, -0.38 + i * 0.19);
  box(g, 0.5, 0.42, 0.5, cardboard, -0.26, 0.35, 0);
  box(g, 0.48, 0.4, 0.48, cardboard, 0.27, 0.34, 0.01);
  box(g, 0.44, 0.3, 0.44, cardboard, 0.01, 0.71, 0);
  box(g, 0.1, 0.3, 0.445, M('#d6b17a'), 0.01, 0.71, 0, { cast: false });
  box(g, 0.5, 0.02, 0.14, M('#d6b17a'), -0.26, 0.56, 0, { cast: false });
  box(g, 0.48, 0.02, 0.12, M('#d6b17a'), 0.27, 0.54, 0.01, { cast: false });
  return g;
}

function forklift() {
  const g = newGroup('forklift');
  const body = M('#f59e0b', { roughness: 0.5, metalness: 0.35 });
  const dark = M('#1f2937', { roughness: 0.6, metalness: 0.4 });
  const steel = M('#94a3b8', { roughness: 0.35, metalness: 0.8 });
  box(g, 1.0, 0.55, 1.5, body, 0, 0.55, -0.05);
  box(g, 1.0, 0.55, 0.42, M('#334155'), 0, 0.55, -0.82);
  box(g, 0.95, 0.3, 0.5, dark, 0, 0.95, -0.35);
  box(g, 0.42, 0.1, 0.42, M('#111827'), 0, 1.05, -0.25);
  box(g, 0.42, 0.32, 0.06, M('#111827'), 0, 1.25, -0.44);
  box(g, 0.4, 0.02, 0.5, body, 0, 0.8, 0.2);
  // rodas
  [[-0.52, 0.5], [0.52, 0.5], [-0.52, -0.55], [0.52, -0.55]].forEach(([x, z]) => {
    cyl(g, 0.2, 0.2, 0.16, M('#111827', { roughness: 0.9 }), x, 0.2, z, { rz: Math.PI / 2 });
    cyl(g, 0.09, 0.09, 0.17, steel, x, 0.2, z, { rz: Math.PI / 2 });
  });
  // torre e garfos
  box(g, 0.09, 2.0, 0.09, steel, -0.32, 1.05, 0.78);
  box(g, 0.09, 2.0, 0.09, steel, 0.32, 1.05, 0.78);
  box(g, 0.74, 0.08, 0.1, steel, 0, 1.9, 0.78);
  box(g, 0.74, 0.08, 0.1, steel, 0, 0.35, 0.78);
  box(g, 0.8, 0.5, 0.06, dark, 0, 0.6, 0.84);
  box(g, 0.12, 0.05, 0.9, steel, -0.24, 0.18, 1.25);
  box(g, 0.12, 0.05, 0.9, steel, 0.24, 0.18, 1.25);
  box(g, 0.12, 0.4, 0.06, steel, -0.24, 0.4, 0.84);
  box(g, 0.12, 0.4, 0.06, steel, 0.24, 0.4, 0.84);
  // protetor superior
  [[-0.45, -0.42], [0.45, -0.42], [-0.45, 0.42], [0.45, 0.42]].forEach(([x, z]) => box(g, 0.05, 0.85, 0.05, dark, x, 1.6, z));
  box(g, 1.0, 0.06, 1.05, dark, 0, 2.03, 0);
  cyl(g, 0.04, 0.045, 0.06, M('#f97316', { emissive: 0xf97316, emissiveIntensity: 0.3 }), 0.35, 2.09, 0.2);
  // volante
  const wheel = new THREE.Mesh(new THREE.TorusGeometry(0.1, 0.018, 6, 20), dark);
  wheel.rotation.x = -0.6;
  wheel.position.set(0, 1.16, 0.1);
  g.add(wheel);
  cyl(g, 0.015, 0.015, 0.3, steel, 0, 1.05, 0.12, { rx: 0.5 });
  return g;
}

function unknown() {
  const g = newGroup('unknown');
  const shell = M('#475569', { roughness: 0.6, metalness: 0.3 });
  box(g, 0.6, 0.6, 0.6, shell, 0, 0.3, 0);
  box(g, 0.62, 0.06, 0.62, stripeMaterial(), 0, 0.62, 0);
  return g;
}

const BUILDERS = {
  desktop,
  notebook,
  server,
  rack,
  switch: switchModel,
  router,
  ap,
  antenna,
  camera,
  printer,
  nobreak,
  phone,
  cnc,
  conveyor,
  lathe,
  press,
  workbench,
  panel,
  compressor,
  ac,
  lamp,
  extinguisher,
  hydrant,
  sensor,
  pallet,
  forklift,
};

export function buildModel(typeId, { compact = false } = {}) {
  const builder = BUILDERS[typeId] || unknown;
  const model = builder(compact);
  model.traverse((o) => {
    if (o.isMesh) {
      o.castShadow = o.castShadow !== false;
      o.receiveShadow = true;
    }
  });
  return model;
}

/** Anel de seleção compartilhado (adicionado pelo viewer). */
export function createSelectionRing(color = '#22d3ee') {
  const mat = new THREE.MeshBasicMaterial({
    color: new THREE.Color(color),
    transparent: true,
    opacity: 0.85,
    side: THREE.DoubleSide,
    depthWrite: false,
    toneMapped: false,
  });
  const mesh = new THREE.Mesh(ringGeo, mat);
  mesh.rotation.x = -Math.PI / 2;
  mesh.renderOrder = 3;
  mesh.raycast = () => {};
  return mesh;
}

export { M as material, screenMaterial };
