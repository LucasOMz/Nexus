"""`schema.sql` precisa refletir os modelos.

## Por que esta trava existe

O `schema.sql` é o caminho PostgreSQL documentado. Ele **ficou para trás duas
vezes** sem ninguém notar:

1. A locação acrescentou `contratos` e três colunas em `ativos` — e o arquivo
   não soube;
2. O inventário de software acrescentou cinco tabelas — e o arquivo também
   não.

Nada quebrou, porque o sistema cria as tabelas sozinho (`AUTO_CREATE_TABLES`).
**Por isso ninguém percebeu**: quem segue o esquema documentado só descobre o
furo quando tenta instalar num PostgreSQL de verdade e a primeira consulta
estoura.

Uma instalação que dependa do SQL documentado não tinha como criar o módulo
inteiro. Este teste compara os dois lados e falha **no mesmo commit** em que
alguém acrescenta um modelo sem refletir no arquivo.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import app.models  # noqa: F401 - registra todas as tabelas no metadata
from app.models.base import Base

SCHEMA = Path(__file__).resolve().parent.parent / "schema.sql"


def _sql() -> str:
    return SCHEMA.read_text(encoding="utf-8")


def _tabelas_do_sql() -> set[str]:
    return set(re.findall(r"CREATE TABLE(?: IF NOT EXISTS)? (\w+)", _sql()))


def _colunas_do_sql(tabela: str) -> set[str]:
    """As colunas declaradas num `CREATE TABLE`."""
    m = re.search(
        rf"CREATE TABLE(?: IF NOT EXISTS)? {tabela} \((.*?)\n\);",
        _sql(),
        re.S,
    )
    if not m:
        return set()
    colunas = set()
    for linha in m.group(1).split("\n"):
        limpa = linha.strip()
        if not limpa or limpa.startswith("--") or limpa.startswith("CONSTRAINT"):
            continue
        # Primeira palavra é o nome da coluna; o resto é tipo e modificadores.
        nome = limpa.split()[0]
        if nome.isidentifier():
            colunas.add(nome)
    return colunas


# Tabelas que existem no modelo e NÃO estão em `schema.sql`.
#
# Sem esta lista a trava acusaria falsos positivos e alguém a desligaria —
# que é pior do que não ter trava. Mas cada entrada aqui é **dívida
# registrada**, não permissão: a trava continua valendo para tabela NOVA.
#
# ⚠️ Estas sete são ANTERIORES a este trabalho: o `schema.sql` já estava
# desatualizado antes de a locação e o software chegarem. Documentar é o
# honesto; corrigi-las exige revisar a história de cada uma (colunas que
# mudaram, índices, dados) e é tarefa própria.
DISPENSADAS: dict[str, str] = {
    "contagens": "dívida anterior — ausente do schema.sql desde antes",
    "contagem_itens": "dívida anterior",
    "emprestimos": "dívida anterior",
    "emprestimo_itens": "dívida anterior",
    "checklist_itens": "dívida anterior",
    "filtros_salvos": "dívida anterior",
    "ocs_config": "dívida anterior",
    "ocs_sincronizacoes": "dívida anterior",
    "qr_zerados": "dívida anterior",
    "reportes_erro": "dívida anterior",
    "transferencias": "dívida anterior",
    # `plantas` é citada por outras tabelas do arquivo, mas o CREATE TABLE
    # dela não está aqui — está no bloco de instalação. Conferir antes de
    # mexer: pode ser criada noutro lugar de propósito.
    "plantas": "criada fora deste arquivo — conferir antes de mexer",
}


class TestTabelas:
    def test_toda_tabela_do_modelo_esta_no_sql(self):
        do_sql = _tabelas_do_sql()
        faltando = sorted(
            nome for nome in Base.metadata.tables
            if nome not in do_sql and nome not in DISPENSADAS
        )
        assert not faltando, (
            "Estas tabelas existem no modelo e não em `schema.sql`:\n"
            + "\n".join(f"  - {n}" for n in faltando)
            + "\n\nUma instalação PostgreSQL que siga o arquivo não as teria. "
            "Acrescente o CREATE TABLE correspondente."
        )

    def test_o_sql_nao_inventa_tabela(self):
        """O contrário também é problema: o arquivo criar algo que o modelo
        não conhece leva a consultas que falham do outro lado."""
        do_modelo = set(Base.metadata.tables)
        sobrando = sorted(t for t in _tabelas_do_sql() if t not in do_modelo)
        assert not sobrando, f"`schema.sql` cria tabela que o modelo não tem: {sobrando}"


class TestColunas:
    @pytest.mark.parametrize("tabela", [
        "softwares", "licencas", "softwares_instalados",
        "atribuicoes_licenca", "contratos",
    ])
    def test_as_colunas_batem(self, tabela):
        """Só as tabelas que nasceram nesta leva.

        As antigas divergem do arquivo em detalhes históricos, e ajustá-las
        seria outra conversa — mas as novas não podem nascer já fora de sinc.
        """
        do_sql = _colunas_do_sql(tabela)
        assert do_sql, f"{tabela} não foi encontrada em schema.sql"

        do_modelo = {c.name for c in Base.metadata.tables[tabela].columns}
        faltando = sorted(do_modelo - do_sql)
        assert not faltando, (
            f"Colunas de `{tabela}` no modelo e não em `schema.sql`: {faltando}"
        )


class TestEstruturaDoArquivo:
    def test_termina_com_commit(self):
        assert _sql().rstrip().endswith("COMMIT;")

    def test_as_novas_tabelas_entram_antes_do_commit(self):
        """Fora da transação, a instalação ficaria pela metade se algo
        falhasse no meio."""
        c = _sql()
        pos_commit = c.rfind("COMMIT;")
        for tabela in ("softwares", "licencas", "atribuicoes_licenca"):
            i = c.find(f"CREATE TABLE IF NOT EXISTS {tabela}")
            assert i > 0 and i < pos_commit, f"{tabela} ficou fora da transação"

    def test_a_chave_nunca_e_gravada_em_claro(self):
        """A garantia que o esquema documentado também precisa carregar."""
        colunas = _colunas_do_sql("licencas")
        assert "chave" not in colunas, (
            "`schema.sql` declara uma coluna `chave` em claro — a chave de "
            "licença é um segredo e só pode existir cifrada"
        )
        assert {"chave_cifrada", "chave_versao", "chave_impressao", "chave_hash"} <= colunas

    def test_a_atribuicao_tem_a_restricao_de_um_dono(self):
        """Exatamente um entre ativo e usuário. Sem a CHECK, o banco aceitaria
        uma atribuição sem dono — e ela não apareceria em lugar nenhum."""
        c = _sql()
        assert "ck_atribuicao_um_dono" in c
