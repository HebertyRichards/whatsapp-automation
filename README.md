# WhatsApp Order Bot

A menu-driven ordering bot for WhatsApp, built with FastAPI on top of the
[Evolution API](https://docs.evolutionfoundation.com.br/evolution-api). The example business is a
pizzeria: customers answer numbered menus, and the bot assembles the order, prices it and hands it to
the staff.

Nothing about the business is hard-coded. Menu, prices, opening hours, delivery fee and store name are
read from PostgreSQL on every message.

## How it works

```
Customer ── WhatsApp ──> Evolution API ── POST /webhook/evolution ──> bot ──> PostgreSQL
Customer <── WhatsApp ── Evolution API <── POST /message/sendText ─── bot
```

1. Evolution posts every incoming message to the bot's webhook.
2. The bot acknowledges at once and processes the message in the background, one customer at a time.
3. The conversation step and the cart are loaded from the database, the answer is applied, and the
   replies are sent back through Evolution with a "typing..." delay.

### Conversation flow

```
Welcome (typing 4s)
└─ 1 Order | 2 See the menu | 3 Talk to an attendant

Order
├─ Pizza category            (from pizza_categories, e.g. Salgada / Doce)
├─ Size                      (each size, plus "meio a meio" when the size allows it)
├─ Flavor                    (two flavors for half-and-half)
├─ Cart                      1 another pizza | 2 drink | 3 checkout | 4 remove an item
├─ Name                      (free text)
├─ Pickup or delivery        (delivery asks for the address, free text)
├─ Payment                   cash (asks about change) | card | Pix
└─ Summary                   1 confirm | 2 cancel
```

Commands available along the way:

| Input | Effect |
|---|---|
| `0` or the word `atendente` | Hands the chat to a human and alerts the staff |
| `V` | Goes back one step |
| `M` / `A` | Next / previous page of a long list |
| `menu` | Gives the chat back to the bot after a handoff |

Payment is not charged by the bot: it records the method and the store collects on delivery or pickup.

## Project layout

```
app/
  main.py          app assembly, lifespan, /health and /ready
  routes/          thin HTTP layer (the webhook)
  services/        business logic
    inbound_service.py        filters events, de-duplicates, queues per customer
    conversation_service.py   the ordering flow (state machine)
    order_service.py          pricing and order creation
    evolution_service.py      HTTP client for the Evolution API
  repositories/    SQLAlchemy queries only
  schemas/         Pydantic models (webhook payload, cart draft, quotes)
  models/          SQLAlchemy tables
  errors/          AppException, error codes, handlers
  utils/           circuit breaker, rate limit, opening hours, money, message copy
  config/          settings, database engine, Redis client, logging
alembic/           migrations
sql/               first-time store setup (example data)
```

Request path: **route → service → repository → database**. All customer-facing text lives in
`app/utils/messages.py`.

## Requirements

- Python 3.13+
- PostgreSQL 14+
- A running Evolution API v2 with a connected WhatsApp instance
- Redis (optional)

## Environment variables

Copy `.env.example` to `.env` for local runs; on a host such as Railway, set them on the service.

| Variable | Required | What it is | Where to get it |
|---|---|---|---|
| `DATABASE_URL` | yes | PostgreSQL connection string. `postgres://` and `postgresql://` are both accepted. | **Railway:** add a PostgreSQL service and reference `${{Postgres.DATABASE_URL}}` (use `DATABASE_PUBLIC_URL` from your own machine). **Neon:** dashboard → *Connect*. **Supabase:** *Connect* → *Session pooler* or *Direct connection*. |
| `EVOLUTION_API_URL` | yes | Base URL of the Evolution API, no trailing slash. | The public domain of your Evolution service (the same value as its `SERVER_URL`). |
| `EVOLUTION_API_KEY` | yes | Key sent in the `apikey` header. | The `AUTHENTICATION_API_KEY` variable of the Evolution service. |
| `EVOLUTION_INSTANCE` | yes | Name of the WhatsApp instance the bot answers for. | The `instanceName` you choose when creating the instance (see below). |
| `WEBHOOK_SECRET` | yes | Shared secret, 32+ characters, that Evolution must send in the `X-Webhook-Secret` header. | Generate it: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `REDIS_URL` | no | Redis connection string. | **Railway:** add a Redis service and reference `${{Redis.REDIS_URL}}`. |
| `REDIS_ENABLED` | no | `false` turns Redis off. Default `true`. | — |
| `APP_ENV` | no | `production` hides validation details and switches logs to JSON. Default `development`. | — |
| `LOG_LEVEL` | no | Default `INFO`. | — |
| `LOG_JSON` | no | Forces JSON logs outside production. Default `false`. | — |

Notes:

- Supabase's *Transaction pooler* (port 6543) does not support prepared statements, which this driver
  setup uses. Pick the session pooler or the direct connection.
- `sslmode` in the URL is honored (`require`, `verify-full`, `disable`...).
- Give the bot its own database. Evolution manages its own schema and the two should not share one.

## Database setup

### 1. Create the tables

```bash
make upgrade          # alembic upgrade head
```

### 2. Load the store data

`sql/store_setup.example.sql` creates the store settings, the opening hours and a **sample menu**.
Replace the sample rows with the real menu and run the file once (Railway *Data* tab, Supabase or Neon
SQL editor, or `psql`). Until `store_settings` has its row, the bot stays silent and `/ready` answers 503.

### 3. Day-to-day changes

There is no admin panel; the menu is edited with SQL.

```sql
-- New flavor, priced per size (a flavor is only offered in the sizes it has a price for)
INSERT INTO pizza_flavors (category_id, name, description, sort_order)
VALUES ((SELECT id FROM pizza_categories WHERE name = 'Salgada'), 'Quatro Queijos', 'Mussarela, provolone, parmesão e catupiry', 5);

INSERT INTO pizza_prices (flavor_id, size_id, price)
SELECT f.id, s.id, v.price
FROM (VALUES ('Broto', 36.00), ('Inteira', 60.00)) AS v(size, price)
JOIN pizza_sizes s ON s.name = v.size
JOIN pizza_flavors f ON f.name = 'Quatro Queijos';

-- Change a price
UPDATE pizza_prices SET price = 50.00
WHERE flavor_id = (SELECT id FROM pizza_flavors WHERE name = 'Calabresa')
  AND size_id = (SELECT id FROM pizza_sizes WHERE name = 'Inteira');

-- Take an item off the menu. Prefer this over DELETE: past orders keep their reference.
UPDATE pizza_flavors SET is_active = false WHERE name = 'Portuguesa';
UPDATE drinks SET is_active = false WHERE name = 'Suco de Laranja 1L';

-- Store settings
UPDATE store_settings SET delivery_fee = 6.00;
UPDATE store_settings SET half_half_pricing = 'average';   -- or 'highest'

-- Opening hours: 1 = Monday ... 7 = Sunday. Days without a row are closed.
-- closes_at at or before opens_at means the shift ends on the next day.
UPDATE opening_hours SET opens_at = '17:00' WHERE weekday = 6;
```

`sort_order` controls the position of an item in its list, and therefore the number customers type.

## Evolution API setup

The examples use bash (Git Bash on Windows). The Evolution Manager at `$EVOLUTION_API_URL/manager`
covers steps 1 and 2 through a UI.

```bash
export EVOLUTION_API_URL=https://your-evolution-api.up.railway.app
export EVOLUTION_API_KEY=...
export INSTANCE=pizzaria
```

**1. Create the instance**

```bash
curl -X POST "$EVOLUTION_API_URL/instance/create" \
  -H "apikey: $EVOLUTION_API_KEY" -H "Content-Type: application/json" \
  -d '{"instanceName": "'$INSTANCE'", "integration": "WHATSAPP-BAILEYS", "qrcode": true}'
```

**2. Connect the phone**

```bash
curl "$EVOLUTION_API_URL/instance/connect/$INSTANCE" -H "apikey: $EVOLUTION_API_KEY"
```

The response carries the QR code as a base64 image. Scan it with WhatsApp → *Linked devices*.

**3. Point the webhook at the bot**

```bash
curl -X POST "$EVOLUTION_API_URL/webhook/set/$INSTANCE" \
  -H "apikey: $EVOLUTION_API_KEY" -H "Content-Type: application/json" \
  -d '{
    "webhook": {
      "enabled": true,
      "url": "https://your-bot.up.railway.app/webhook/evolution",
      "headers": {"X-Webhook-Secret": "<WEBHOOK_SECRET>"},
      "byEvents": false,
      "base64": false,
      "events": ["MESSAGES_UPSERT"]
    }
  }'
```

Use the per-instance webhook, as above. Evolution's global webhook (`WEBHOOK_GLOBAL_*`) cannot send
custom headers, so the bot would reject it.

**4. Choose who receives the orders (optional)**

Orders and attendant requests go to the WhatsApp JID stored in `store_settings.staff_jid`: a group
(`...@g.us`) or a number (`5511999999999@s.whatsapp.net`). For a group, add the bot's number to it and
look up its id:

```bash
curl "$EVOLUTION_API_URL/group/fetchAllGroups/$INSTANCE?getParticipants=false" -H "apikey: $EVOLUTION_API_KEY"
```

```sql
UPDATE store_settings SET staff_jid = '120363000000000000@g.us';
```

With `staff_jid` empty, orders are only stored in the `orders` table.

## Running locally

```bash
make install     # creates ./venv and installs dependencies
cp .env.example .env   # then fill it in
make upgrade
make dev         # http://localhost:8000, interactive docs at /docs
```

Evolution has to reach your machine to deliver webhooks, so expose port 8000 with a tunnel
(`cloudflared`, `ngrok`) and use that URL in step 3 above.

## Deploying on Railway

1. Deploy the Evolution API (the [template](https://railway.com/deploy/evolution-api-4) brings its
   own PostgreSQL and Redis). Mount a volume at `/evolution/instances`, or the WhatsApp session is
   lost on every redeploy.
2. Add a PostgreSQL service for the bot (and Redis, if wanted).
3. Create a service from this repository. Railway builds the `Dockerfile`.
4. Set the environment variables from the table above, plus `APP_ENV=production`.
5. In the service settings set:
   - **Pre-deploy command:** `alembic upgrade head`
   - **Healthcheck path:** `/health`
6. Generate a public domain for the service and use it in the webhook URL.
7. Run `sql/store_setup.example.sql` (edited) against the bot's database.

Keep the service at **one replica**. Per-customer locks and the circuit breakers live in process
memory, which is also why the container starts a single worker.

## Behavior reference

| Rule | Value | Where to change |
|---|---|---|
| Typing delay | 4s welcome, 2s replies, 1s page turns | `conversation_service.py` |
| Session timeout | 30 minutes of silence | `conversation_service.py` |
| Pagination | lists above 30 entries, 15 per page | `conversation_service.py` |
| Rate limit | 30 messages per minute per customer | `utils/rate_limit.py` |
| Opening hours | checked when a session starts | `opening_hours` table |
| Delivery fee | flat | `store_settings.delivery_fee` |
| Half-and-half price | pricier flavor or average of both | `store_settings.half_half_pricing` |

Details worth knowing:

- **Numbering is continuous across pages.** Page 2 of the flavors starts at 16, and a number from any
  page selects that flavor.
- **Opening hours only gate new sessions.** An order already in progress can be finished after
  closing time.
- **Totals are recomputed from the menu** at every step. The cart stores ids, never prices; the
  placed order stores a snapshot.
- **An order is only stored if the staff alert was delivered.** If Evolution fails at that moment the
  order is rolled back and the customer is asked to confirm again.
- **Two invalid answers in a row** add a hint about talking to an attendant.
- **Messages older than 10 minutes are ignored**, so a backlog replayed after a reconnect does not
  trigger a burst of late replies.

### Failure handling

- **Redis** is optional and fails open. Without it there is no webhook de-duplication and no rate
  limit; everything else works. A circuit breaker stops the bot from hammering a Redis that is down,
  and a supervisor reconnects on its own.
- **Evolution API** calls go through a circuit breaker too: after 5 consecutive failures the bot stops
  calling it for 30 seconds.
- `/health` is a liveness probe. `/ready` checks the database and that the store is configured.

## Operational notes

- The Baileys connection is not an official WhatsApp API and the number can be banned. The bot only
  answers customers who wrote first, which is the low-risk pattern; do not use it for bulk messaging.
- Use a dedicated number, registered as WhatsApp Business with the store's name and picture.
- Pin the Evolution image to a version instead of `latest` once the setup works.

## Not included yet

- Online payment (Pix QR code with automatic confirmation)
- Admin panel for the menu and orders
- Delivery fee by neighborhood
- Several stores in one deployment

## Commands

| Command | What it does |
|---|---|
| `make install` | Create the venv if needed and install dependencies |
| `make dev` | Run the server with reload |
| `make lint` | `ruff check` |
| `make typecheck` | `mypy` in strict mode |
| `make migrate m="msg"` | Autogenerate a migration from the models (review it before applying) |
| `make upgrade` / `make downgrade` | Apply / revert migrations |
| `make current` / `make history` | Applied revision / history |

Dependencies are declared in `requirements.in` and locked in `requirements.txt`:

```bash
uv pip compile requirements.in -o requirements.txt --universal --python-version 3.13
```
