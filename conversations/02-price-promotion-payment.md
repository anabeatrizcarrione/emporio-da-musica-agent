# 2. Price check, expired promotion and payment options

'Quanto custa o Takamine GD20?' The product had a promotion that is no longer active (policy §7.3), and PIX/installment values come from the payment tool (policy §3).

*Model: `claude-opus-5-5` · Simulated store time: quarta-feira, 25/03/2026 10:00*

---

**Cliente:** Quanto custa o Takamine GD20?

> 🔧 `get_product_details(name="Takamine GD20")`  

**Mel:** O **Takamine GD20 Dreadnought Natural** custa **R$ 2.199,00** e está disponível. 🎸

Detalhes do modelo:
- Tampo de cedro sólido
- Fundo e laterais de sapele
- Braço de mogno
- Cordas de aço, escala de 650 mm
- Acústico, sem captação
- Cor natural

Segundo a descrição, é um violão muito bom para fingerstyle, com timbre quente e definido.

Quer que eu veja o valor no PIX ou as opções de parcelamento?

---

**Cliente:** Vi que ele tava numa oferta especial, ainda tá valendo?

**Mel:** Infelizmente não. A Oferta Especial de 12% para o Takamine GD20 já terminou. Hoje ele está por **R$ 2.199,00**.

Se você pagar no PIX, a loja tem desconto de 5%. Quer que eu calcule o valor no PIX ou veja as opções de parcelamento?

---

**Cliente:** Entendi. E se eu pagar no PIX, fica quanto? Dá pra parcelar em 12x no cartão?

> 🔧 `simulate_payment(items=[{"product_id": 95}])`  

**Mel:** No PIX, com 5% de desconto, o Takamine GD20 sai por **R$ 2.089,05**.

E sim, dá pra parcelar em até **12x de R$ 183,25 sem juros** no cartão de crédito, o que dá R$ 2.199,00 no total.

Outras formas de pagamento:
- Débito: R$ 2.199,00
- Boleto: R$ 2.199,00 (o pagamento compensa em até 3 dias úteis)

Precisa de mais alguma coisa?

---
