"""Importação de ativos — criação dos cadastros de apoio.

## Os dois bugs que estes testes existem para impedir

### 1. `planta_id` em cadastro global

`Categoria`, `Fornecedor`, `Localizacao` e `Departamento` **não têm**
`planta_id` — são globais. O código passava o argumento mesmo assim:

    TypeError: 'planta_id' is an invalid keyword argument for Categoria

Ficou escondido enquanto o backup falhava: a importação morria antes.

### 2. Colisão de nomes entre tabelas diferentes

O mapa de "o que já criei neste arquivo" era `dict[str, int]`, com o **nome**
como chave — e os quatro cadastros **dividiam o mesmo mapa**.

Como existem nomes repetidos entre tabelas — `Financeiro` e `Diretoria` são
**localização e departamento** — o segundo reaproveitava o id do primeiro:

    localizacao "Financeiro"   -> id 5
    departamento "Financeiro"  -> achou no mapa -> usou id 5

E o INSERT em `ativos` falhava:

    ForeignKeyViolation: Key (departamento_id)=(5) is not present
    in table "departamentos"

## Por que em banco ZERADO

Os dois só aparecem quando os cadastros **precisam ser criados**. Num banco
que já os tem, `novo_departamento` não é setado, a criação não roda, e o bug
passa despercebido — foi o que aconteceu no primeiro teste manual.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.models.core import Ativo, Categoria, Departamento, Localizacao, Planta
from app.services import importar_ativos

# Nomes que colidem de propósito: a localização e o departamento têm o mesmo
# nome, que é o caso real de "Financeiro" e "Diretoria".
CABECALHO = "patrimonio;dominio;tipo_item;numero_serie;modelo;marca;status;categoria;localizacao;departamento"


def _csv(linhas: list[str]) -> bytes:
    return ("\ufeff" + CABECALHO + "\r\n" + "\r\n".join(linhas) + "\r\n").encode("utf-8")


@pytest.fixture()
def limpo(monkeypatch):
    """Banco zerado, com uma planta — o cenário de uma instalação nova.

    O backup é neutralizado: `importar()` exige um antes de gravar, e o banco
    em memória não tem arquivo para copiar. Este teste é sobre **os cadastros
    de apoio**, não sobre o backup — que tem os seus próprios testes.

    Pior que neutralizar seria usar banco em arquivo: `backup_service` lê o
    caminho do `Settings` global, então copiaria o banco da suíte, não o
    deste teste. O backup passaria sem tocar no que está sendo testado.
    """
    from app.services import backup_service

    monkeypatch.setattr(
        backup_service, "criar_backup",
        lambda *a, **k: {"arquivo": "teste.dump", "tamanho": 0},
    )

    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    Sessao = sessionmaker(bind=engine, future=True)
    db = Sessao()
    planta = Planta(nome="Central", sigla="Central", ativa=True)
    db.add(planta)
    db.commit()
    try:
        yield db, planta.id
    finally:
        db.close()
        engine.dispose()


class TestCadastrosGlobais:
    def test_importa_criando_os_cadastros(self, limpo):
        """O caminho básico: cadastro novo precisa ser criado, não herdado."""
        db, planta_id = limpo
        conteudo = _csv([
            "TI-1;ti;ativo;SN1;Latitude;Dell;em_uso;Notebook;Recepção;TI",
        ])
        r = importar_ativos.importar(conteudo, db, planta_id)

        assert r["ok"] is True, r.get("mensagem")
        assert r["criados"] == 1
        assert db.query(Ativo).count() == 1
        assert db.query(Categoria).count() == 1
        assert db.query(Localizacao).count() == 1
        assert db.query(Departamento).count() == 1

    def test_nome_igual_em_tabelas_diferentes_nao_colide(self, limpo):
        """O bug da chave só pelo nome.

        "Financeiro" é localização **e** departamento. Sem a chave composta,
        o departamento recebia o id da localização e o INSERT estourava com
        violação de chave estrangeira.

        ## Por que a localização pré-existente

        Num banco vazio, localização e departamento nascem ambos com `id=1`
        — e as duas idades coincidem, então o bug **passaria despercebido**.
        Criando uma localização antes, as sequências se desalinham: a
        localização "Financeiro" vira `id=2` e o departamento `id=1`.

        Com o bug, `departamento_id` recebia `2` — que não existe em
        `departamentos` — e o INSERT falhava. É exatamente o erro que
        apareceu na importação de 5.000 ativos.
        """
        db, planta_id = limpo

        # Desalinha as sequências: a localização já começa em 2.
        db.add(Localizacao(nome="Recepção"))
        db.commit()

        conteudo = _csv([
            "TI-1;ti;ativo;SN1;Latitude;Dell;em_uso;Notebook;Financeiro;Financeiro",
        ])
        r = importar_ativos.importar(conteudo, db, planta_id)

        assert r["ok"] is True, r.get("mensagem")

        ativo = db.query(Ativo).first()
        local = db.query(Localizacao).filter(Localizacao.nome == "Financeiro").one()
        dep = db.query(Departamento).filter(Departamento.nome == "Financeiro").one()

        # O ponto do bug: apontar para a tabela CERTA, não para um id que
        # existe em outra.
        assert ativo.localizacao_id == local.id
        assert ativo.departamento_id == dep.id

        # E as sequências precisam estar desalinhadas — senão o teste acima
        # não provaria nada.
        assert local.id != dep.id, "as sequências coincidiram; o teste perdeu o sentido"

    def test_dois_ativos_reaproveitam_o_mesmo_cadastro(self, limpo):
        """Reaproveitar dentro do mesmo arquivo continua valendo.

        É a razão de o mapa existir: 40 ativos com "Notebook" não podem
        criar 40 categorias.
        """
        db, planta_id = limpo
        conteudo = _csv([
            "TI-1;ti;ativo;SN1;Latitude;Dell;em_uso;Notebook;Recepção;TI",
            "TI-2;ti;ativo;SN2;Latitude;Dell;em_uso;Notebook;Recepção;TI",
        ])
        r = importar_ativos.importar(conteudo, db, planta_id)

        assert r["ok"] is True, r.get("mensagem")
        assert db.query(Ativo).count() == 2
        assert db.query(Categoria).count() == 1, "categoria duplicada"
        assert db.query(Localizacao).count() == 1, "localização duplicada"

    def test_categoria_recebe_o_dominio(self, limpo):
        """Categoria de impressora não pode aparecer no inventário de TI."""
        db, planta_id = limpo
        conteudo = _csv([
            "IMP-1;impressora;ativo;SN9;LaserJet;HP;em_uso;Impressora;Recepção;TI",
        ])
        r = importar_ativos.importar(conteudo, db, planta_id)
        assert r["ok"] is True, r.get("mensagem")

        cat = db.query(Categoria).one()
        assert cat.dominio is not None, "categoria criada sem domínio"
        assert cat.dominio.value == "impressora"

    def test_nada_gravado_quando_falha(self, limpo):
        """Transação: uma falha no meio não deixa meio arquivo dentro.

        A mensagem do sistema promete "o banco voltou ao estado anterior".
        Este teste cobra a promessa.
        """
        db, planta_id = limpo
        # Segunda linha sem série e sem patrimônio: inválida.
        conteudo = _csv([
            "TI-1;ti;ativo;SN1;Latitude;Dell;em_uso;Notebook;Recepção;TI",
            ";;;",
        ])
        r = importar_ativos.importar(conteudo, db, planta_id)

        if r["ok"]:
            # Se aceitou, importou só a válida — e o banco tem de refletir isso.
            assert db.query(Ativo).count() == r["criados"]
        else:
            assert db.query(Ativo).count() == 0, "sobrou ativo de importação falha"

class TestSerieUnica:
    """A série é o identificador — e o índice único cobre linha excluída.

    ## O erro que estes testes impedem

        UniqueViolation: duplicate key value violates unique constraint
        "ix_ativos_numero_serie"  Key (numero_serie)=(...) already exists

    A validação ignorava `deleted_at`, então dizia que estava livre; o índice
    único **não** ignora, e o INSERT estourava. Só aparecia depois de excluir
    em lote e reimportar o mesmo arquivo.
    """

    CSV = ("\ufeffpatrimonio;dominio;tipo_item;numero_serie;modelo;marca;status\r\n"
           "TI-1;ti;ativo;SERIAL-X;Latitude;Dell;em_uso\r\n")

    def test_previa_acusa_serie_de_linha_viva(self, limpo):
        db, planta_id = limpo
        importar_ativos.importar(self.CSV.encode("utf-8"), db, planta_id)

        a = importar_ativos.analisar(self.CSV.encode("utf-8"), db, planta_id)
        erros = [e for linha in a.linhas for e in linha.erros]
        assert any("série" in e for e in erros), erros

    def test_reimportar_apos_excluir_funciona(self, limpo):
        """O caso real: excluir em lote e subir o mesmo arquivo de novo."""
        from datetime import datetime, timezone

        db, planta_id = limpo
        importar_ativos.importar(self.CSV.encode("utf-8"), db, planta_id)

        ativo = db.query(Ativo).first()
        ativo.deleted_at = datetime.now(timezone.utc)
        db.commit()

        r = importar_ativos.importar(self.CSV.encode("utf-8"), db, planta_id)
        assert r["ok"] is True, r.get("mensagem")
        assert r["criados"] == 1

    def test_excluido_tem_o_valor_liberado(self, limpo):
        """O detentor antigo é renomeado, não apagado.

        Apagar o histórico seria pior: perde-se a rastreabilidade de quem
        tinha aquele equipamento. O sufixo deixa claro que é registro morto.
        """
        from datetime import datetime, timezone

        db, planta_id = limpo
        importar_ativos.importar(self.CSV.encode("utf-8"), db, planta_id)

        ativo = db.query(Ativo).first()
        ativo.deleted_at = datetime.now(timezone.utc)
        db.commit()
        importar_ativos.importar(self.CSV.encode("utf-8"), db, planta_id)

        morto = db.query(Ativo).filter(Ativo.deleted_at.isnot(None)).one()
        assert morto.numero_serie.startswith("SERIAL-X")
        assert "excluído" in morto.numero_serie, morto.numero_serie

        vivo = db.query(Ativo).filter(Ativo.deleted_at.is_(None)).one()
        assert vivo.numero_serie == "SERIAL-X"
