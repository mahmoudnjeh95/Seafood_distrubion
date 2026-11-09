# WhatsApp assistant: design

_2026-11-09 · owner request · status: approved by the owner 2026-11-09 ("start the plan implementation")_

## 1. Intent

The owner wants to run the Frutti app from WhatsApp, in Tunisian, by text **and** voice notes:
"chnowa 3andi f frigo?", "9addech ysalni Mohamed?", "7a4arli fatoura l Mohamed". In the end the
assistant should do anything the app can do. Staff (manager, accountant, drivers) use it too, from
their own phones, each limited to what their role allows in the app.

Why: in the market, on the port, and in the truck, typing into a desktop screen is slow. A WhatsApp
message or voice note is how people here already work.

## 2. Goals, non-goals, anti-goals

**Goals**
- Answer questions about the app's data in Tunisian (Darija, Arabizi, Arabic script, French mixed in).
- Prepare and record business actions (quotes, BL, invoices, payments, expenses, …) after the user
  confirms.
- Understand voice notes as well as text.
- One phone = one user. The assistant does exactly what that user's role allows in the app, no more.

**Non-goals (first version)**
- Not every module on day one. The first version covers the most used tasks (§6). More tools are
  added in later tasks from what people actually ask.
- No messages the bot starts by itself (alerts, reminders). That stays in Phase 8 "SMS / WhatsApp
  notifications" and can reuse this channel later.
- No customers or suppliers talking to the bot. Only the company's own users.
- No voice replies. The bot answers in text, and sends PDFs when asked.

**Anti-goals (a failure even if it "works")**
- The bot saves something the user did not confirm, or saves something other than what it showed.
- A user gets data or an action their role would get a 403 for in the app.
- An unknown number gets any business data at all, even a customer name.
- The bot guesses between two customers or products instead of asking.

## 3. Constraints

- **Meta WhatsApp Business Cloud API, direct (owner's choice, 2026-11-09).** The bot needs its own
  number that is not used in the WhatsApp app. Meta verifies the business once. Free-form replies are
  allowed only within 24 h of the user's last message, which is fine because users always write first.
- **Cost (estimated with the owner, 2026-11-09).** At ~3 000 messages a month, ~180 DT/month: Meta
  ~$8 (first 1 000 service messages per month free since 2026-10-01, then ~$0.004 each, Rest of Africa
  rate to confirm in the Meta account), AI ~$45–50, speech-to-text ~$2. The AI is the main cost.
- **The repo's hard rules hold** (CLAUDE.md): writes only through services in a transaction, permissions
  on the server, issued documents immutable, Decimal money, organization on every business table.
- **Permissions live in the API views today** (`apps/core/permissions.py` classes on each view, plus
  per-view filtering such as a driver seeing only his truck). Services do not check roles themselves.
- **Shared VPS.** The webhook runs in the existing `frutti-staging` stack; nothing else on the server is
  touched (runbook).
- **Personal data leaves the server.** Message text, voice audio and the data in answers go to Anthropic
  (Claude) and to the speech-to-text provider. Tunisian law 2004-63 on personal data applies; see §9.

## 4. Approaches considered

| | Approach | Trade-off | Verdict |
|---|---|---|---|
| A | Meta Cloud API, directly to our server | Business verification paperwork; cheapest stable option (~180 DT/month) | **Chosen by the owner** |
| B | Same API through Twilio or 360dialog | Easier onboarding; +90 to +150 DT/month; one more company in the chain | Fallback only if Meta's verification gets stuck |
| C | Unofficial library on a normal WhatsApp account | Only ~30 DT/month cheaper; against WhatsApp's rules, number can be banned, breaks often | Rejected |

How the bot reaches the app's rules was also weighed (my call):

| | How tools act | Trade-off | Verdict |
|---|---|---|---|
| 1 | **Tools call the existing API endpoints in-process, authenticated as the user** | Same permission classes, serializers, validation and driver scoping as the screens; tools are thin | **Chosen** |
| 2 | Tools call `services.py` / `selectors.py` directly | Faster, but every role check and filter must be re-written for the bot and will drift from the app | Rejected |

## 5. How it works

```
WhatsApp ─▶ Meta ─▶ POST /api/v1/whatsapp/webhook (signature checked, 200 at once)
                         │
                         ▼ Celery task (one at a time per phone)
            find user by phone ─ unknown → one fixed refusal, nothing else
                         │
            voice note? → download from Meta → speech-to-text
                         │
            Claude with tools (the user's role decides which tools it is given)
                │                         │
         read tool → API GET as user   write tool → stored "pending action", summary shown
                │                         │
                ▼                         ▼  user replies "ey" / button "Confirmer"
            answer text            API POST/PATCH as user, exactly the stored payload
                         │
                         ▼
             reply via Meta (text, or a PDF document)
```

**Decided with the owner**
- Roles are the app's roles with the same rights. **Using the bot is itself a permission of the roles
  matrix** (owner, 2026-11-09): a user whose role lacks "Utiliser l'assistant WhatsApp" gets the same
  refusal as an unknown number. The roles matrix is being built in parallel (branch `user-roles-matrix`);
  the bot's permission key and its checks follow that design, and the role-based tool filtering uses the
  matrix's permissions, not the four fixed roles.
- Each user's WhatsApp number is entered on their account, by the owner or manager, in the users screen.
- A number linked to no active user gets one polite fixed refusal; no data, no AI call.
- Anything that changes data is shown as a summary first and saved only after the user confirms.
- When unsure (two customers called Mohamed, an unknown product, a missing quantity) the bot asks.
- Everything done through the bot is in the audit log under that user, marked "via WhatsApp".
- Text and voice notes, both.

**My calls (the owner can change them)**
- **Tools act through the API as the user** (approach 1 above). The tool list given to Claude is also
  filtered by role, so it does not even try what the role cannot do, but the API check is the real one.
- **Confirmation is enforced by code, not by the model.** A write tool never writes; it stores a
  pending action (tool, exact payload, summary, user, expiry 15 min) and the bot shows the summary with
  WhatsApp buttons "Confirmer" / "Annuler" (typed "ey", "ok", "n3am" also confirm). Only a confirmation
  from the same phone, for the latest pending action, runs it, with that stored payload. A new request
  replaces the pending one.
- **Drafts first.** Invoices, BL and quotes are created as drafts by default. Issuing an invoice (which
  makes it immutable and takes a number) is a separate action with its own confirmation, and its summary
  says plainly that it cannot be changed afterwards.
- **Model: Claude Sonnet 5.5** for the conversation and tools, because that is what the owner's cost
  estimate used. Claude Haiku 5.5 (about 20 times cheaper) is tried on the same test messages (§8)
  and used only if it gets the same answers.
- **Speech-to-text: chosen by a test**, not upfront: 10 to 20 real Tunisian voice notes from the owner
  and drivers, run through two or three providers (OpenAI transcription models, ElevenLabs Scribe, …).
  The best on Tunisian wins. Claude does not take audio directly.
- **Language of replies:** the bot answers in the user's style: Tunisian in Latin letters (Arabizi)
  if they wrote that, Arabic script if they wrote that, French if they wrote French. Amounts always as
  "1 234,500 DT", weights in kg with 3 decimals, as in the app.
- **Conversation memory:** the last 20 messages or 24 hours per phone, whichever is shorter, so
  "w zid 2 kg" refers to the previous order. Stored in the database, deleted after 90 days.
- **Safety limits:** at most 60 messages per user per hour and a monthly AI budget in the settings;
  over it, the bot says so and the owner gets a notification. An on/off switch for the whole assistant
  and per user.
- **Data from the database is data, not instructions.** A customer named "ignore your rules" changes
  nothing: tool results go back to the model as data, and the writes it can make are still only the
  role's tools with confirmation.
- **New Django app `assistant`** (models: phone link on the membership, conversation messages,
  pending actions, usage log with tokens and cost), its own import-linter contract: it may call other
  apps only through the API layer.

## 6. First version: which tools

Read (answered at once, filtered by role as the matching screen is):
- Stock: cold room and trucks, by product, lots and expiry dates.
- Customers: balance, unpaid invoices, last purchases. Suppliers: what we owe them.
- Sales of the day / week / month, by product, customer or truck.
- A document by number (invoice, BL, quote) and its PDF sent in the chat.
- For a driver: his truck stock, his deliveries today, his day's cash.

Write (always summary + confirmation):
- Quote, BL and invoice drafts for a customer; issue an invoice (separate confirmation).
- Record a customer payment.
- Record an expense (amount, category, note; photo of the receipt if sent with the message).
- For a driver: the same sales and cash actions his phone app allows.

Later tasks add more (purchases, transfers, closings, reports, partner shares…) from what users ask.
The usage log shows which requests the bot could not handle.

## 7. Setup the owner does (not code)

1. A new SIM with a number never used in the WhatsApp app (or deleted from it).
2. A Meta Business account with the company papers, verified; the number added to the WhatsApp
   Business Platform; a payment card on file (needed after the 1 000 free messages a month).
3. Anthropic API key and speech-to-text API key, each with a monthly spending limit.
4. Each user's WhatsApp number on their account.

## 8. How we check it works

- A test set of 50+ real messages (text and voice) written with the owner, with the expected tool call
  or answer. It runs on demand, not in CI (it costs money); used to compare models and providers and
  before changing the prompt.
- Automated tests (pytest, no real AI): webhook signature, unknown number refused, a driver's tool list
  excludes office tools, a forbidden tool call gets the API's 403, a write never happens without the
  stored confirmation, an expired or replaced pending action cannot be confirmed, the confirmed write
  uses the stored payload.
- On staging: the owner and one driver use it for a week before go-live.

## 9. Open points for the owner

- **Personal data (law 2004-63, INPDP):** customer names and amounts go to Anthropic and the speech
  provider (abroad). The accountant or lawyer should say whether a declaration to INPDP or a clause in
  staff contracts is needed. Building can start; go-live waits for the answer.
- **The Meta account:** in whose name (the company) and who handles verification.

## 9b. Several companies (owner, 2026-11-09, D-308)

The app is sold to several companies. **One bot number for all of them**, run by the seller: the sender's phone
gives the user, their company and their role. Per company: on/off, monthly budget, usage (to bill it). The prompt
and the refusal name no company. A person in two companies with one phone is asked which one. A company's own
number is a later option (needs the seller to be a verified Meta Tech Provider). Step by step:
`docs/guides/assistant-whatsapp.md`.

## 10. Left to the builder

- Task split and phase number (proposal: Phase 12 "Assistant WhatsApp": T01 webhook, phone link and
  read tools by text; T02 write tools with confirmation; T03 voice notes; T04 PDFs and receipt photos;
  T05 settings screen, budget and usage).
- Exact prompt wording, tool schemas (derived from the OpenAPI schema of each endpoint), table design,
  retry handling of Meta and Anthropic errors, how the in-process API call is done (DRF request with the
  user forced, or an internal client).
- Decision numbers (D-…) and the entries in `docs/DECISIONS.md`.
