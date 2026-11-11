# Phase 12 · Assistant WhatsApp (D-307)

_Owner request of 2026-11-09: "a bot in my WhatsApp that talks Tunisian and does what I need in the application"._
Design (approved by the owner 2026-11-09): `docs/superpowers/specs/2026-11-09-whatsapp-assistant-design.md`.
Plan: `docs/superpowers/plans/2026-11-09-whatsapp-assistant.md`. Step by step for the seller, the client
companies and the users: `docs/guides/assistant-whatsapp.md`.

Users message the company's WhatsApp Business number, by text or voice, in Tunisian, Arabic or French. The
assistant answers from the app's data and, after a confirmation, records things. Each phone is one user; the bot
can do only what that user's role allows in the app. Using the bot is itself a permission of the roles matrix
(section `assistant`, built with the roles matrix on branch `user-roles-matrix`).

Choices made with the owner: Meta's official WhatsApp Cloud API, connected directly (no Twilio / 360dialog);
about 180 DT a month at ~3 000 messages (AI ~150 DT, Meta ~25 DT, voice ~6 DT).

## Owner (outside the code)

- [ ] Meta developer app with WhatsApp, under a business portfolio in the owner's name. No company exists yet
      (owner, 2026-11-09): unverified is enough (250 new contacts a day). Start on Meta's free test number (up to 5
      registered phones).
- [ ] Later: a SIM with a number not used in the WhatsApp app, replacing the test number; a payment card if the
      replies pass 1 000 a month (Meta bills service messages beyond that since 2026-10-01).
- [ ] When a company exists: Meta business verification (RNE extract, matricule fiscal, a document with the address).
- [ ] Anthropic API key with a monthly spending limit.
- [ ] For the Tunisian voice in every browser (D-314): an Azure AI Speech resource (portal.azure.com › Speech, free
      tier F0: 500 000 characters a month), its key and region in the server `.env`.
- [ ] Accountant or lawyer: does sending customer names and amounts to Anthropic (abroad) need an INPDP declaration
      (law 2004-63)? Go-live waits for the answer; building does not.

## Tasks

- [x] **P12-T01 Webhook, phone link, answers by text (reads only).** App `apps.assistant`: `WhatsAppLink` (one phone
      per membership, set in the Django admin until T05), `AssistantMessage` (conversation memory and token usage);
      webhook `GET/POST /api/v1/whatsapp/webhook` (Meta's verify token; `X-Hub-Signature-256` checked; a message
      delivered twice is handled once); Celery task: unknown number → refusal (once a day), role without the
      permission → refusal, switched off, 60 messages an hour, voice → "text only for now"; Claude Sonnet 5.5
      with read tools that call the app's own endpoints in-process **as the user** (stock, customers and what they
      owe, receivables, sales, the driver's truck and day); a failure gets an apology. Until the roles matrix
      merges, only the owner may use the bot.
- [ ] **P12-T02 Write tools with confirmation.** Pending action (exact payload, summary, 15 min); buttons
      Confirmer / Annuler; only the latest pending action of the same phone runs, with the stored payload; quote, BL
      and invoice drafts, issue an invoice (separate confirmation), customer payment, expense; audit "via WhatsApp".
- [ ] **P12-T03 Voice notes.** Media download; speech-to-text provider chosen on 10 to 20 real Tunisian voice
      notes from the owner and the drivers.
- [ ] **P12-T04 PDFs and photos.** Send a document's PDF; a receipt photo on an expense.
- [ ] **P12-T05 Screens, companies and budget.** The app is sold to several companies, all on **one bot number**
      run by the seller (owner, 2026-11-09, D-309). After the roles matrix: section `assistant` in `core/access.py`,
      tools filtered by section and level; WhatsApp number in the users screen; per company: on/off and monthly AI
      budget, usage per company (to bill it), per-user on/off; Mon profil: QR code and wa.me link; welcome message
      with examples for the role; one phone in two companies: the bot asks which; the prompt and the refusal carry no
      company name (the company comes from the organization, the bot speaks for the software's brand).
- [x] **P12-T06 "Assistant IA" screen with voice (D-314, owner 2026-11-10).** Sidebar section "Assistant IA" in the
      admin app: the same assistant without Meta (the unverified test account is locked, error 131031). Typed or
      dictated (browser dictation, تونسي / Français), answers read aloud ("Écouter", or "Réponses à voix haute"):
      Azure's Tunisian voice when the key is set, the browser's voice otherwise. Owner only until T05.
- [ ] **Test set.** 50+ real messages with the expected answer, run on demand (not in CI) to compare models
      (Haiku 5.5 vs Sonnet 5.5) and to check a prompt change.

## Check on staging (T06)

1. Log in as the owner: the menu shows "Assistant IA". Touch "chnowa 3andi f frigo?": the answer comes in a few
   seconds.
2. Chrome or Edge: touch the micro, allow it, say "chnowa 3andi f frigo?", touch the micro again: the question is
   sent and the answer comes in Arabic letters and is read aloud (Tunisian voice in Edge, or in any browser once the
   Azure key is in `.env`).
3. A manager does not see the menu entry, and `/assistant` shows "no access".

## Check on staging (T01)

1. Runbook "WhatsApp assistant": the Meta webhook saved, the keys in `.env`, `ASSISTANT_ENABLED=true`.
2. Django admin › Assistant WhatsApp › link the owner's phone.
3. From that phone: "chnowa 3andi f frigo?" → the stock; "9addech ysalni <client>?" → the balance.
4. From a number linked to nobody → "Ce numéro n'est pas autorisé…"; a voice note → "seulement les messages écrits".
