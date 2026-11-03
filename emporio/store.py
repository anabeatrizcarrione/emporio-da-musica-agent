"""Store facts and policy rules used for deterministic answers.

Transcribed from the policy manual (§1.2, §2, §3, §5.1); tests/test_store.py
checks them against the PDF text so the two cannot drift apart silently. Where
the manual contradicts itself, the choice made here is documented in the README:
- Phone/WhatsApp: (67) 3341-4444 appears on the cover and in the company data
  table; §7 mentions (67) 3321-4500 once. The company data table wins.
- E-mail: §1.2 spells the domain with an accent ("empóriodamusica"), which is
  not a valid domain; the cover's spelling is used.
- Installments: the summary table in §3 says "parcela mínima de R$ 100,00" for
  every case; the detailed tiers of §3.1 are more specific and win.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

STORE_PROFILE = {
    "nome": "Empório da Música",
    "slogan": "Sua música começa aqui.",
    "endereco": "Rua 14 de Maio, 3200 — Centro, Campo Grande - MS, CEP 79202-333",
    "telefone_whatsapp": "(67) 3341-4444",
    "email": "contato@emporiodamusica.com.br",
    "fundacao": 2008,
    "o_que_vendemos": "Exclusivamente instrumentos musicais. Não vendemos acessórios "
    "(cordas, palhetas, cabos, cases, pedais, amplificadores).",
}

# weekday() -> (open, close); Sunday closed. Holidays are also closed, but no
# holiday calendar was provided.
OPENING_HOURS: dict[int, tuple[time, time] | None] = {
    0: (time(9), time(18)),
    1: (time(9), time(18)),
    2: (time(9), time(18)),
    3: (time(9), time(18)),
    4: (time(9), time(18)),
    5: (time(9), time(13)),
    6: None,
}
WEEKDAY_NAMES = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]

# Payment rules (§3, §3.1)
PIX_DISCOUNT = 0.05
MAX_INSTALLMENTS = 12
# (first, last, minimum installment value); paying in 1x has no minimum.
INSTALLMENT_TIERS = [(2, 3, 50.0), (4, 6, 80.0), (7, 12, 100.0)]
SPLIT_PAYMENT_MIN_TOTAL = 2000.0

# Delivery in the metropolitan area (§5.1)
METRO_CITY = "Campo Grande"
METRO_MAX_BUSINESS_DAYS = 3


def installment_minimum(installments: int) -> float:
    """Minimum value of each installment when paying in `installments` times."""
    if installments == 1:
        return 0.0
    for first, last, minimum in INSTALLMENT_TIERS:
        if first <= installments <= last:
            return minimum
    raise ValueError(f"Installments must be between 1 and {MAX_INSTALLMENTS}, got {installments}")


def business_days_between(start: date, end: date) -> int:
    """Weekdays after `start` up to and including `end` (holidays are not modelled)."""
    return sum(1 for offset in range(1, (end - start).days + 1) if (start + timedelta(days=offset)).weekday() < 5)


def is_open(now: datetime) -> bool:
    hours = OPENING_HOURS[now.weekday()]
    return hours is not None and hours[0] <= now.time() < hours[1]


def next_opening(now: datetime) -> datetime:
    """The next moment the store opens, strictly after `now`'s current open period."""
    for offset in range(8):
        day = now.date() + timedelta(days=offset)
        hours = OPENING_HOURS[day.weekday()]
        if hours is None:
            continue
        opening = datetime.combine(day, hours[0])
        if opening > now:
            return opening
    raise RuntimeError("Opening hours table has no open day")
