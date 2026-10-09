-- First-time store setup. The bot reads everything it shows from these tables.
-- Replace the sample menu below with the real one, then run this file once
-- (Railway "Data" tab, Supabase SQL editor, Neon SQL editor or psql).

BEGIN;

-- Single row. half_half_pricing: 'highest' charges the pricier flavor, 'average' the mean of both.
-- staff_jid: WhatsApp JID (group or number) that receives orders and attendant requests.
INSERT INTO store_settings (id, name, timezone, delivery_fee, half_half_pricing, staff_jid)
VALUES (1, 'Pizzaria Exemplo', 'America/Sao_Paulo', 5.00, 'highest', NULL);

-- weekday: 1 = Monday ... 7 = Sunday. Days without a row are closed.
-- closes_at at or before opens_at means the shift ends on the next day.
INSERT INTO opening_hours (weekday, opens_at, closes_at) VALUES
    (2, '18:00', '04:00'),
    (3, '18:00', '04:00'),
    (4, '18:00', '04:00'),
    (5, '18:00', '04:00'),
    (6, '18:00', '04:00'),
    (7, '18:00', '04:00');

INSERT INTO pizza_categories (name, sort_order) VALUES
    ('Salgada', 1),
    ('Doce', 2);

-- allows_half: whether the size can be ordered half-and-half.
INSERT INTO pizza_sizes (name, allows_half, sort_order) VALUES
    ('Broto', true, 1),
    ('Inteira', true, 2);

INSERT INTO pizza_flavors (category_id, name, description, sort_order)
SELECT c.id, v.name, v.description, v.sort_order
FROM (VALUES
    ('Salgada', 'Mussarela', 'Mussarela, tomate e orégano', 1),
    ('Salgada', 'Calabresa', 'Calabresa, cebola e mussarela', 2),
    ('Salgada', 'Frango com Catupiry', 'Frango desfiado e catupiry', 3),
    ('Salgada', 'Portuguesa', 'Presunto, ovo, cebola, ervilha e mussarela', 4),
    ('Doce', 'Chocolate', 'Chocolate ao leite', 1),
    ('Doce', 'Romeu e Julieta', 'Goiabada e mussarela', 2)
) AS v(category, name, description, sort_order)
JOIN pizza_categories c ON c.name = v.category;

-- A flavor is only offered in the sizes it has a price for.
INSERT INTO pizza_prices (flavor_id, size_id, price)
SELECT f.id, s.id, v.price
FROM (VALUES
    ('Mussarela', 'Broto', 28.00),           ('Mussarela', 'Inteira', 45.00),
    ('Calabresa', 'Broto', 30.00),           ('Calabresa', 'Inteira', 48.00),
    ('Frango com Catupiry', 'Broto', 34.00), ('Frango com Catupiry', 'Inteira', 55.00),
    ('Portuguesa', 'Broto', 35.00),          ('Portuguesa', 'Inteira', 58.00),
    ('Chocolate', 'Broto', 32.00),           ('Chocolate', 'Inteira', 52.00),
    ('Romeu e Julieta', 'Broto', 30.00),     ('Romeu e Julieta', 'Inteira', 50.00)
) AS v(flavor, size, price)
JOIN pizza_flavors f ON f.name = v.flavor
JOIN pizza_sizes s ON s.name = v.size;

INSERT INTO drinks (name, price, sort_order) VALUES
    ('Coca-Cola 2L', 14.00, 1),
    ('Guaraná Antarctica 2L', 12.00, 2),
    ('Dolly Guaraná 2L', 8.00, 3),
    ('Suco de Laranja 1L', 12.00, 4);

COMMIT;
