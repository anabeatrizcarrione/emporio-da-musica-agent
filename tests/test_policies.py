def test_manual_is_split_into_ten_sections(policies):
    assert policies.topics == [
        "sobre_a_emporio_da_musica",
        "horario_de_funcionamento",
        "formas_de_pagamento",
        "politica_de_trocas_e_devolucoes",
        "politica_de_frete_e_entregas",
        "promocoes_e_descontos",
        "atendimento_via_whatsapp",
        "garantia",
        "privacidade_e_protecao_de_dados",
        "disposicoes_finais",
    ]


def test_section_content_is_clean(policies):
    returns = policies.get("politica_de_trocas_e_devolucoes").text
    assert "7 (sete) dias corridos" in returns
    assert "Página" not in returns
    payment = policies.get("formas_de_pagamento").text
    assert "- Parcelamento de 4x a 6x: sem juros, parcela mínima de R$ 80,00." in payment
    assert "PIX | Pagamento à vista" in payment


def test_numbered_lists_do_not_start_new_sections(policies):
    service = policies.get("atendimento_via_whatsapp").text
    assert "1. Saudação:" in service
    assert "5. Fechamento:" in service
