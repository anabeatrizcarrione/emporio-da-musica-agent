"""Domain model and loader for the store's CSV exports.

The dataset is small (~230 rows across six files), so it is loaded once into
typed, in-memory objects. Tools query these objects directly; a production
version would replace this module with a repository backed by the store's
database, keeping the same interface.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path

from emporio import store

CSV_PREFIX = "desafio_tecnico_ai_eng - "

PRODUCT_STATUSES = {"active", "discontinued", "coming_soon"}
ORDER_STATUSES = {"pending", "confirmed", "shipped", "delivered", "cancelled"}

# Used to spot descriptions that talk about a different brand than the product
# name (e.g. "Bateria Acústica Yamaha" described as a "Pearl Export").
KNOWN_BRANDS = {
    "casio", "crafter", "epiphone", "fender", "gibson", "giannini", "gretsch", "ibanez",
    "jackson", "kala", "kalani", "korg", "ludwig", "mapex", "martin", "music man", "nord",
    "ohana", "pearl", "prs", "roland", "rozini", "shelby", "squier", "tagima", "takamine",
    "tama", "taylor", "yamaha",
}


def normalize(text: str) -> str:
    """Lowercase and strip accents/punctuation: 'Violão Aço' -> 'violao aco'."""
    decomposed = unicodedata.normalize("NFKD", text)
    no_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", no_accents.lower()).strip()


def slugify(text: str) -> str:
    return normalize(text).replace(" ", "_")


def digits(text: str) -> str:
    return re.sub(r"\D", "", text)


class Availability(StrEnum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    DISCONTINUED = "discontinued"
    COMING_SOON = "coming_soon"


@dataclass(frozen=True)
class Category:
    id: int
    name: str
    description: str

    @property
    def slug(self) -> str:
        return slugify(self.name)


@dataclass(frozen=True)
class Promotion:
    id: int
    product_id: int
    name: str
    discount_percent: float
    is_active: bool


@dataclass
class Product:
    id: int
    name: str
    category: Category
    price: float
    description: str
    stock: int
    status: str
    specs: dict[str, str]
    promotions: list[Promotion] = field(default_factory=list)

    @property
    def availability(self) -> Availability:
        # A discontinued item is never offered, even with leftover stock (policy §7.3).
        if self.status == "discontinued":
            return Availability.DISCONTINUED
        if self.status == "coming_soon":
            return Availability.COMING_SOON
        return Availability.IN_STOCK if self.stock > 0 else Availability.OUT_OF_STOCK

    @property
    def sellable(self) -> bool:
        return self.availability is Availability.IN_STOCK

    @property
    def active_promotion(self) -> Promotion | None:
        # Promotions are not cumulative (policy §6.2): if several are active, the best one wins.
        active = [p for p in self.promotions if p.is_active]
        return max(active, key=lambda p: p.discount_percent, default=None)

    @property
    def effective_price(self) -> float:
        promo = self.active_promotion
        if promo is None:
            return self.price
        return round(self.price * (1 - promo.discount_percent / 100), 2)

    @property
    def search_key(self) -> str:
        return normalize(self.name)

    @property
    def description_reliable(self) -> bool:
        """False when the description names a brand that is not in the product name."""
        name = f" {normalize(self.name)} "
        description = f" {normalize(self.description)} "
        return not any(f" {b} " in description and f" {b} " not in name for b in KNOWN_BRANDS)


@dataclass(frozen=True)
class Customer:
    id: int
    name: str
    phone: str
    email: str
    city: str

    @property
    def first_name(self) -> str:
        return self.name.split()[0]


@dataclass(frozen=True)
class OrderItem:
    product: Product
    quantity: int


@dataclass
class Order:
    id: int
    customer: Customer
    order_date: date
    status: str
    total: float
    payment_method: str
    tracking_code: str | None
    estimated_delivery: date | None
    notes: str | None
    items: list[OrderItem] = field(default_factory=list)


@dataclass
class StoreData:
    categories: dict[int, Category]
    products: dict[int, Product]
    customers: dict[int, Customer]
    orders: dict[int, Order]

    def category_by_slug(self, slug: str) -> Category | None:
        return next((c for c in self.categories.values() if c.slug == slug), None)

    def quality_report(self) -> list[str]:
        """Inconsistencies found in the raw data and how the agent treats them."""
        issues: list[str] = []
        products = self.products.values()

        for p in products:
            if p.status == "discontinued" and p.stock > 0:
                issues.append(
                    f"Product {p.id} ({p.name}) is discontinued but has stock={p.stock}; treated as not for sale."
                )
            if p.status == "active" and p.stock <= 0:
                issues.append(f"Product {p.id} ({p.name}) is active with zero stock; reported as out of stock.")
            if len([promo for promo in p.promotions if promo.is_active]) > 1:
                issues.append(f"Product {p.id} has several active promotions; only the largest discount applies.")
            if not p.description_reliable:
                issues.append(
                    f"Product {p.id} ({p.name}) has a description naming another brand; "
                    "description is hidden from the agent."
                )

        ordered_ids = {item.product.id for o in self.orders.values() for item in o.items}
        for p in products:
            if p.status == "coming_soon" and p.id in ordered_ids:
                issues.append(
                    f"Product {p.id} ({p.name}) is 'coming_soon' but appears in existing orders; "
                    "order history is still reported."
                )

        pix_at_list_price: list[str] = []
        below_installment_minimum: list[str] = []
        slow_metro_deliveries: list[int] = []
        for o in self.orders.values():
            items_total = round(sum(i.product.price * i.quantity for i in o.items), 2)
            if abs(items_total - o.total) > 0.01:
                issues.append(
                    f"Order {o.id} total R$ {o.total:.2f} differs from current item prices R$ {items_total:.2f}; "
                    "the recorded total is reported as-is."
                )
            elif o.payment_method == "pix":
                pix_at_list_price.append(str(o.id))
            if o.payment_method.startswith("credit_"):
                installments = int(o.payment_method.removeprefix("credit_").removesuffix("x"))
                try:
                    if o.total / installments < store.installment_minimum(installments):
                        below_installment_minimum.append(f"{o.id} ({installments}x of R$ {o.total / installments:.2f})")
                except ValueError:
                    issues.append(f"Order {o.id} has an invalid installment count: {o.payment_method}.")
            if o.estimated_delivery and o.customer.city == store.METRO_CITY:
                days = store.business_days_between(o.order_date, o.estimated_delivery)
                if days > store.METRO_MAX_BUSINESS_DAYS:
                    slow_metro_deliveries.append(days)
        if pix_at_list_price:
            issues.append(
                f"PIX orders {', '.join(pix_at_list_price)} total exactly the list price, "
                "without the 5% PIX discount (§3); totals are reported as the recorded order total, "
                "not as the amount charged."
            )
        if below_installment_minimum:
            issues.append(
                f"Orders {', '.join(below_installment_minimum)} are below the installment minimums of policy §3.1; "
                "past orders are reported as recorded."
            )
        if slow_metro_deliveries:
            issues.append(
                f"{len(slow_metro_deliveries)} {store.METRO_CITY} orders have delivery estimates of "
                f"{min(slow_metro_deliveries)}-{max(slow_metro_deliveries)} business days, while policy §5.1 promises "
                f"1-{store.METRO_MAX_BUSINESS_DAYS} in the metro area; the agent reports each order's own estimate."
            )

        used_categories = {p.category.id for p in products}
        for c in self.categories.values():
            if c.id not in used_categories:
                issues.append(f"Category '{c.name}' has no products in the catalog.")

        by_email: dict[str, list[Customer]] = {}
        for c in self.customers.values():
            by_email.setdefault(c.email.lower(), []).append(c)
        for email, group in by_email.items():
            if len(group) > 1:
                who = " and ".join(f"#{c.id} {c.name}" for c in group)
                same_person = len({c.first_name for c in group}) == 1 and len({c.city for c in group}) == 1
                note = "probably the same person with two records" if same_person else "different people"
                issues.append(
                    f"Customers {who} share the e-mail {email} ({note}); "
                    "order lookup always requires the order number too."
                )
        return issues


def _read_csv(data_dir: Path, table: str) -> list[dict[str, str]]:
    path = data_dir / f"{CSV_PREFIX}{table}.csv"
    with path.open(encoding="utf-8", newline="") as fh:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(fh)]


def _optional(value: str) -> str | None:
    return value or None


def load_store_data(data_dir: Path) -> StoreData:
    categories = {
        int(r["category_id"]): Category(int(r["category_id"]), r["name"], r["description"])
        for r in _read_csv(data_dir, "categories")
    }

    promotions_by_product: dict[int, list[Promotion]] = {}
    for r in _read_csv(data_dir, "promotions"):
        promo = Promotion(
            id=int(r["promotion_id"]),
            product_id=int(r["product_id"]),
            name=r["description"],
            discount_percent=float(r["discount_percent"]),
            is_active=r["is_active"] == "1",
        )
        promotions_by_product.setdefault(promo.product_id, []).append(promo)

    products: dict[int, Product] = {}
    for r in _read_csv(data_dir, "products"):
        if r["status"] not in PRODUCT_STATUSES:
            raise ValueError(f"Unknown product status {r['status']!r} for product {r['product_id']}")
        product_id = int(r["product_id"])
        products[product_id] = Product(
            id=product_id,
            name=r["name"],
            category=categories[int(r["category_id"])],
            price=float(r["price_brl"]),
            description=r["description"],
            stock=int(r["stock_quantity"]),
            status=r["status"],
            specs={k: str(v) for k, v in json.loads(r["specs"]).items()},
            promotions=promotions_by_product.get(product_id, []),
        )

    customers = {
        int(r["customer_id"]): Customer(int(r["customer_id"]), r["name"], r["phone"], r["email"], r["city"])
        for r in _read_csv(data_dir, "customers")
    }

    orders: dict[int, Order] = {}
    for r in _read_csv(data_dir, "orders"):
        if r["status"] not in ORDER_STATUSES:
            raise ValueError(f"Unknown order status {r['status']!r} for order {r['order_id']}")
        delivery = _optional(r["estimated_delivery"])
        orders[int(r["order_id"])] = Order(
            id=int(r["order_id"]),
            customer=customers[int(r["customer_id"])],
            order_date=date.fromisoformat(r["order_date"]),
            status=r["status"],
            total=float(r["total_brl"]),
            payment_method=r["payment_method"],
            tracking_code=_optional(r["tracking_code"]),
            estimated_delivery=date.fromisoformat(delivery) if delivery else None,
            notes=_optional(r["notes"]),
        )
    for r in _read_csv(data_dir, "order_items"):
        orders[int(r["order_id"])].items.append(
            OrderItem(product=products[int(r["product_id"])], quantity=int(r["quantity"]))
        )

    return StoreData(categories=categories, products=products, customers=customers, orders=orders)
