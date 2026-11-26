const rotulos = {
  planta: "Planta", departamento: "Departamento", localizacao: "Localização", categoria: "Categoria",
  tipo_equipamento: "Tipo de equipamento", dominio: "Inventário", status: "Status", marca: "Marca", modelo: "Modelo",
};

function celula(valor) {
  if (valor == null || valor === "") return "";
  if (typeof valor === "number") return String(valor).replace(".", ",");
  let texto = String(valor);
  if (/^\s*[=+\-@]|^[\t\r\n]/u.test(texto)) texto = "'" + texto;
  return '"' + texto.replaceAll('"', '""') + '"';
}

export function montarCsv({ pergunta, resposta, resultados }, historica = false) {
  const linhas = [
    ["Consulta", "Linha", "Pergunta", "Resposta", "Total", "Correspondentes", "Percentual (%)",
      "Agrupamento 1", "Valor 1", "Agrupamento 2", "Valor 2", "ID", "Hostname", "Patrimônio", "Modelo",
      "Planta", "Departamento", "Status", "Observação", "RAM (GB)", "Armazenamento (GB)", "Processador", "Sistema operacional",
      "Seção", "Campo", "Valor"],
    ["", "Resposta", pergunta, resposta],
  ];
  for (const [indice, item] of resultados.entries()) {
    const n = indice + 1;
    if (item.tipo === "informacoes") {
      for (const secao of item.blocos || []) {
        for (const [campo, valor] of secao.linhas) {
          const linha = [n, "Informação"];
          linha[23] = secao.titulo;
          linha[24] = campo;
          linha[25] = valor;
          linhas.push(linha);
        }
      }
      continue;
    }
    const equipamentos = item.equipamentos_exibidos || item.equipamentos || [];
    const totalDetalhes = item.total_exibidos ?? item.total;
    const cadastros = item.cadastros_consultados;
    const escopo = [...(cadastros?.planta || []), ...(cadastros?.departamento || [])];
    const avisos = [item.aviso, escopo.length ? escopo.join(" · ") : ""];
    if (item.truncado) avisos.push("Agrupamento limitado aos grupos exibidos.");
    if (item.operacao === "listar" || item.equipamentos_exibidos) {
      const rotulo = historica && item.equipamentos_exibidos ? "Lista atual do inventário" : "Lista exibida";
      avisos.push(`${rotulo}: ${equipamentos.length} de ${totalDetalhes} equipamentos.`);
    }
    linhas.push([n, "Total", "", "", item.total, item.correspondentes, item.percentual,
      "", "", "", "", "", "", "", "", "", "", "", avisos.filter(Boolean).join(" ")]);
    for (const grupo of item.grupos || []) {
      const [primeiro, segundo] = item.agrupar_por;
      linhas.push([n, "Grupo", "", "", grupo.total, grupo.correspondentes, grupo.percentual,
        rotulos[primeiro], grupo.valores[0] || "Sem cadastro",
        rotulos[segundo], segundo ? grupo.valores[1] || "Sem cadastro" : ""]);
    }
    for (const ativo of equipamentos) {
      linhas.push([n, "Equipamento", "", "", "", "", "", "", "", "", "",
        ativo.id, ativo.hostname, ativo.patrimonio, ativo.modelo, ativo.planta, ativo.departamento, ativo.status, "",
        ativo.ram_gb, ativo.armazenamento_gb, ativo.cpu, ativo.so]);
    }
  }
  const largura = linhas[0].length;
  return "\uFEFF" + linhas.map(linha =>
    Array.from({ length: largura }, (_, coluna) => celula(linha[coluna])).join(";")
  ).join("\r\n") + "\r\n";
}

export function baixarCsv(turno, historica) {
  const url = URL.createObjectURL(new Blob([montarCsv(turno, historica)], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "nexus-resultado-chat.csv";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
