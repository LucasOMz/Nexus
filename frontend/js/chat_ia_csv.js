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

export function rotuloSoftware(filtro) {
  const acao = filtro.situacao === "ausente" ? "Sem " : "";
  const versao = filtro.versao ? " · versão " + filtro.versao + (filtro.comparacao_versao === "prefixo" ? ".x" : "") : "";
  return acao + filtro.nome + versao;
}

export const avisoSoftwareAusente = "A ausência considera ativos com software inventariado. Versões desconhecidas não confirmam ausência de uma versão.";

export function montarCsv({ pergunta, resposta, resultados, exportacao_atual }, historica = false) {
  const linhas = [
    ["Consulta", "Linha", "Pergunta", "Resposta", "Total", "Correspondentes", "Percentual (%)",
      "Agrupamento 1", "Valor 1", "Agrupamento 2", "Valor 2", "ID", "Hostname", "Patrimônio", "Modelo",
      "Planta", "Departamento", "Status", "Observação", "RAM (GB)", "Armazenamento (GB)", "Processador", "Sistema operacional",
      "Seção", "Campo", "Valor", "Número de série", "Marca", "Categoria", "Localização", "Tipo de equipamento",
      "Inventário", "Software", "Versão instalada"],
    ["", "Resposta", pergunta, resposta],
  ];
  if (exportacao_atual) linhas.push(["", "Atualização", "", "",
    "", "", "", "", "", "", "", "", "", "", "", "", "", "", "O texto da resposta é o original. Os resultados detalhados refletem os dados consultados na hora da exportação."]);
  for (const [indice, item] of resultados.entries()) {
    const n = indice + 1;
    if (item.tipo === "informacoes") {
      linhas.push([n, "Resumo", "", item.resumo]);
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
    const softwares = [...(item.consulta?.softwares || []), ...(item.consulta?.softwares_numerador || [])];
    escopo.push(...softwares.map(rotuloSoftware));
    const avisos = [item.aviso, escopo.length ? escopo.join(" · ") : ""];
    if (softwares.some(filtro => filtro.situacao === "ausente")) avisos.push(avisoSoftwareAusente);
    if (item.truncado) avisos.push("Agrupamento limitado aos grupos exibidos.");
    if (item.operacao === "listar" || item.equipamentos_exibidos) {
      const rotulo = exportacao_atual || historica && item.equipamentos_exibidos ? "Lista atual do inventário" : "Lista exibida";
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
      const linha = [n, "Equipamento", "", "", "", "", "", "", "", "", "",
        ativo.id, ativo.hostname, ativo.patrimonio, ativo.modelo, ativo.planta, ativo.departamento, ativo.status, "",
        ativo.ram_gb, ativo.armazenamento_gb, ativo.cpu, ativo.so, "", "", "",
        ativo.numero_serie, ativo.marca, ativo.categoria, ativo.localizacao, ativo.tipo_equipamento, ativo.dominio];
      linhas.push(linha);
      for (const software of ativo.softwares || []) {
        const instalacao = [...linha, software.nome, software.versao];
        instalacao[1] = "Software instalado";
        linhas.push(instalacao);
      }
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
