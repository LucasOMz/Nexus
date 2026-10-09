"""Exportação e importação CSV (backup "do dia a dia").

* **Exportar** → um ZIP com um CSV por tabela (mais um manifesto). Usa os
  **nomes** (patrimônio, SKU, e-mail, nome do departamento…) em vez de IDs, para
  o arquivo ser legível e reimportável em outro banco.

* **Importar** → lê o ZIP, valida e **remove duplicados** pela chave natural de
  cada entidade. Sempre roda primeiro em modo *simulação* (`dry_run`), que
  devolve o relatório do que seria feito sem alterar nada.
"""
from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from app import __version__
from app.models.core import (
    Ativo,
    Categoria,
    Departamento,
    Fornecedor,
    Imagem,
    Localizacao,
    Manutencao,
    Movimentacao,
    Produto,
    Usuario,
)

# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------
_COLUNAS: dict[str, list[str]] = {
    "departamentos": ["nome", "sigla"],
    "localizacoes": ["nome", "descricao"],
    "fornecedores": ["nome", "cnpj", "contato", "telefone", "email"],
    "categorias": ["nome", "dominio", "descricao"],
    "usuarios": ["nome", "email", "papel", "ativo", "origem"],
    "ativos": [
        "patrimonio", "numero_serie", "modelo", "marca", "dominio", "tipo_item", "status",
        "categoria", "fornecedor", "localizacao", "departamento",
        "data_aquisicao", "data_garantia", "valor", "observacoes", "qr_payload", "foto_nome",
    ],
    "ativos_ti": ["patrimonio", "hostname", "mac_address", "ip", "so", "dominio_ad", "cpu", "ram_gb", "armazenamento_gb"],
    "ativos_impressora": ["patrimonio", "ip", "hostname", "driver", "tipo_impressao", "colorida", "contador_paginas", "conectividade"],
    "produtos": ["sku", "nome", "descricao", "categoria", "fornecedor", "dominio", "tipo_item", "unidade", "estoque_minimo", "preco_unitario"],
    "movimentacoes": ["tipo", "patrimonio", "produto_sku", "quantidade", "data_mov", "observacoes"],
    "manutencoes": ["patrimonio", "status", "descricao", "custo", "data_abertura", "data_conclusao", "tecnico", "observacoes"],
    "imagens": ["nome", "descricao", "tags", "dominio"],
}


def _fmt(valor: Any) -> str:
    if valor is None:
        return ""
    if hasattr(valor, "value"):
        valor = valor.value
    if hasattr(valor, "isoformat"):
        return valor.isoformat()
    return str(valor)


def _linhas(db: Session) -> dict[str, list[dict[str, str]]]:
    """Monta as linhas de cada tabela em formato portátil (por nome)."""
    dados: dict[str, list[dict[str, str]]] = {}

    dados["departamentos"] = [{"nome": d.nome, "sigla": d.sigla or ""} for d in db.query(Departamento).filter(Departamento.deleted_at.is_(None))]
    dados["localizacoes"] = [{"nome": loc.nome, "descricao": loc.descricao or ""} for loc in db.query(Localizacao).filter(Localizacao.deleted_at.is_(None))]
    dados["fornecedores"] = [
        {"nome": f.nome, "cnpj": f.cnpj or "", "contato": f.contato or "", "telefone": f.telefone or "", "email": f.email or ""}
        for f in db.query(Fornecedor).filter(Fornecedor.deleted_at.is_(None))
    ]
    dados["categorias"] = [{"nome": c.nome, "dominio": _fmt(c.dominio), "descricao": c.descricao or ""} for c in db.query(Categoria).filter(Categoria.deleted_at.is_(None))]
    dados["usuarios"] = [
        {"nome": u.nome, "email": u.email, "papel": _fmt(u.papel), "ativo": str(u.ativo), "origem": u.origem}
        for u in db.query(Usuario).filter(Usuario.deleted_at.is_(None))
    ]
    dados["imagens"] = [
        {"nome": i.nome, "descricao": i.descricao or "", "tags": i.tags or "", "dominio": _fmt(i.dominio)}
        for i in db.query(Imagem).filter(Imagem.deleted_at.is_(None))
    ]

    ativos_ti, ativos_imp = [], []
    lista_ativos = []
    for a in db.query(Ativo).filter(Ativo.deleted_at.is_(None)):
        lista_ativos.append({
            "patrimonio": a.patrimonio, "numero_serie": a.numero_serie or "", "modelo": a.modelo or "",
            "marca": a.marca or "", "dominio": _fmt(a.dominio), "tipo_item": _fmt(a.tipo_item), "status": _fmt(a.status),
            "categoria": a.categoria.nome if a.categoria else "", "fornecedor": a.fornecedor.nome if a.fornecedor else "",
            "localizacao": a.localizacao.nome if a.localizacao else "", "departamento": a.departamento.nome if a.departamento else "",
            "data_aquisicao": _fmt(a.data_aquisicao), "data_garantia": _fmt(a.data_garantia), "valor": _fmt(a.valor),
            "observacoes": a.observacoes or "", "qr_payload": a.qr_payload or "",
            "foto_nome": a.foto.nome if a.foto else "",
        })
        if a.ti:
            ativos_ti.append({
                "patrimonio": a.patrimonio, "hostname": a.ti.hostname or "", "mac_address": a.ti.mac_address or "",
                "ip": a.ti.ip or "", "so": a.ti.so or "", "dominio_ad": a.ti.dominio_ad or "", "cpu": a.ti.cpu or "",
                "ram_gb": _fmt(a.ti.ram_gb), "armazenamento_gb": _fmt(a.ti.armazenamento_gb),
            })
        if a.impressora:
            ativos_imp.append({
                "patrimonio": a.patrimonio, "ip": a.impressora.ip or "", "hostname": a.impressora.hostname or "",
                "driver": a.impressora.driver or "", "tipo_impressao": _fmt(a.impressora.tipo_impressao),
                "colorida": str(a.impressora.colorida), "contador_paginas": _fmt(a.impressora.contador_paginas),
                "conectividade": _fmt(a.impressora.conectividade),
            })
    dados["ativos"] = lista_ativos
    dados["ativos_ti"] = ativos_ti
    dados["ativos_impressora"] = ativos_imp

    dados["produtos"] = [
        {"sku": p.sku, "nome": p.nome, "descricao": p.descricao or "", "categoria": p.categoria.nome if p.categoria else "",
         "fornecedor": p.fornecedor.nome if p.fornecedor else "", "dominio": _fmt(p.dominio), "tipo_item": _fmt(p.tipo_item),
         "unidade": p.unidade or "", "estoque_minimo": _fmt(p.estoque_minimo), "preco_unitario": _fmt(p.preco_unitario)}
        for p in db.query(Produto).filter(Produto.deleted_at.is_(None))
    ]
    dados["movimentacoes"] = [
        {"tipo": _fmt(m.tipo), "patrimonio": m.ativo.patrimonio if m.ativo else "",
         "produto_sku": m.produto.sku if m.produto else "", "quantidade": _fmt(m.quantidade),
         "data_mov": _fmt(m.data_mov), "observacoes": m.observacoes or ""}
        for m in db.query(Movimentacao).filter(Movimentacao.deleted_at.is_(None))
    ]
    dados["manutencoes"] = [
        {"patrimonio": m.ativo.patrimonio if m.ativo else "", "status": _fmt(m.status), "descricao": m.descricao or "",
         "custo": _fmt(m.custo), "data_abertura": _fmt(m.data_abertura), "data_conclusao": _fmt(m.data_conclusao),
         "tecnico": m.tecnico or "", "observacoes": m.observacoes or ""}
        for m in db.query(Manutencao).filter(Manutencao.deleted_at.is_(None))
    ]
    return dados


def exportar_zip(db: Session) -> bytes:
    """Gera o ZIP com um CSV por tabela + manifesto."""
    dados = _linhas(db)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifesto = {
            "gerado_em": datetime.now().isoformat(timespec="seconds"),
            "app_version": __version__,
            "formato": "gestao-patrimonial/csv-zip",
            "tabelas": {},
        }
        for tabela, colunas in _COLUNAS.items():
            linhas = dados.get(tabela, [])
            texto = io.StringIO()
            escritor = csv.DictWriter(texto, fieldnames=colunas, delimiter=";", extrasaction="ignore")
            escritor.writeheader()
            for linha in linhas:
                escritor.writerow({c: linha.get(c, "") for c in colunas})
            zf.writestr(f"{tabela}.csv", "\ufeff" + texto.getvalue())
            manifesto["tabelas"][tabela] = len(linhas)
        zf.writestr("manifesto.json", json.dumps(manifesto, ensure_ascii=False, indent=2))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Importação
# ---------------------------------------------------------------------------
def _ler_csv(zf: zipfile.ZipFile, nome: str) -> list[dict[str, str]]:
    try:
        bruto = zf.read(f"{nome}.csv").decode("utf-8-sig")
    except KeyError:
        return []
    return [dict(linha) for linha in csv.DictReader(io.StringIO(bruto), delimiter=";")]


def _bool(valor: str) -> bool:
    return str(valor).strip().lower() in ("true", "1", "sim", "yes")


def _num(valor: str):
    texto = (valor or "").strip().replace(",", ".")
    if not texto:
        return None
    try:
        return float(texto) if "." in texto else int(texto)
    except ValueError:
        return None


def importar_zip(db: Session, conteudo: bytes, dry_run: bool = True, atualizar: bool = False) -> dict[str, Any]:
    """Importa um ZIP exportado pelo sistema, removendo duplicados.

    `atualizar=False` (padrão) mantém o registro existente e conta como duplicado.
    `dry_run=True` não altera nada — só devolve o relatório.
    """
    with zipfile.ZipFile(io.BytesIO(conteudo)) as zf:
        manifesto = {}
        try:
            manifesto = json.loads(zf.read("manifesto.json").decode("utf-8"))
        except (KeyError, json.JSONDecodeError):
            pass
        # Cache das entidades já existentes, por chave natural.
        deps = {d.nome.lower(): d for d in db.query(Departamento).filter(Departamento.deleted_at.is_(None))}
        locs = {loc.nome.lower(): loc for loc in db.query(Localizacao).filter(Localizacao.deleted_at.is_(None))}
        forns = {f.nome.lower(): f for f in db.query(Fornecedor).filter(Fornecedor.deleted_at.is_(None))}
        cats = {(c.nome.lower(), (c.dominio.value if c.dominio else "")): c for c in db.query(Categoria).filter(Categoria.deleted_at.is_(None))}
        users = {u.email.lower(): u for u in db.query(Usuario).filter(Usuario.deleted_at.is_(None))}
        imgs = {i.nome.lower(): i for i in db.query(Imagem).filter(Imagem.deleted_at.is_(None))}
        ativos = {a.patrimonio.lower(): a for a in db.query(Ativo).filter(Ativo.deleted_at.is_(None))}
        produtos = {p.sku.lower(): p for p in db.query(Produto).filter(Produto.deleted_at.is_(None))}

        relatorio: dict[str, dict[str, int]] = {}

        def contar(entidade: str, campo: str):
            relatorio.setdefault(entidade, {"novos": 0, "duplicados": 0, "atualizados": 0, "ignorados": 0})
            relatorio[entidade][campo] += 1

        # --- Cadastros simples -------------------------------------------------
        def importar_simples(tabela: str, cache: dict, criar: Callable, extra=None) -> None:
            for linha in _ler_csv(zf, tabela):
                chave = (linha.get("nome") or "").strip().lower()
                if not chave:
                    contar(tabela, "ignorados")
                    continue
                if chave in cache:
                    if atualizar and not dry_run:
                        extra and extra(cache[chave], linha)
                        contar(tabela, "atualizados")
                    else:
                        contar(tabela, "duplicados")
                    continue
                contar(tabela, "novos")
                if not dry_run:
                    obj = criar(linha)
                    db.add(obj)
                    db.flush()
                    cache[chave] = obj

        importar_simples("departamentos", deps, lambda linha: Departamento(nome=linha["nome"].strip(), sigla=(linha.get("sigla") or "").strip() or None))
        importar_simples("localizacoes", locs, lambda linha: Localizacao(nome=linha["nome"].strip(), descricao=(linha.get("descricao") or "").strip() or None))
        importar_simples("fornecedores", forns, lambda linha: Fornecedor(
            nome=linha["nome"].strip(), cnpj=(linha.get("cnpj") or "").strip() or None,
            contato=(linha.get("contato") or "").strip() or None, telefone=(linha.get("telefone") or "").strip() or None,
            email=(linha.get("email") or "").strip() or None,
        ))

        # Categorias (chave: nome + domínio).
        for linha in _ler_csv(zf, "categorias"):
            nome = (linha.get("nome") or "").strip()
            if not nome:
                contar("categorias", "ignorados")
                continue
            chave = (nome.lower(), (linha.get("dominio") or "").strip().lower())
            if chave in cats:
                contar("categorias", "duplicados")
                continue
            contar("categorias", "novos")
            if not dry_run:
                from app.models.enums import Dominio

                obj = Categoria(nome=nome, descricao=(linha.get("descricao") or "").strip() or None)
                if chave[1] in ("ti", "impressora"):
                    obj.dominio = Dominio(chave[1])
                db.add(obj)
                db.flush()
                cats[chave] = obj

        # Usuários (chave: e-mail). Nunca importa senha.
        import secrets as _secrets

        from app.core.security import hash_password

        for linha in _ler_csv(zf, "usuarios"):
            email = (linha.get("email") or "").strip().lower()
            if not email:
                contar("usuarios", "ignorados")
                continue
            if email in users:
                contar("usuarios", "duplicados")
                continue
            contar("usuarios", "novos")
            if not dry_run:
                from app.models.enums import PapelUsuario

                papel = (linha.get("papel") or "leitor").strip().lower()
                obj = Usuario(
                    nome=(linha.get("nome") or email).strip(), email=email,
                    senha_hash=hash_password(_secrets.token_urlsafe(24)),
                    papel=PapelUsuario(papel) if papel in ("admin", "ti", "leitor", "auditor") else PapelUsuario.LEITOR,
                    ativo=_bool(linha.get("ativo", "true")), origem=(linha.get("origem") or "local").strip() or "local",
                )
                db.add(obj)
                db.flush()
                users[email] = obj

        # Imagens (metadados; os arquivos vêm na pasta media/).
        for linha in _ler_csv(zf, "imagens"):
            nome = (linha.get("nome") or "").strip()
            if not nome:
                contar("imagens", "ignorados")
                continue
            if nome.lower() in imgs:
                contar("imagens", "duplicados")
                continue
            contar("imagens", "novos")
            if not dry_run:
                db.add(Imagem(nome=nome, descricao=(linha.get("descricao") or "").strip() or None,
                              tags=(linha.get("tags") or "").strip() or None, caminho=""))
                db.flush()

        # --- Ativos (chave: patrimônio) ---------------------------------------
        from app.models.enums import Dominio, StatusAtivo, TipoItem

        for linha in _ler_csv(zf, "ativos"):
            patrimonio = (linha.get("patrimonio") or "").strip()
            if not patrimonio:
                contar("ativos", "ignorados")
                continue
            if patrimonio.lower() in ativos:
                contar("ativos", "duplicados")
                continue
            contar("ativos", "novos")
            if dry_run:
                continue
            dominio_txt = (linha.get("dominio") or "ti").strip().lower()
            obj = Ativo(
                patrimonio=patrimonio,
                numero_serie=(linha.get("numero_serie") or "").strip() or None,
                modelo=(linha.get("modelo") or "").strip() or None,
                marca=(linha.get("marca") or "").strip() or None,
                dominio=Dominio(dominio_txt) if dominio_txt in ("ti", "impressora") else Dominio.TI,
                tipo_item=TipoItem.ATIVO,
                qr_payload=(linha.get("qr_payload") or "").strip() or None,
                observacoes=(linha.get("observacoes") or "").strip() or None,
                categoria_id=(cats.get(((linha.get("categoria") or "").strip().lower(), dominio_txt)) or {}).id if linha.get("categoria") else None,
                fornecedor_id=(forns.get((linha.get("fornecedor") or "").strip().lower()) or {}).id if linha.get("fornecedor") else None,
                localizacao_id=(locs.get((linha.get("localizacao") or "").strip().lower()) or {}).id if linha.get("localizacao") else None,
                departamento_id=(deps.get((linha.get("departamento") or "").strip().lower()) or {}).id if linha.get("departamento") else None,
            )
            status_txt = (linha.get("status") or "estoque").strip().lower()
            if status_txt in {s.value for s in StatusAtivo}:
                obj.status = StatusAtivo(status_txt)
            db.add(obj)
            db.flush()
            ativos[patrimonio.lower()] = obj

        # Extensões TI / Impressora (vinculadas pelo patrimônio).
        from app.models.enums import Conectividade, TipoImpressao
        from app.models.impressora import AtivoImpressora
        from app.models.ti import AtivoTI

        for linha in _ler_csv(zf, "ativos_ti"):
            ativo = ativos.get((linha.get("patrimonio") or "").strip().lower())
            if not ativo:
                contar("ativos_ti", "ignorados")
                continue
            if getattr(ativo, "ti", None) is not None:
                contar("ativos_ti", "duplicados")
                continue
            contar("ativos_ti", "novos")
            if not dry_run:
                ativo.ti = AtivoTI(
                    hostname=(linha.get("hostname") or "").strip() or None, mac_address=(linha.get("mac_address") or "").strip() or None,
                    ip=(linha.get("ip") or "").strip() or None, so=(linha.get("so") or "").strip() or None,
                    dominio_ad=(linha.get("dominio_ad") or "").strip() or None, cpu=(linha.get("cpu") or "").strip() or None,
                    ram_gb=_num(linha.get("ram_gb")), armazenamento_gb=_num(linha.get("armazenamento_gb")),
                )
                db.flush()

        for linha in _ler_csv(zf, "ativos_impressora"):
            ativo = ativos.get((linha.get("patrimonio") or "").strip().lower())
            if not ativo:
                contar("ativos_impressora", "ignorados")
                continue
            if getattr(ativo, "impressora", None) is not None:
                contar("ativos_impressora", "duplicados")
                continue
            contar("ativos_impressora", "novos")
            if not dry_run:
                tipo_txt = (linha.get("tipo_impressao") or "laser").strip().lower()
                con_txt = (linha.get("conectividade") or "rede").strip().lower()
                ativo.impressora = AtivoImpressora(
                    ip=(linha.get("ip") or "").strip() or None, hostname=(linha.get("hostname") or "").strip() or None,
                    driver=(linha.get("driver") or "").strip() or None,
                    tipo_impressao=TipoImpressao(tipo_txt) if tipo_txt in {t.value for t in TipoImpressao} else TipoImpressao.LASER,
                    colorida=_bool(linha.get("colorida", "false")),
                    contador_paginas=int(_num(linha.get("contador_paginas")) or 0),
                    conectividade=Conectividade(con_txt) if con_txt in {c.value for c in Conectividade} else Conectividade.REDE,
                )
                db.flush()

        # --- Produtos (chave: SKU) --------------------------------------------
        for linha in _ler_csv(zf, "produtos"):
            sku = (linha.get("sku") or "").strip()
            if not sku:
                contar("produtos", "ignorados")
                continue
            if sku.lower() in produtos:
                contar("produtos", "duplicados")
                continue
            contar("produtos", "novos")
            if not dry_run:
                dom = (linha.get("dominio") or "ti").strip().lower()
                db.add(Produto(
                    sku=sku, nome=(linha.get("nome") or sku).strip(),
                    descricao=(linha.get("descricao") or "").strip() or None,
                    dominio=Dominio(dom) if dom in ("ti", "impressora") else Dominio.TI,
                    tipo_item=TipoItem.CONSUMIVEL,
                    unidade=(linha.get("unidade") or "un").strip(),
                    estoque_minimo=int(_num(linha.get("estoque_minimo")) or 0),
                    preco_unitario=_num(linha.get("preco_unitario")),
                ))
                db.flush()

        # --- Histórico: movimentações e manutenções ---------------------------
        vistos_mov = {
            (m.tipo.value, m.ativo_id, m.produto_id, str(m.data_mov), m.quantidade)
            for m in db.query(Movimentacao).filter(Movimentacao.deleted_at.is_(None))
        }
        for linha in _ler_csv(zf, "movimentacoes"):
            ativo = ativos.get((linha.get("patrimonio") or "").strip().lower())
            produto = produtos.get((linha.get("produto_sku") or "").strip().lower())
            if not ativo and not produto:
                contar("movimentacoes", "ignorados")
                continue
            tipo_txt = (linha.get("tipo") or "entrada").strip().lower()
            chave = (tipo_txt, ativo.id if ativo else None, produto.id if produto else None,
                     (linha.get("data_mov") or "").strip(), int(_num(linha.get("quantidade")) or 1))
            if chave in vistos_mov:
                contar("movimentacoes", "duplicados")
                continue
            contar("movimentacoes", "novos")
            if not dry_run:
                from app.models.enums import TipoMov

                obj = Movimentacao(
                    tipo=TipoMov(tipo_txt) if tipo_txt in {t.value for t in TipoMov} else TipoMov.ENTRADA,
                    ativo_id=ativo.id if ativo else None, produto_id=produto.id if produto else None,
                    quantidade=int(_num(linha.get("quantidade")) or 1),
                    observacoes=(linha.get("observacoes") or "").strip() or None,
                )
                db.add(obj)
                db.flush()
                vistos_mov.add((obj.tipo.value, obj.ativo_id, obj.produto_id, str(obj.data_mov), obj.quantidade))

        vistos_manut = {
            (m.ativo_id, str(m.data_abertura))
            for m in db.query(Manutencao).filter(Manutencao.deleted_at.is_(None))
        }
        for linha in _ler_csv(zf, "manutencoes"):
            ativo = ativos.get((linha.get("patrimonio") or "").strip().lower())
            if not ativo:
                contar("manutencoes", "ignorados")
                continue
            chave = (ativo.id, (linha.get("data_abertura") or "").strip())
            if chave in vistos_manut:
                contar("manutencoes", "duplicados")
                continue
            contar("manutencoes", "novos")
            if not dry_run:
                from app.models.enums import StatusManut

                status_txt = (linha.get("status") or "aberta").strip().lower()
                db.add(Manutencao(
                    ativo_id=ativo.id,
                    status=StatusManut(status_txt) if status_txt in {s.value for s in StatusManut} else StatusManut.ABERTA,
                    descricao=(linha.get("descricao") or "").strip() or None,
                    custo=_num(linha.get("custo")), tecnico=(linha.get("tecnico") or "").strip() or None,
                    observacoes=(linha.get("observacoes") or "").strip() or None,
                ))
                db.flush()

        if dry_run:
            db.rollback()
        else:
            db.commit()

    totais = {
        "novos": sum(r["novos"] for r in relatorio.values()),
        "duplicados": sum(r["duplicados"] for r in relatorio.values()),
        "atualizados": sum(r["atualizados"] for r in relatorio.values()),
        "ignorados": sum(r["ignorados"] for r in relatorio.values()),
    }
    return {
        "dry_run": dry_run,
        "atualizar": atualizar,
        "manifesto": manifesto,
        "tabelas": relatorio,
        "totais": totais,
        "mensagem": (
            f"Simulação: {totais['novos']} novos, {totais['duplicados']} duplicados (serão ignorados)."
            if dry_run
            else f"Importação concluída: {totais['novos']} novos, {totais['duplicados']} duplicados ignorados."
        ),
    }
