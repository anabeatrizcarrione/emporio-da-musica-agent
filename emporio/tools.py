"""Agent tools: deterministic functions over the store data and the policy manual.

Each tool returns a JSON-serialisable dict. Anything involving arithmetic,
dates or business rules (installments, PIX discount, return windows, opening
hours, identity checks) is computed here and never left to the language model.
Money is computed with Decimal and rounded half-up to the cent.
"""

from __future__ import annotations

import difflib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Callable

from emporio import store
from emporio.data import Availability, Category, Order, Product, StoreData, digits, normalize
from emporio.policies import PolicyManual

logger = logging.getLogger(__name__)

AVAILABILITY_LABELS = {
    Availability.IN_STOCK: "disponível",
    Availability.OUT_OF_STOCK: "fora de estoque no momento",
    Availability.DISCONTINUED: "descontinuado (não faz mais parte do catálogo)",
    Availability.COMING_SOON: "em breve (ainda não disponível para venda)",
}

# Meaning of each status is an assumption: the dataset only provides the code.
ORDER_STATUS_LABELS = {
    "pending": "aguardando confirmação do pagamento",
    "confirmed": "pagamento confirmado, pedido em separação",
    "shipped": "enviado",
    "delivered": "entregue",
    "cancelled": "cancelado",
}

MAX_SEARCH_RESULTS = 30
DEFAULT_SEARCH_LIMIT = 10
# Specs that define "the same kind of instrument" when suggesting alternatives.
SIMILARITY_SPECS = ("strings", "electronics")
# Internal service procedures (§7) and closing remarks (§10) are not exposed to the model: their rules
# are already in the system prompt, and §7 lists a WhatsApp number that conflicts with the company data.
INTERNAL_POLICY_TOPICS = {"atendimento_via_whatsapp", "disposicoes_finais"}
POLICY_NOTE = (
    "Endereço, contatos e horários: use get_store_info (o manual tem divergências nesses dados). "
    "Produtos à venda: só o que as ferramentas de catálogo retornam, não a descrição geral do manual."
)
INTERNAL_ERROR = "Erro interno ao executar esta consulta. Peça desculpas e, se preciso, encaminhe para a equipe."
SHARED_EMAIL_MESSAGE = (
    "Este e-mail está em mais de um cadastro, então não serve para confirmar o pedido. "
    "Peça o telefone usado na compra."
)
UNVERIFIED_TICKET_NOTE = (
    "Chamado registrado com solicitante NÃO verificado para este pedido: a equipe vai confirmar a "
    "identidade antes de qualquer ação no pedido."
)
CENT = Decimal("0.01")


@dataclass
class ToolContext:
    data: StoreData
    policies: PolicyManual
    clock: Callable[[], datetime]
    handoff_log: Path


class ToolError(Exception):
    """A problem the model should see and can recover from (bad id, unknown topic...)."""


# --------------------------------------------------------------------------- helpers


def _as_int(value: Any, field: str) -> int:
    """Accept 7, 7.0, "7", "#7" or "0007" from the model; reject anything else clearly."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    try:
        return int(str(value).strip().lstrip("#"))
    except ValueError:
        raise ToolError(f"'{field}' must be a whole number, got {value!r}.") from None


def _as_float(value: Any, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ToolError(f"'{field}' must be a number, got {value!r}.") from None


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _money(value: Decimal) -> float:
    return float(value.quantize(CENT, rounding=ROUND_HALF_UP))


def _when(moment: datetime) -> str:
    return f"{store.WEEKDAY_NAMES[moment.weekday()]}, {moment:%d/%m/%Y} às {moment:%H:%M}"


def _product_summary(p: Product) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "product_id": p.id,
        "name": p.name,
        "category": p.category.name,
        "price_brl": p.price,
        "availability": AVAILABILITY_LABELS[p.availability],
    }
    if p.sellable:
        summary["stock_quantity"] = p.stock
    promo = p.active_promotion
    if promo:
        summary["active_promotion"] = {
            "name": promo.name,
            "discount_percent": promo.discount_percent,
            "promotional_price_brl": p.effective_price,
        }
    return summary


def _get_product(ctx: ToolContext, product_id: Any) -> Product:
    pid = _as_int(product_id, "product_id")
    product = ctx.data.products.get(pid)
    if product is None:
        raise ToolError(f"No product with id {pid}.")
    return product


def _category_terms(category: Category) -> list[str]:
    """Category words plus naive singulars, so 'violão' or 'ukulele' match their category."""
    terms = []
    for word in normalize(category.name).split():
        terms.append(word)
        if word.endswith("oes"):
            terms.append(word[:-3] + "ao")
        elif word.endswith("s"):
            terms.append(word[:-1])
    return terms


def _matches(query: str, p: Product) -> bool:
    """Every query word appears in the product's name, specs or category (spacing-insensitive)."""
    haystack = " ".join([p.search_key, *(normalize(v) for v in p.specs.values()), *_category_terms(p.category)])
    compact = haystack.replace(" ", "")
    return all(tok in haystack or tok in compact for tok in normalize(query).split())


def _names_exactly(query: str, p: Product) -> bool:
    """The query, ignoring spaces, equals a run of whole words of the name ('Martin D-28' is not 'Martin D-28E')."""
    target = normalize(query).replace(" ", "")
    words = p.search_key.split()
    return any("".join(words[i:j]) == target for i in range(len(words)) for j in range(i + 1, len(words) + 1))


def _closest(query: str, products: list[Product], limit: int = 5) -> list[Product]:
    """Fuzzy fallback for typos or models we don't carry ('Fender Jazz Bass')."""
    q = normalize(query)
    tokens = q.split()

    def score(p: Product) -> float:
        hits = sum(tok in p.search_key for tok in tokens) / max(len(tokens), 1)
        return hits + 0.5 * difflib.SequenceMatcher(None, q, p.search_key).ratio()

    ranked = sorted(products, key=score, reverse=True)
    return [p for p in ranked if score(p) >= 0.4][:limit]


def _alternatives(p: Product, products: list[Product], limit: int = 3) -> list[dict[str, Any]]:
    """Sellable products of the same category: same strings and pickup first, then closest in price."""

    def distance(o: Product) -> tuple[int, float]:
        different_specs = sum(o.specs.get(k) != p.specs[k] for k in SIMILARITY_SPECS if k in p.specs)
        return different_specs, abs(o.effective_price - p.price)

    same_category = [o for o in products if o.category.id == p.category.id and o.sellable and o.id != p.id]
    same_category.sort(key=distance)
    return [_product_summary(o) for o in same_category[:limit]]


def installment_options(total: float) -> list[dict[str, Any]]:
    amount = _decimal(total)
    return [
        {"installments": n, "installment_value_brl": _money(amount / n)}
        for n in range(1, store.MAX_INSTALLMENTS + 1)
        if amount / n >= _decimal(store.installment_minimum(n))
    ]


def _window(start: date, days: int, today: date) -> dict[str, Any]:
    deadline = start + timedelta(days=days)
    return {
        "counted_from": start.isoformat(),
        "deadline": deadline.isoformat(),
        "within_window": today <= deadline,
    }


def _shared_email(ctx: ToolContext, contact: str) -> bool:
    """An e-mail that belongs to several customer records can't prove who is asking."""
    return "@" in contact and len(ctx.data.customers_with_email(contact)) > 1


def _contact_matches(order: Order, contact: str) -> bool:
    contact = contact.strip()
    if "@" in contact:
        return contact.lower() == order.customer.email.lower()
    given = digits(contact)
    if len(given) < 8:
        return False
    tail = min(len(given), 9)  # ignore country/area code differences
    return digits(order.customer.phone)[-tail:] == given[-tail:]


def _payment_label(method: str) -> str:
    if method.startswith("credit_"):
        return f"cartão de crédito em {method.removeprefix('credit_')}"
    return {"pix": "PIX", "debit": "cartão de débito", "boleto": "boleto bancário"}.get(method, method)


def customer_policy_topics(policies: PolicyManual) -> list[str]:
    return [t for t in policies.topics if t not in INTERNAL_POLICY_TOPICS]


# --------------------------------------------------------------------------- tools


def search_products(
    ctx: ToolContext,
    query: str | None = None,
    category: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    string_type: str | None = None,
    acoustic_electric: bool | None = None,
    include_unavailable: bool = False,
    sort: str = "price_asc",
    limit: int | None = DEFAULT_SEARCH_LIMIT,
) -> dict[str, Any]:
    products = list(ctx.data.products.values())
    result: dict[str, Any] = {}

    if category:
        cat = ctx.data.category_by_slug(category)
        if cat is None:
            raise ToolError(f"Unknown category '{category}'.")
        products = [p for p in products if p.category.id == cat.id]
        if not products:
            available = sorted({p.category.name for p in ctx.data.products.values() if p.sellable})
            note = (
                f"A loja não tem produtos da categoria '{cat.name}' no catálogo atual. "
                f"Categorias com produtos à venda: {', '.join(available)}."
            )
            return {"total_found": 0, "products": [], "note": note, "categories_with_products": available}
    if string_type:
        products = [p for p in products if p.specs.get("strings") == string_type]
    if acoustic_electric is not None:
        wanted = "yes" if acoustic_electric else "no"
        products = [p for p in products if p.specs.get("electronics") == wanted]
    if min_price is not None:
        floor = _as_float(min_price, "min_price")
        products = [p for p in products if p.effective_price >= floor]
    if max_price is not None:
        ceiling = _as_float(max_price, "max_price")
        products = [p for p in products if p.effective_price <= ceiling]
    if query:
        matched = [p for p in products if _matches(query, p)]
        if not matched:
            matched = _closest(query, products)
            if matched:
                result["note"] = "Nenhum produto com esse nome exato; estes são os nomes mais parecidos."
        products = matched

    if not include_unavailable:
        hidden = [p for p in products if not p.sellable]
        products = [p for p in products if p.sellable]
        if hidden:
            result["unavailable_matches_hidden"] = len(hidden)

    products.sort(key=lambda p: p.effective_price, reverse=(sort == "price_desc"))
    limit = DEFAULT_SEARCH_LIMIT if limit is None else max(1, min(_as_int(limit, "limit"), MAX_SEARCH_RESULTS))
    result.update(
        total_found=len(products),
        returned=min(len(products), limit),
        products=[_product_summary(p) for p in products[:limit]],
    )
    return result


def get_product_details(ctx: ToolContext, product_id: Any = None, name: str | None = None) -> dict[str, Any]:
    all_products = list(ctx.data.products.values())
    if product_id is not None:
        product = _get_product(ctx, product_id)
    elif name:
        exact = [p for p in all_products if _matches(name, p)]
        if len(exact) > 1:
            whole_name = [p for p in exact if _names_exactly(name, p)]
            if len(whole_name) == 1:
                exact = whole_name
        if len(exact) != 1:
            candidates = exact or _closest(name, all_products)
            if not candidates:
                return {"found": False, "message": "Nenhum produto parecido com esse nome no catálogo."}
            return {
                "found": False,
                "message": "Mais de um produto (ou nenhum exato) corresponde ao nome; confirme qual o cliente quer.",
                "candidates": [_product_summary(p) for p in candidates],
            }
        product = exact[0]
    else:
        raise ToolError("Provide product_id or name.")

    details = _product_summary(product)
    details["found"] = True
    details["specs"] = product.specs
    if product.description_reliable:
        details["description"] = product.description
    else:
        details["description_note"] = (
            "Descrição cadastrada inconsistente com o produto; use apenas nome e especificações."
        )
    expired = [p for p in product.promotions if not p.is_active]
    if expired:
        details["expired_promotions"] = [f"{p.name} ({p.discount_percent:g}%) — encerrada" for p in expired]
    if not product.sellable:
        details["similar_available_products"] = _alternatives(product, all_products)
    return details


def simulate_payment(
    ctx: ToolContext,
    items: list[dict[str, Any]] | None = None,
    amount_brl: float | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if items:
        lines, warnings = [], []
        total = list_total = pix_total = Decimal(0)
        has_promotion = False
        for item in items:
            if not isinstance(item, dict):
                raise ToolError("Each item must be an object with product_id and optional quantity.")
            product = _get_product(ctx, item.get("product_id"))
            quantity = 1 if item.get("quantity") is None else max(1, _as_int(item["quantity"], "quantity"))
            line_total = _decimal(product.effective_price) * quantity
            promotional = product.active_promotion is not None
            has_promotion |= promotional
            total += line_total
            list_total += _decimal(product.price) * quantity
            # The PIX discount does not stack with promotions (policy §6.2), so it applies per item.
            if promotional:
                pix_total += line_total
            else:
                pix_total += (line_total * (1 - _decimal(store.PIX_DISCOUNT))).quantize(CENT, ROUND_HALF_UP)
            lines.append({**_product_summary(product), "quantity": quantity, "line_total_brl": _money(line_total)})
            if not product.sellable:
                label = AVAILABILITY_LABELS[product.availability]
                warnings.append(f"{product.name}: {label}; não pode ser vendido agora.")
            elif quantity > product.stock:
                warnings.append(f"{product.name}: só {product.stock} unidade(s) em estoque.")
        result.update(items=lines, list_price_total_brl=_money(list_total))
        if warnings:
            result["warnings"] = warnings
        total_brl = _money(total)
        pix: dict[str, Any] = {"total_brl": _money(pix_total)}
        if has_promotion:
            pix["note"] = "O desconto de 5% do PIX não vale para itens já em promoção (não é cumulativo)."
        else:
            pix["discount_percent"] = round(store.PIX_DISCOUNT * 100)
    elif amount_brl is not None and _as_float(amount_brl, "amount_brl") > 0:
        total_brl = _money(_decimal(float(amount_brl)))
        pix = {
            "total_brl": _money(_decimal(total_brl) * (1 - _decimal(store.PIX_DISCOUNT))),
            "discount_percent": round(store.PIX_DISCOUNT * 100),
            "note": (
                "Valor avulso: considera que não há itens em promoção. "
                "Para produtos do catálogo, informe os itens."
            ),
        }
    else:
        raise ToolError("Provide items (product_id and quantity) or a positive amount_brl.")

    result["total_brl"] = total_brl
    result["pix"] = pix
    result["debit_card"] = {"total_brl": total_brl}
    result["boleto"] = {"total_brl": total_brl, "note": "Compensação em até 3 dias úteis."}
    options = installment_options(total_brl)
    result["credit_card"] = {
        "interest": "sem juros",
        "max_installments": options[-1]["installments"],
        "options": options,
    }
    result["split_payment_allowed"] = total_brl > store.SPLIT_PAYMENT_MIN_TOTAL
    return result


def check_order(ctx: ToolContext, order_id: Any, customer_contact: str) -> dict[str, Any]:
    contact = str(customer_contact or "")
    # Checked before looking at the order, so the answer says nothing about the order itself.
    if _shared_email(ctx, contact):
        return {"verified": False, "needs_phone": True, "message": SHARED_EMAIL_MESSAGE}
    order = ctx.data.orders.get(_as_int(order_id, "order_id"))
    # Same answer for "no such order" and "wrong contact" so nobody can probe order numbers.
    if order is None or not _contact_matches(order, contact):
        return {
            "verified": False,
            "message": "Não encontramos um pedido com esse número para o e-mail/telefone informado.",
        }

    today = ctx.clock().date()
    result: dict[str, Any] = {
        "verified": True,
        "order_id": order.id,
        "customer_first_name": order.customer.first_name,
        "order_date": order.order_date.isoformat(),
        "days_since_order": (today - order.order_date).days,
        "status": order.status,
        "status_label": ORDER_STATUS_LABELS[order.status],
        "items": [{"product_id": i.product.id, "name": i.product.name, "quantity": i.quantity} for i in order.items],
        # As recorded: the data doesn't show whether a PIX discount was applied, so not "amount charged".
        "order_total_brl": order.total,
        "payment_method": _payment_label(order.payment_method),
        "today": today.isoformat(),
    }
    if order.tracking_code:
        result["tracking_code"] = order.tracking_code
        result["tracking_where"] = "site dos Correios ou da Jadlog"
    if order.estimated_delivery:
        result["estimated_delivery"] = order.estimated_delivery.isoformat()
        if order.status in {"confirmed", "shipped"} and today > order.estimated_delivery:
            result["delivery_overdue"] = True
    if order.notes:
        result["notes"] = order.notes
    if order.status == "delivered" and order.estimated_delivery:
        # Assumption: no real delivery date exists, so the estimated one is used as "received on".
        received = order.estimated_delivery
        result["received_on_assumed"] = received.isoformat()
        result["return_windows"] = {
            "arrependimento_7_dias_apos_recebimento": _window(received, 7, today),
            "troca_por_preferencia_7_dias_apos_recebimento": _window(received, 7, today),
            "troca_por_defeito_30_dias_apos_compra": _window(order.order_date, 30, today),
            "garantia_legal_90_dias_apos_recebimento": _window(received, 90, today),
        }
    return result


def get_store_policy(ctx: ToolContext, topics: list[str] | str) -> dict[str, Any]:
    if isinstance(topics, str):
        topics = [topics]
    available = customer_policy_topics(ctx.policies)
    sections = []
    for topic in topics:
        if topic not in available:
            raise ToolError(f"Unknown topic '{topic}'. Valid topics: {', '.join(available)}")
        section = ctx.policies.get(topic)
        sections.append({"section": f"{section.number}. {section.title}", "text": section.text})
    return {"sections": sections, "note": POLICY_NOTE}


def get_store_info(ctx: ToolContext) -> dict[str, Any]:
    now = ctx.clock()
    hours = []
    for weekday, name in enumerate(store.WEEKDAY_NAMES):
        slot = store.OPENING_HOURS[weekday]
        hours.append(f"{name}: {slot[0]:%H:%M} às {slot[1]:%H:%M}" if slot else f"{name}: fechado")
    info: dict[str, Any] = {
        **store.STORE_PROFILE,
        "horario_de_funcionamento": hours,
        "feriados": "fechado (horário pode ser estendido em Black Friday, aniversário da loja e Natal)",
        "agora": f"{store.WEEKDAY_NAMES[now.weekday()]}, {now:%d/%m/%Y %H:%M}",
        "loja_aberta_agora": store.is_open(now),
    }
    if not info["loja_aberta_agora"]:
        info["proxima_abertura"] = _when(store.next_opening(now))
    return info


def escalate_to_human(
    ctx: ToolContext,
    reason: str,
    summary: str,
    customer_name: str | None = None,
    customer_contact: str | None = None,
    order_id: int | None = None,
) -> dict[str, Any]:
    now = ctx.clock()
    # Tickets about an order record whether the requester proved they own it, so the team never acts
    # on someone else's order because of a chat message.
    requester_verified = None
    if order_id is not None:
        order_id = _as_int(order_id, "order_id")
        order = ctx.data.orders.get(order_id)
        contact = str(customer_contact or "")
        requester_verified = bool(order) and not _shared_email(ctx, contact) and _contact_matches(order, contact)
    ticket = {
        "ticket_id": f"EM-{uuid.uuid4().hex[:6].upper()}",
        "created_at": now.isoformat(timespec="minutes"),
        "reason": reason,
        "summary": summary,
        "customer_name": customer_name,
        "customer_contact": customer_contact,
        "order_id": order_id,
        "requester_verified": requester_verified,
    }
    ctx.handoff_log.parent.mkdir(parents=True, exist_ok=True)
    with ctx.handoff_log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(ticket, ensure_ascii=False) + "\n")
    result = {
        "ticket_id": ticket["ticket_id"],
        "status": "registrado e encaminhado para a equipe",
        "response_deadline": "até 24 horas úteis",
        "store_open_now": store.is_open(now),
    }
    if not result["store_open_now"]:
        result["team_back_at"] = _when(store.next_opening(now))
    if requester_verified is False:
        result["note"] = UNVERIFIED_TICKET_NOTE
    return result


# --------------------------------------------------------------------------- registry

HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "search_products": search_products,
    "get_product_details": get_product_details,
    "simulate_payment": simulate_payment,
    "check_order": check_order,
    "get_store_policy": get_store_policy,
    "get_store_info": get_store_info,
    "escalate_to_human": escalate_to_human,
}


def tool_definitions(ctx: ToolContext) -> list[dict[str, Any]]:
    """JSON-schema tool definitions sent to the model (enums derived from the data)."""
    category_slugs = sorted(c.slug for c in ctx.data.categories.values())
    return [
        {
            "name": "search_products",
            "description": (
                "Search the store catalog. Use for any question about which instruments exist, prices in a range, "
                "or 'what options do you have'. Use `category` for the instrument type (violão, guitarra, ukulele...) "
                "and `query` for brand/model words (e.g. 'Takamine', 'GD20'). By default only returns products "
                "available for sale; `unavailable_matches_hidden` tells you if out-of-stock/discontinued matches "
                "were omitted. Price filters use the current price (promotional price when a promotion is active)."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Brand/model words to match in the product name."},
                    "category": {"type": "string", "enum": category_slugs},
                    "min_price": {"type": "number", "description": "Minimum price in BRL."},
                    "max_price": {"type": "number", "description": "Maximum price in BRL."},
                    "string_type": {
                        "type": "string",
                        "enum": ["nylon", "steel"],
                        "description": "Violões/ukuleles only: nylon or steel (aço) strings.",
                    },
                    "acoustic_electric": {
                        "type": "boolean",
                        "description": (
                            "Violões/ukuleles only: true = eletroacústico (with pickup), false = acoustic only."
                        ),
                    },
                    "include_unavailable": {
                        "type": "boolean",
                        "description": "Also return out-of-stock, discontinued and coming-soon products.",
                    },
                    "sort": {"type": "string", "enum": ["price_asc", "price_desc"]},
                    "limit": {
                        "type": "integer",
                        "description": f"Max results (default {DEFAULT_SEARCH_LIMIT}, max {MAX_SEARCH_RESULTS}).",
                    },
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "get_product_details",
            "description": (
                "Full details of one product: price, active promotion, availability, stock, specs, description, "
                "promotions that have ended, and similar available products when it can't be sold. Use when the "
                "customer asks about a specific instrument (price, availability, 'tem promoção?'). Accepts the "
                "product_id from a search or a free-text name; if the name is ambiguous it returns candidates."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "integer"},
                    "name": {"type": "string", "description": "Product name as the customer wrote it."},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "simulate_payment",
            "description": (
                "Compute payment options for one or several catalog products (a cart), or for an arbitrary amount: "
                "PIX price, debit, boleto and every valid credit-card installment option according to store rules. "
                "Promotions and the PIX discount are applied per item, and it warns when a quantity exceeds stock or "
                "a product can't be sold. Always use this instead of doing the math yourself when the customer asks "
                "about parcelamento, PIX or payment conditions; put every product in a single call."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "description": "Catalog products to pay for.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "product_id": {"type": "integer"},
                                "quantity": {"type": "integer", "description": "Units (default 1)."},
                            },
                            "required": ["product_id"],
                            "additionalProperties": False,
                        },
                    },
                    "amount_brl": {
                        "type": "number",
                        "description": (
                            "Only for an amount not tied to catalog products (assumes no promotional items)."
                        ),
                    },
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "check_order",
            "description": (
                "Look up an order's status, items, tracking code, delivery estimate and (for delivered orders) "
                "return/exchange/warranty windows computed for today. Requires the order number AND the e-mail or "
                "phone used in the purchase; ask the customer for both before calling. Never reveal order data if "
                "`verified` is false. If `needs_phone` is true, the e-mail belongs to more than one customer: ask "
                "for the phone used in the purchase."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "integer"},
                    "customer_contact": {"type": "string", "description": "E-mail or phone given by the customer."},
                },
                "required": ["order_id", "customer_contact"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_store_policy",
            "description": (
                "Read sections of the store's official policy manual. Use before answering anything about rules: "
                "exchanges/returns, shipping, payment rules, promotions rules, warranty, data privacy, about the store."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "topics": {
                        "type": "array",
                        "items": {"type": "string", "enum": customer_policy_topics(ctx.policies)},
                        "minItems": 1,
                    }
                },
                "required": ["topics"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_store_info",
            "description": (
                "Store address, phone/WhatsApp, e-mail, opening hours, the current date/time and whether the store is "
                "open right now (with the next opening time if closed)."
            ),
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "escalate_to_human",
            "description": (
                "Register a ticket for the human team. Use for complaints, problems with an order (delays, damage, "
                "wrong item), return/exchange requests the customer wants to start, questions the policy does not "
                "answer, or when the customer asks for a person. Tell the customer the ticket id and the deadline, "
                "and when the team is back if the store is closed. For a ticket about a specific order, pass the "
                "order_id and the contact the customer gave: if it doesn't match the order, the ticket is marked "
                "as coming from an unverified requester."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "enum": [
                            "complaint", "order_problem", "return_or_exchange",
                            "policy_question", "human_requested", "other",
                        ],
                    },
                    "summary": {"type": "string", "description": "Short summary for the team, in Portuguese."},
                    "customer_name": {"type": "string"},
                    "customer_contact": {"type": "string"},
                    "order_id": {"type": "integer"},
                },
                "required": ["reason", "summary"],
                "additionalProperties": False,
            },
        },
    ]


def run_tool(ctx: ToolContext, name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Execute a tool call. Returns (result, is_error); never raises."""
    handler = HANDLERS.get(name)
    if handler is None:
        return {"error": f"Unknown tool '{name}'."}, True
    try:
        return handler(ctx, **arguments), False
    except (ToolError, TypeError, ValueError) as exc:
        # Bad or missing arguments: the model can read the message and retry.
        return {"error": str(exc)}, True
    except Exception:
        # A bug or an environment problem: log it, and let the model apologise or escalate.
        logger.exception("Tool %s failed with arguments %s", name, arguments)
        return {"error": INTERNAL_ERROR}, True
