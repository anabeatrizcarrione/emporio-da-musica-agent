"""Store facts and policy rules in code must match the policy manual they were transcribed from."""

import re
from datetime import date

import pytest
from pypdf import PdfReader

from emporio import store
from emporio.config import POLICY_PDF


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def brl(value: float) -> str:
    """2000.0 -> 'R$ 2.000,00', as amounts are written in the manual."""
    return "R$ " + f"{value:,.2f}".replace(",", "#").replace(".", ",").replace("#", ".")


def test_contacts_match_the_manual(policies):
    about = flat(policies.get("sobre_a_emporio_da_musica").text)
    street = store.STORE_PROFILE["endereco"].split(" — ")[0]
    cep = re.search(r"\d{5}-\d{3}", store.STORE_PROFILE["endereco"]).group()
    assert street in about and cep in about
    assert store.STORE_PROFILE["telefone_whatsapp"] in about
    cover = PdfReader(POLICY_PDF).pages[0].extract_text(extraction_mode="layout")
    assert store.STORE_PROFILE["email"] in cover


def test_opening_hours_match_the_manual(policies):
    hours = flat(policies.get("horario_de_funcionamento").text)
    assert len({store.OPENING_HOURS[d] for d in range(5)}) == 1  # same hours Monday to Friday
    weekday, saturday = store.OPENING_HOURS[0], store.OPENING_HOURS[5]
    assert f"Segunda a Sexta-feira | {weekday[0]:%H:%M} às {weekday[1]:%H:%M}" in hours
    assert f"Sábado | {saturday[0]:%H:%M} às {saturday[1]:%H:%M}" in hours
    assert store.OPENING_HOURS[6] is None and "Domingo e Feriados | Fechado" in hours


def test_payment_rules_match_the_manual(policies):
    payment = flat(policies.get("formas_de_pagamento").text)
    assert f"{store.PIX_DISCOUNT * 100:g}% de desconto" in payment
    assert f"Até {store.MAX_INSTALLMENTS}x sem juros" in payment
    first_tier, *other_tiers = store.INSTALLMENT_TIERS
    assert f"até {first_tier[1]}x" in payment and f"abaixo de {brl(first_tier[2])}" in payment
    for first, last, minimum in other_tiers:
        assert f"de {first}x a {last}x: sem juros, parcela mínima de {brl(minimum)}" in payment
    assert f"acima de {brl(store.SPLIT_PAYMENT_MIN_TOTAL)}" in payment


def test_metro_delivery_rule_matches_the_manual(policies):
    shipping = flat(policies.get("politica_de_frete_e_entregas").text)
    assert f"Região Metropolitana de {store.METRO_CITY}" in shipping
    assert f"Prazo de entrega: 1 a {store.METRO_MAX_BUSINESS_DAYS} dias úteis" in shipping


def test_installment_minimum():
    assert store.installment_minimum(1) == 0
    assert store.installment_minimum(3) == 50
    assert store.installment_minimum(6) == 80
    assert store.installment_minimum(12) == 100
    with pytest.raises(ValueError):
        store.installment_minimum(13)


def test_business_days_between():
    assert store.business_days_between(date(2026, 3, 20), date(2026, 3, 23)) == 1  # Friday -> Monday
    assert store.business_days_between(date(2025, 10, 15), date(2025, 10, 25)) == 7
