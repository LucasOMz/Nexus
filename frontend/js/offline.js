/**
 * Fila offline baseada em IndexedDB.
 * Operações de escrita (POST/PUT/PATCH/DELETE) que falham por falta de rede
 * são enfileiradas e reexecutadas quando a conexão retorna.
 * @module offline
 */

const DB_NAME = "patrimonio-offline";
const STORE = "queue";

function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: "id", autoIncrement: true });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

/** Enfileira uma operação para reenvio posterior. */
export async function enqueue(method, path, body) {
  try {
    const db = await openDb();
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).add({ method, path, body, ts: Date.now() });
    return new Promise((r) => { tx.oncomplete = r; tx.onerror = r; });
  } catch { /* IndexedDB indisponível: descarta silenciosamente */ }
}

/** Retorna todas as operações pendentes. */
export async function pending() {
  try {
    const db = await openDb();
    const tx = db.transaction(STORE, "readonly");
    const req = tx.objectStore(STORE).getAll();
    return await new Promise((r) => { req.onsuccess = () => r(req.result || []); req.onerror = () => r([]); });
  } catch { return []; }
}

/** Remove uma operação da fila (após reenvio bem-sucedido). */
export async function dequeue(id) {
  try {
    const db = await openDb();
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).delete(id);
  } catch { /* noop */ }
}
