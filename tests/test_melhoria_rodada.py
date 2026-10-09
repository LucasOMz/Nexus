

class TestBuscaPorHostname:
    """O hostname é como a máquina é conhecida na rede.

    Ele fica na ficha técnica (AtivoTI), não no ativo. Sem a junção, procurar
    por "DTAT0001" não achava nada — nem na lista de ativos, nem na leitura.
    """

    def _ativo_com_hostname(self, client, auth_headers, patrimonio, hostname):
        a = client.post("/api/v1/ativos", json={
            "dominio": "ti", "patrimonio": patrimonio, "tipo_item": "ativo",
            "modelo": "Latitude",
        }, headers=auth_headers).json()
        # A ficha técnica é criada junto do ativo; atualizamos o hostname nela.
        client.put(f"/api/v1/ativos/{a['id']}", json={"ti": {"hostname": hostname}},
                   headers=auth_headers)
        return a

    def test_busca_encontra_pelo_hostname(self, client, auth_headers):
        self._ativo_com_hostname(client, auth_headers, "HOST-001", "DTAT0001")

        r = client.get("/api/v1/ativos", params={"search": "DTAT0001"}, headers=auth_headers).json()
        assert r["total"] >= 1, "a busca por hostname não encontrou o ativo"

    def test_busca_parcial_pelo_hostname(self, client, auth_headers):
        self._ativo_com_hostname(client, auth_headers, "HOST-002", "NTAT0099")

        r = client.get("/api/v1/ativos", params={"search": "NTAT"}, headers=auth_headers).json()
        assert r["total"] >= 1

    def test_busca_por_patrimonio_continua(self, client, auth_headers):
        client.post("/api/v1/ativos", json={
            "dominio": "ti", "patrimonio": "PATR-777", "tipo_item": "ativo",
        }, headers=auth_headers)

        r = client.get("/api/v1/ativos", params={"search": "PATR-777"}, headers=auth_headers).json()
        assert r["total"] >= 1

    def test_leitura_resolve_pelo_hostname(self, client, auth_headers):
        """Na tela de Leitura o técnico digita o nome da máquina."""
        self._ativo_com_hostname(client, auth_headers, "HOST-003", "RTAT0007")

        r = client.post("/api/v1/scanner/buscar", json={"codigo": "RTAT0007"},
                        headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["ativo"]["patrimonio"] == "HOST-003"

    def test_leitura_ainda_resolve_pelo_patrimonio(self, client, auth_headers):
        client.post("/api/v1/ativos", json={
            "dominio": "ti", "patrimonio": "SEMPATR-1", "tipo_item": "ativo",
        }, headers=auth_headers)

        r = client.post("/api/v1/scanner/buscar", json={"codigo": "SEMPATR-1"},
                        headers=auth_headers)
        assert r.status_code == 200


class TestHistoricoDeConsumivel:
    """Consulta do histórico de entrada e saída de um consumível.

    O dado sempre existiu (`usuario_id` e `data_mov` na movimentação); faltava
    uma forma de lê-lo. O que o histórico precisa é ser LEGÍVEL: nome de quem
    movimentou, não o id.
    """

    def _consumivel(self, client, auth_headers, sku="SKU-HIST-1"):
        return client.post("/api/v1/produtos", json={
            "sku": sku, "nome": "Tonner HP 26A", "dominio": "ti",
            "estoque_minimo": 5,
        }, headers=auth_headers).json()

    def _movimentar(self, client, auth_headers, produto_id, tipo, qtd):
        return client.post("/api/v1/movimentacoes", json={
            "tipo": tipo, "produto_id": produto_id, "quantidade": qtd,
        }, headers=auth_headers)

    def test_historico_do_produto(self, client, auth_headers):
        p = self._consumivel(client, auth_headers)
        self._movimentar(client, auth_headers, p["id"], "entrada", 10)
        self._movimentar(client, auth_headers, p["id"], "saida", 3)

        r = client.get("/api/v1/movimentacoes",
                       params={"produto_id": p["id"]}, headers=auth_headers).json()
        assert r["total"] == 2

    def test_historico_traz_quem_e_quando(self, client, auth_headers):
        p = self._consumivel(client, auth_headers, "SKU-HIST-2")
        self._movimentar(client, auth_headers, p["id"], "entrada", 5)

        item = client.get("/api/v1/movimentacoes",
                          params={"produto_id": p["id"]}, headers=auth_headers).json()["items"][0]
        assert item["usuario_nome"], "o histórico precisa dizer QUEM movimentou"
        assert item["data_mov"], "o histórico precisa dizer QUANDO"

    def test_historico_traz_o_nome_do_produto(self, client, auth_headers):
        p = self._consumivel(client, auth_headers, "SKU-HIST-3")
        self._movimentar(client, auth_headers, p["id"], "saida", 2)

        item = client.get("/api/v1/movimentacoes",
                          params={"produto_id": p["id"]}, headers=auth_headers).json()["items"][0]
        assert item["produto_nome"] == "Tonner HP 26A"
        assert item["produto_sku"] == "SKU-HIST-3"

    def test_ordem_do_mais_recente_para_o_antigo(self, client, auth_headers):
        p = self._consumivel(client, auth_headers, "SKU-HIST-4")
        self._movimentar(client, auth_headers, p["id"], "entrada", 1)
        self._movimentar(client, auth_headers, p["id"], "saida", 1)

        itens = client.get("/api/v1/movimentacoes",
                           params={"produto_id": p["id"]}, headers=auth_headers).json()["items"]
        assert itens[0]["data_mov"] >= itens[-1]["data_mov"]

    def test_filtra_por_tipo(self, client, auth_headers):
        p = self._consumivel(client, auth_headers, "SKU-HIST-5")
        self._movimentar(client, auth_headers, p["id"], "entrada", 10)
        self._movimentar(client, auth_headers, p["id"], "saida", 4)

        itens = client.get("/api/v1/movimentacoes",
                           params={"produto_id": p["id"], "tipo": "saida"},
                           headers=auth_headers).json()["items"]
        assert len(itens) == 1
        assert itens[0]["tipo"] == "saida"

    def test_historico_de_outro_produto_nao_vaza(self, client, auth_headers):
        a = self._consumivel(client, auth_headers, "SKU-HIST-6")
        b = self._consumivel(client, auth_headers, "SKU-HIST-7")
        self._movimentar(client, auth_headers, a["id"], "entrada", 1)

        itens = client.get("/api/v1/movimentacoes",
                           params={"produto_id": b["id"]}, headers=auth_headers).json()["items"]
        assert itens == []


class TestFinalidadeDaSaida:
    """Saída de consumível com finalidade: descarte ou instalação.

    Saber apenas "saíram 2 unidades" não responde a pergunta que importa:
    foi descarte ou foi usado numa máquina — e qual.
    """

    def _consumivel(self, client, h, sku):
        return client.post("/api/v1/produtos", json={
            "sku": sku, "nome": f"Tonner {sku}", "dominio": "ti", "estoque_minimo": 1,
        }, headers=h).json()

    def _equipamento(self, client, h, patrimonio):
        return client.post("/api/v1/ativos", json={
            "dominio": "ti", "patrimonio": patrimonio, "tipo_item": "ativo",
        }, headers=h).json()

    def _saida(self, client, h, produto_id, **extra):
        return client.post("/api/v1/movimentacoes", json={
            "tipo": "saida", "produto_id": produto_id, "quantidade": 2, **extra,
        }, headers=h)

    def test_descarte_e_aceito(self, client, auth_headers):
        p = self._consumivel(client, auth_headers, "FIN-1")
        r = self._saida(client, auth_headers, p["id"], finalidade="descarte")
        assert r.status_code == 201, r.text
        assert r.json()["finalidade"] == "descarte"
        assert r.json()["finalidade_rotulo"] == "Descarte"

    def test_instalacao_guarda_o_equipamento(self, client, auth_headers):
        p = self._consumivel(client, auth_headers, "FIN-2")
        a = self._equipamento(client, auth_headers, "EQ-FIN-1")

        r = self._saida(client, auth_headers, p["id"],
                        finalidade="instalacao", ativo_instalado_id=a["id"])
        assert r.status_code == 201, r.text
        assert r.json()["finalidade"] == "instalacao"
        assert r.json()["ativo_instalado_id"] == a["id"]
        assert r.json()["ativo_instalado_patrimonio"] == "EQ-FIN-1"

    def test_instalacao_sem_ativo_e_recusada(self, client, auth_headers):
        p = self._consumivel(client, auth_headers, "FIN-3")
        r = self._saida(client, auth_headers, p["id"], finalidade="instalacao")
        assert r.status_code == 422
        assert "ativo" in r.text.lower()

    def test_descarte_com_ativo_e_recusado(self, client, auth_headers):
        p = self._consumivel(client, auth_headers, "FIN-4")
        a = self._equipamento(client, auth_headers, "EQ-FIN-2")
        r = self._saida(client, auth_headers, p["id"],
                        finalidade="descarte", ativo_instalado_id=a["id"])
        assert r.status_code == 422

    def test_entrada_nao_aceita_finalidade(self, client, auth_headers):
        p = self._consumivel(client, auth_headers, "FIN-5")
        r = client.post("/api/v1/movimentacoes", json={
            "tipo": "entrada", "produto_id": p["id"], "quantidade": 5,
            "finalidade": "descarte",
        }, headers=auth_headers)
        assert r.status_code == 422

    def test_finalidade_inventada_e_recusada(self, client, auth_headers):
        p = self._consumivel(client, auth_headers, "FIN-6")
        r = self._saida(client, auth_headers, p["id"], finalidade="qualquer_coisa")
        assert r.status_code == 422

    def test_ativo_instalado_inexistente_e_recusado(self, client, auth_headers):
        p = self._consumivel(client, auth_headers, "FIN-7")
        r = self._saida(client, auth_headers, p["id"],
                        finalidade="instalacao", ativo_instalado_id=999999)
        assert r.status_code == 404

    def test_saida_sem_finalidade_continua_valendo(self, client, auth_headers):
        """Compatibilidade: o campo é opcional, o uso antigo segue funcionando."""
        p = self._consumivel(client, auth_headers, "FIN-8")
        r = self._saida(client, auth_headers, p["id"])
        assert r.status_code == 201
        assert r.json()["finalidade"] is None

    def test_historico_mostra_a_finalidade(self, client, auth_headers):
        p = self._consumivel(client, auth_headers, "FIN-9")
        a = self._equipamento(client, auth_headers, "EQ-FIN-3")
        self._saida(client, auth_headers, p["id"],
                    finalidade="instalacao", ativo_instalado_id=a["id"])

        item = client.get("/api/v1/movimentacoes",
                          params={"produto_id": p["id"]}, headers=auth_headers).json()["items"][0]
        assert item["finalidade_rotulo"] == "Instalação"
        assert item["ativo_instalado_patrimonio"] == "EQ-FIN-3"


class TestResumoDoAtivoNaBusca:
    """A busca precisa devolver o hostname para a tela poder MOSTRAR.

    O hostname não fica no topo do ativo, e sim na ficha técnica (`ti`). Se a
    resposta não o trouxer, quem procura por "DTAT0001" vê um resultado que não
    casa com o que digitou — e a busca parece quebrada.
    """

    def _com_hostname(self, client, h, patrimonio, hostname):
        a = client.post("/api/v1/ativos", json={
            "dominio": "ti", "patrimonio": patrimonio, "tipo_item": "ativo",
        }, headers=h).json()
        client.put(f"/api/v1/ativos/{a['id']}", json={"ti": {"hostname": hostname}}, headers=h)
        return a

    def test_busca_devolve_o_hostname(self, client, auth_headers):
        self._com_hostname(client, auth_headers, "RSM-1", "RSMHOST01")

        itens = client.get("/api/v1/ativos",
                           params={"search": "RSMHOST01", "dominio": "ti"},
                           headers=auth_headers).json()["items"]
        assert itens, "a busca por hostname não devolveu nada"
        item = itens[0]
        # Aceita as duas formas: no topo ou dentro da ficha técnica.
        host = item.get("hostname") or (item.get("ti") or {}).get("hostname")
        assert host == "RSMHOST01", (
            "a resposta não traz o hostname — a tela não tem como mostrar por que "
            "aquele resultado casou com a busca"
        )

    def test_busca_devolve_patrimonio_e_modelo(self, client, auth_headers):
        self._com_hostname(client, auth_headers, "RSM-2", "RSMHOST02")

        itens = client.get("/api/v1/ativos",
                           params={"search": "RSMHOST02", "dominio": "ti"},
                           headers=auth_headers).json()["items"]
        assert itens[0]["patrimonio"] == "RSM-2"

    def test_busca_por_parte_do_hostname(self, client, auth_headers):
        self._com_hostname(client, auth_headers, "RSM-3", "PARTHOST77")

        itens = client.get("/api/v1/ativos",
                           params={"search": "PARTHOST", "dominio": "ti"},
                           headers=auth_headers).json()["items"]
        assert any(i["patrimonio"] == "RSM-3" for i in itens)


class TestHostnameNoHistorico:
    """O histórico mostra o hostname do equipamento que recebeu o consumível.

    O patrimônio sozinho não diz muito a quem lê o histórico no dia a dia; o
    nome de rede, sim.
    """

    def test_instalacao_traz_patrimonio_e_hostname(self, client, auth_headers):
        p = client.post("/api/v1/produtos", json={
            "sku": "HOST-HIST-1", "nome": "Tonner X", "dominio": "ti", "estoque_minimo": 1,
        }, headers=auth_headers).json()
        a = client.post("/api/v1/ativos", json={
            "dominio": "ti", "patrimonio": "TP9800001176", "tipo_item": "ativo",
        }, headers=auth_headers).json()
        client.put(f"/api/v1/ativos/{a['id']}",
                   json={"ti": {"hostname": "TP980HOST01"}}, headers=auth_headers)

        client.post("/api/v1/movimentacoes", json={
            "tipo": "saida", "produto_id": p["id"], "quantidade": 1,
            "finalidade": "instalacao", "ativo_instalado_id": a["id"],
        }, headers=auth_headers)

        item = client.get("/api/v1/movimentacoes",
                          params={"produto_id": p["id"]}, headers=auth_headers).json()["items"][0]
        assert item["ativo_instalado_patrimonio"] == "TP9800001176"
        assert item["ativo_instalado_hostname"] == "TP980HOST01"

    def test_ativo_sem_ficha_tecnica_nao_quebra(self, client, auth_headers):
        """Equipamento sem ficha técnica: o hostname vem nulo, sem erro."""
        p = client.post("/api/v1/produtos", json={
            "sku": "HOST-HIST-2", "nome": "Tonner Y", "dominio": "ti", "estoque_minimo": 1,
        }, headers=auth_headers).json()
        a = client.post("/api/v1/ativos", json={
            "dominio": "ti", "patrimonio": "SEM-FICHA-1", "tipo_item": "ativo",
        }, headers=auth_headers).json()

        client.post("/api/v1/movimentacoes", json={
            "tipo": "saida", "produto_id": p["id"], "quantidade": 1,
            "finalidade": "instalacao", "ativo_instalado_id": a["id"],
        }, headers=auth_headers)

        item = client.get("/api/v1/movimentacoes",
                          params={"produto_id": p["id"]}, headers=auth_headers).json()["items"][0]
        assert item["ativo_instalado_patrimonio"] == "SEM-FICHA-1"
        assert item["ativo_instalado_hostname"] is None

    def test_descarte_nao_tem_hostname(self, client, auth_headers):
        p = client.post("/api/v1/produtos", json={
            "sku": "HOST-HIST-3", "nome": "Tonner Z", "dominio": "ti", "estoque_minimo": 1,
        }, headers=auth_headers).json()
        client.post("/api/v1/movimentacoes", json={
            "tipo": "saida", "produto_id": p["id"], "quantidade": 1, "finalidade": "descarte",
        }, headers=auth_headers)

        item = client.get("/api/v1/movimentacoes",
                          params={"produto_id": p["id"]}, headers=auth_headers).json()["items"][0]
        assert item["ativo_instalado_hostname"] is None
        assert item["finalidade_rotulo"] == "Descarte"
