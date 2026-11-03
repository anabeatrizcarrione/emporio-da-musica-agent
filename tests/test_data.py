from emporio.data import Availability, normalize


def test_loads_all_tables(store_data):
    assert len(store_data.categories) == 9
    assert len(store_data.products) == 65
    assert len(store_data.customers) == 50
    assert len(store_data.orders) == 20
    assert sum(len(o.items) for o in store_data.orders.values()) == 22


def test_availability_rules(store_data):
    p = store_data.products
    assert p[81].availability is Availability.IN_STOCK
    assert p[96].availability is Availability.OUT_OF_STOCK  # active, stock 0
    assert p[113].availability is Availability.DISCONTINUED
    assert p[136].availability is Availability.DISCONTINUED  # discontinued even with stock 13
    assert p[130].availability is Availability.COMING_SOON
    assert not p[136].sellable


def test_only_active_promotions_change_the_price(store_data):
    assert store_data.products[90].effective_price == 1967.18  # 18% active
    takamine = store_data.products[95]  # 12% promotion exists but is inactive
    assert takamine.active_promotion is None
    assert takamine.effective_price == 2199.0


def test_descriptions_naming_another_brand_are_flagged(store_data):
    flagged = {p.id for p in store_data.products.values() if not p.description_reliable}
    assert flagged == {135, 137, 139, 140, 142, 144}


def test_quality_report_lists_known_inconsistencies(store_data):
    report = "\n".join(store_data.quality_report())
    assert "Order 3 total" in report and "Order 20 total" in report
    assert "PIX orders 1, 5, 10, 13, 17 total exactly the list price" in report
    assert "Orders 9 (6x of R$ 58.32), 16 (6x of R$ 71.65), 18 (12x of R$ 38.32) are below" in report
    assert "7 Campo Grande orders have delivery estimates of 7-11 business days" in report
    assert "#11 Bruno Carvalho Martins and #43 Bruno Martins" in report
    assert "probably the same person" in report
    assert "Cordas Orquestrais" in report


def test_normalize():
    assert normalize("Violão Aço  Elétrico!") == "violao aco eletrico"
