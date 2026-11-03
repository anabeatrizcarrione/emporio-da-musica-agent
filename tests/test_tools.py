import json
from datetime import datetime

from emporio import store
from emporio.tools import (
    ToolContext,
    check_order,
    escalate_to_human,
    get_product_details,
    get_store_info,
    installment_options,
    run_tool,
    search_products,
    simulate_payment,
    tool_definitions,
)

# ----------------------------------------------------------------- catalog


def test_violoes_up_to_1000_only_returns_sellable(ctx):
    result = search_products(ctx, category="violoes", max_price=1000, limit=30)
    ids = {p["product_id"] for p in result["products"]}
    assert result["total_found"] == 12
    assert 96 not in ids and 113 not in ids  # out of stock / discontinued
    assert result["unavailable_matches_hidden"] == 2
    prices = [p["price_brl"] for p in result["products"]]
    assert prices == sorted(prices)


def test_empty_category_explains_itself(ctx):
    result = search_products(ctx, category="cordas_orquestrais")
    assert result["total_found"] == 0
    assert "Cordas Orquestrais" in result["note"]
    # ...and points to what the store does sell, so the agent doesn't suggest another empty category.
    assert result["categories_with_products"] == [
        "Baixos", "Baterias e Percussão", "Guitarras", "Teclados e Pianos", "Ukuleles", "Violões",
    ]


def test_query_is_spacing_and_accent_insensitive(ctx):
    assert [p["product_id"] for p in search_products(ctx, query="takamine gd 20")["products"]] == [95]
    assert 93 in {p["product_id"] for p in search_products(ctx, query="Martin D28")["products"]}


def test_unknown_model_falls_back_to_closest_names(ctx):
    result = search_products(ctx, query="Fender Jazz Bass")
    assert "note" in result
    assert result["products"]


def test_instrument_type_words_match_their_category(ctx, store_data):
    ukuleles = search_products(ctx, query="ukulele", limit=30)
    assert ukuleles["total_found"] == 14  # 15 ukuleles, one is coming soon
    nylon = search_products(ctx, query="violão nylon", limit=30)
    expected = [
        p for p in store_data.products.values()
        if p.category.slug == "violoes" and p.specs["strings"] == "nylon" and p.sellable
    ]
    assert nylon["total_found"] == len(expected) and "note" not in nylon


def test_whole_model_name_wins_over_partial_matches(ctx):
    assert get_product_details(ctx, name="Kala KA-C")["product_id"] == 120  # not Kalani or other KA- models
    assert get_product_details(ctx, name="Martin D-28")["product_id"] == 93  # not the D-28E


def test_product_details_by_name_shows_expired_promotion(ctx):
    details = get_product_details(ctx, name="Takamine GD20")
    assert details["found"] and details["product_id"] == 95
    assert details["price_brl"] == 2199.0
    assert "active_promotion" not in details
    assert any("Oferta Especial" in p for p in details["expired_promotions"])


def test_ambiguous_name_returns_candidates(ctx):
    details = get_product_details(ctx, name="Takamine")
    assert details["found"] is False
    assert len(details["candidates"]) == 4


def test_out_of_stock_product_suggests_available_alternatives(ctx, store_data):
    details = get_product_details(ctx, product_id=96)
    assert details["availability"] == "fora de estoque no momento"
    alternatives = details["similar_available_products"]
    assert alternatives
    assert all(store_data.products[a["product_id"]].sellable for a in alternatives)


def test_alternatives_are_the_same_kind_of_instrument(ctx, store_data):
    # #96 is a steel-string violão without pickup: alternatives should be too, not nylon classicals.
    alternatives = get_product_details(ctx, product_id=96)["similar_available_products"]
    for a in alternatives:
        specs = store_data.products[a["product_id"]].specs
        assert (specs["strings"], specs["electronics"]) == ("steel", "no")


def test_unreliable_description_is_hidden(ctx):
    details = get_product_details(ctx, product_id=142)
    assert "description" not in details
    assert "description_note" in details


# ----------------------------------------------------------------- payment


def test_payment_simulation_for_regular_price(ctx):
    result = simulate_payment(ctx, items=[{"product_id": 95}])
    assert result["pix"]["total_brl"] == 2089.05
    assert result["credit_card"]["max_installments"] == 12
    assert result["credit_card"]["options"][-1]["installment_value_brl"] == 183.25
    assert result["split_payment_allowed"] is True


def test_pix_discount_does_not_stack_with_promotion(ctx):
    result = simulate_payment(ctx, items=[{"product_id": 90}])  # 18% off -> 1967.18
    assert result["total_brl"] == 1967.18
    assert result["pix"]["total_brl"] == 1967.18


def test_mixed_cart_applies_pix_only_to_regular_items(ctx):
    # #121 is on promotion (R$ 439,20); #120 is not (R$ 349,90 -> 332,41 with PIX).
    result = simulate_payment(ctx, items=[{"product_id": 121}, {"product_id": 120}])
    assert result["total_brl"] == 789.10
    assert result["pix"]["total_brl"] == 771.61
    assert "note" in result["pix"]


def test_cart_warns_about_stock_and_unsellable_items(ctx):
    result = simulate_payment(ctx, items=[{"product_id": 129, "quantity": 5}, {"product_id": 113}])
    warnings = " ".join(result["warnings"])
    assert "só 1 unidade" in warnings and "descontinuado" in warnings


def test_arbitrary_amount_assumes_no_promotions(ctx):
    result = simulate_payment(ctx, amount_brl=1000)
    assert result["pix"]["total_brl"] == 950.0
    assert "note" in result["pix"]


def test_installment_minimums_per_tier():
    assert [o["installments"] for o in installment_options(159.90)] == [1, 2, 3]
    assert installment_options(500)[-1]["installments"] == 6  # 7x would be 71.43 < 100
    assert installment_options(1200)[-1]["installments"] == 12


# ----------------------------------------------------------------- orders


def test_order_requires_matching_contact(ctx):
    assert check_order(ctx, order_id=8, customer_contact="someone@else.com")["verified"] is False
    assert check_order(ctx, order_id=999, customer_contact="anacarol.ferreira@coldmail.com")["verified"] is False


def test_order_accepts_email_or_phone_in_any_format(ctx):
    assert check_order(ctx, 8, "AnaCarol.Ferreira@coldmail.com ")["verified"]
    assert check_order(ctx, 8, "+55 67 99654-7821")["verified"]
    assert check_order(ctx, 8, "996547821")["verified"]


def test_shared_email_requires_the_phone(ctx):
    # Customers #11 and #43 share bruno.martins@jmail.com; order 10 belongs to #11.
    result = check_order(ctx, 10, "bruno.martins@jmail.com")
    assert result["verified"] is False and result["needs_phone"] is True
    assert check_order(ctx, 999, "bruno.martins@jmail.com") == result  # says nothing about the order
    assert check_order(ctx, 10, "(67) 98543-2109")["verified"] is True  # #11's phone
    assert check_order(ctx, 10, "(67) 99456-3456")["verified"] is False  # #43's phone


def test_overdue_shipment_is_flagged(ctx):
    result = check_order(ctx, 8, "anacarol.ferreira@coldmail.com")
    assert result["status"] == "shipped"
    assert result["order_total_brl"] == 349.9
    assert result["tracking_code"] == "BRJL5544332BR"
    assert result["delivery_overdue"] is True


def test_return_windows_depend_on_today(make_ctx, store_data):
    email = store_data.orders[7].customer.email  # delivered, received 2026-02-17
    early = check_order(make_ctx(datetime(2026, 2, 20, 10)), 7, email)
    late = check_order(make_ctx(datetime(2026, 3, 25, 10)), 7, email)
    assert early["return_windows"]["arrependimento_7_dias_apos_recebimento"]["within_window"] is True
    assert late["return_windows"]["arrependimento_7_dias_apos_recebimento"]["within_window"] is False
    assert late["return_windows"]["garantia_legal_90_dias_apos_recebimento"]["within_window"] is True


# ----------------------------------------------------------------- store / policy / escalation


def test_opening_hours():
    assert store.is_open(datetime(2026, 3, 25, 10))  # Wednesday
    assert not store.is_open(datetime(2026, 3, 28, 14))  # Saturday afternoon
    assert store.next_opening(datetime(2026, 3, 28, 14)) == datetime(2026, 3, 30, 9)  # Monday
    assert store.next_opening(datetime(2026, 3, 25, 7)) == datetime(2026, 3, 25, 9)


def test_store_info_reports_closed_store(make_ctx):
    info = get_store_info(make_ctx(datetime(2026, 3, 29, 11)))  # Sunday
    assert info["loja_aberta_agora"] is False
    assert info["proxima_abertura"].startswith("segunda-feira, 30/03/2026")


def test_unknown_policy_topic_is_a_recoverable_error(ctx):
    result, is_error = run_tool(ctx, "get_store_policy", {"topics": ["refunds"]})
    assert is_error and "Valid topics" in result["error"]


def test_internal_policy_sections_are_not_exposed(ctx):
    schema = next(t for t in tool_definitions(ctx) if t["name"] == "get_store_policy")
    topics = schema["input_schema"]["properties"]["topics"]["items"]["enum"]
    assert "atendimento_via_whatsapp" not in topics and "disposicoes_finais" not in topics
    assert "garantia" in topics
    assert run_tool(ctx, "get_store_policy", {"topics": ["atendimento_via_whatsapp"]})[1] is True
    result, _ = run_tool(ctx, "get_store_policy", {"topics": ["sobre_a_emporio_da_musica"]})
    assert "get_store_info" in result["note"]  # the manual's contacts are not the source of truth


def test_arguments_from_the_model_are_coerced(ctx):
    assert run_tool(ctx, "check_order", {"order_id": "7", "customer_contact": "leticia.rocha@jmail.com"})[0]["verified"]
    assert run_tool(ctx, "get_product_details", {"product_id": "95"})[0]["product_id"] == 95
    assert run_tool(ctx, "search_products", {"category": "violoes", "limit": None})[1] is False
    assert run_tool(ctx, "simulate_payment", {"items": [{"product_id": 95, "quantity": None}]})[1] is False
    result, is_error = run_tool(ctx, "get_store_policy", {"topics": "garantia"})
    assert not is_error and result["sections"][0]["section"] == "8. Garantia"


def test_unexpected_tool_failures_are_contained_and_logged(ctx, tmp_path, caplog):
    (tmp_path / "blocked").write_text("a file where a directory is expected")
    broken = ToolContext(ctx.data, ctx.policies, ctx.clock, tmp_path / "blocked" / "handoffs.jsonl")
    result, is_error = run_tool(broken, "escalate_to_human", {"reason": "complaint", "summary": "x"})
    assert is_error and "Erro interno" in result["error"]
    assert "escalate_to_human" in caplog.text


def test_bad_arguments_are_reported_not_raised(ctx):
    result, is_error = run_tool(ctx, "search_products", {"colour": "red"})
    assert is_error


def test_escalation_writes_a_ticket(ctx):
    result = escalate_to_human(ctx, reason="complaint", summary="Pedido atrasado", order_id=8)
    lines = ctx.handoff_log.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[-1])["ticket_id"] == result["ticket_id"]
    assert "team_back_at" not in result  # store open on the demo date


def test_order_tickets_record_whether_the_requester_was_verified(ctx):
    verified = escalate_to_human(
        ctx, reason="order_problem", summary="x", order_id=8, customer_contact="anacarol.ferreira@coldmail.com"
    )
    unverified = escalate_to_human(ctx, reason="other", summary="x", order_id="13")
    shared = escalate_to_human(
        ctx, reason="other", summary="x", order_id=10, customer_contact="bruno.martins@jmail.com"
    )
    general = escalate_to_human(ctx, reason="complaint", summary="x")
    tickets = [json.loads(line) for line in ctx.handoff_log.read_text(encoding="utf-8").splitlines()]
    assert [t["requester_verified"] for t in tickets] == [True, False, False, None]
    assert tickets[1]["order_id"] == 13
    assert "note" not in verified and "note" not in general
    assert "NÃO verificado" in unverified["note"] and "NÃO verificado" in shared["note"]


def test_escalation_says_when_the_team_is_back(make_ctx):
    result = escalate_to_human(make_ctx(datetime(2026, 3, 29, 11)), reason="complaint", summary="x")  # Sunday
    assert result["team_back_at"] == "segunda-feira, 30/03/2026 às 09:00"
