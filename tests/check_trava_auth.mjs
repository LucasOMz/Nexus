// Prova que a trava da tela de Autenticação detecta a quebra.
// (Sem isso, um teste que nunca falha é pior do que teste nenhum.)
import fs from "node:fs";

const real = fs.readFileSync(new URL("../frontend/js/views/admin_auth.js", import.meta.url), "utf8");
// Quebra simulada: a função auxiliar deixa de ser chamada.
const quebrado = real.replace(/opcao\(/g, "opcaoXX(");

const EXIGIDOS = ["ldap_ativo", "ldap_tls", "ldap_ignorar_certificado"];

function travaPassa(fonte) {
  const achados = [...fonte.matchAll(/opcao\("(\w+)"/g)].map((m) => m[1]);
  return { achados, passa: EXIGIDOS.every((k) => achados.includes(k)) };
}

const ok = travaPassa(real);
const ruim = travaPassa(quebrado);

console.log(`  codigo real     interruptores=${ok.achados.length}  trava passa=${ok.passa}`);
console.log(`  codigo QUEBRADO interruptores=${ruim.achados.length}  trava passa=${ruim.passa}`);

if (!ok.passa || ruim.passa) {
  console.log("\nTRAVA INUTIL - ela nao distingue codigo certo de quebrado");
  process.exit(1);
}
console.log("\nTrava OK: aceita o codigo correto e reprova o quebrado");
