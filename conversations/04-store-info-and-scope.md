# 4. Store information and out-of-scope products

Address and opening hours from the policy, a request for accessories the store does not sell (§7.1), and an instrument category with no products in the catalog.

*Model: `claude-opus-5-5` · Simulated store time: sábado, 28/03/2026 14:00*

---

**Cliente:** Qual o endereço da loja? Dá pra passar aí hoje?

> 🔧 `get_store_info()`  

**Mel:** Oi! A loja fica na Rua 14 de Maio, 3200, Centro, Campo Grande/MS (CEP 79202-333).

Hoje não vai dar. Aos sábados a gente abre das 09:00 às 13:00, e agora já fechamos. No domingo a loja não abre, então a próxima abertura é na segunda-feira, 30/03/2026, às 09:00.

Nossos horários:
- Segunda a sexta: 09:00 às 18:00
- Sábado: 09:00 às 13:00
- Domingo e feriados: fechado

Se quiser falar com a equipe, o telefone/WhatsApp é (67) 3341-4444 e o e-mail é contato@emporiodamusica.com.br. Se estiver procurando algum instrumento, posso te ajudar por aqui mesmo 🎶

---

**Cliente:** Beleza. Vocês vendem cordas e amplificador também?

**Mel:** Não vendemos, não. A Empório da Música trabalha só com instrumentos musicais, então cordas, amplificadores e outros acessórios (palhetas, cabos, cases, pedais) ficam de fora. Pra esses itens, o melhor é procurar uma loja especializada em acessórios musicais.

Se estiver atrás de um instrumento (violão, guitarra, baixo, teclado, ukulele…), posso te mostrar as opções que temos agora. Quer que eu procure algum?

---

**Cliente:** E flauta transversal, vocês têm?

> 🔧 `search_products(category="instrumentos_de_sopro_madeiras", query="flauta transversal")`  

**Mel:** No momento não temos. A loja está sem instrumentos de sopro no catálogo, então não há flauta transversal disponível agora.

O que temos à venda hoje:
- Violões
- Guitarras
- Baixos
- Ukuleles
- Teclados e pianos
- Baterias e percussão

Se alguma dessas te interessar, posso te mostrar as opções e os preços.

---
