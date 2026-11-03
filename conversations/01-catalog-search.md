# 1. Catalog search: violões up to R$ 1.000

Filtered catalog query plus a follow-up recommendation. Out-of-stock and discontinued models must not be offered.

*Model: `claude-opus-5-5` · Simulated store time: quarta-feira, 25/03/2026 10:00*

---

**Cliente:** Oi! Quais opções de violões vocês têm custando até R$1000?

> 🔧 `search_products(category="violoes", max_price=1000, sort="price_asc", limit=15)`  

**Mel:** Oi! Temos 12 violões disponíveis até R$ 1.000,00. Seguem alguns pra você ter uma ideia:

Cordas de nylon:
- Tagima Memphis AC-39 Nylon Natural: R$ 429,90
- Rozini RC-104 Nylon Estudante: R$ 459,90
- Yamaha C40 Nylon Natural: R$ 599,90

Cordas de aço:
- Shelby SN-100 Folk Aço Preto: R$ 549,00
- Yamaha F310 Aço Natural: R$ 699,90
- Shelby SGD-195E Elétrico Aço Sunburst: R$ 799,00

Também tem modelos da Giannini e outros da Tagima e Yamaha nessa faixa, incluindo um violão de 7 cordas. Pra eu te mostrar os mais indicados, me conta: você prefere nylon ou aço? Precisa que seja eletroacústico, pra ligar no amplificador? 🎸

---

**Cliente:** Legal! Sou iniciante e prefiro corda de nylon. Qual você me indica?

> 🔧 `get_product_details(product_id=83)`  
> 🔧 `get_product_details(product_id=85)`  
> 🔧 `get_product_details(product_id=81)`  
> 🔧 `get_product_details(product_id=84)`  
> 🔧 `get_product_details(product_id=82)`  

**Mel:** Boa escolha! Nylon é ótimo pra quem está começando, porque as cordas são mais macias e machucam menos os dedos no início. Separei os modelos de nylon que, pela descrição, são voltados pra iniciantes:

- Tagima Memphis AC-39 Nylon Natural, R$ 429,90: é o mais em conta. Tem corpo leve e confortável pra estudar por bastante tempo, com tampo e fundo em Linden.
- Rozini RC-104 Nylon Estudante, R$ 459,90: é um violão de estudo com tampo em Spruce e fundo e laterais em Sapele, feito com madeiras nacionais.
- Yamaha C40 Nylon Natural, R$ 599,90: tem tampo em Spruce e fundo e laterais em Meranti. A descrição diz que é ideal pra estudantes e iniciantes, com excelente projeção sonora.

Minha sugestão: se quiser gastar o mínimo, vá no Tagima Memphis. Se puder investir um pouco mais, o Yamaha C40 é o mais completo dos três pra iniciantes.

Os outros dois de nylon nessa faixa são pra um nível acima. O Giannini GN-15 (R$ 689,00) é indicado pra estudantes avançados, e o Yamaha C70 (R$ 849,00) é de nível intermediário.

Quer que eu simule o pagamento de algum deles no PIX ou parcelado?

---
