# Assistant WhatsApp: mise en place, pas à pas (D-307, D-309)

One WhatsApp number for every client company, run by the seller of the software. A message's phone number tells
the bot which user wrote, in which company, with which role. It only shows that company's data, and only what that
role may see in the app.

Status column: **now** = works today; **T02…T05** = the Phase 12 task that brings it
(`docs/phases/12-whatsapp-assistant.md`).

## A. The seller, once for all companies

| # | Step | Status |
|---|---|---|
| A1 | developers.facebook.com: log in with Facebook, **Get started** (register as a developer). | now |
| A2 | **My Apps → Create app**, use case "Connect with customers through WhatsApp". Business portfolio in the seller's own name: no company or papers needed (unverified: 250 new contacts a day). | now |
| A3 | **WhatsApp → API Setup**: Meta's free test number. In **To**, add up to 5 personal phones (code by WhatsApp); **Send message** to receive "hello_world". | now |
| A4 | Keys: **Phone number ID** (API Setup); **App secret** (App settings → Basic); **permanent token**: business.facebook.com → Settings → Users → System users → Add (Admin) → Assign assets (the app, full control; the WhatsApp account) → Generate token with `whatsapp_business_messaging`, `whatsapp_business_management` and `business_management`, expiry Never. | now |
| A5 | console.anthropic.com → API Keys; Billing → Limits: a monthly limit. | now |
| A6 | Server `.env` (staging): `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_VERIFY_TOKEN` (a random string), `ANTHROPIC_API_KEY`, `ASSISTANT_ENABLED=true`; redeploy. Secrets never go in GitHub. | now (needs PR #341 and GitHub Actions billing) |
| A7 | Meta: **WhatsApp → Configuration → Webhook → Edit**: URL `https://app.fruttidelmare.com/api/v1/whatsapp/webhook`, the verify token of A6, **Verify and save**; **Webhook fields → Manage**: subscribe `messages`. | now |
| A8 | Test: Django admin → **WhatsApp links → Add** (your owner account, your phone). Send "chnowa 3andi f frigo?" to the test number. | now |
| A9 | Real number: a new SIM never used in the WhatsApp app. **WhatsApp → API Setup → Add phone number**: display name = the software's brand (Meta reviews it), code by SMS. Put its Phone number ID in `.env`. | when ready to sell |
| A10 | Before real users: the app in **Live** mode (Meta asks a privacy-policy URL); **WhatsApp Manager → Payment settings**: a card (Meta bills replies beyond 1 000 a month). | when ready to sell |
| A11 | When a company exists: Meta business verification (RNE extract, matricule fiscal, a document with the address) raises the limits and shows the verified name. | later |

## B. Each client company's owner, in the app

| # | Step | Status |
|---|---|---|
| B1 | **Paramètres → Assistant WhatsApp**: switch it on for the company, set its monthly limit. | T05 (today: the seller, server-wide) |
| B2 | **Rôles**: give "Assistant WhatsApp" to the roles that may use it (e.g. Gestionnaire, Chauffeur), or to one person. | roles matrix + T05 (today: owners only) |
| B3 | **Utilisateurs**: each user's WhatsApp number (`+216…` or 8 digits). One number belongs to one user. | T05 (today: Django admin) |
| B4 | Tell the users to open **Mon profil → Assistant WhatsApp**. | T05 |

## C. Each user

| # | Step | Status |
|---|---|---|
| C1 | **Mon profil → Assistant WhatsApp**: QR code or "Ouvrir WhatsApp" opens the chat with the bot; save the contact. | T05 (today: the number is given by hand) |
| C2 | Send "salam": the bot greets in the user's language with examples for their role. | T05 (today: it answers the question directly) |
| C3 | Ask in Tunisian, Arabic or French: "chnowa 3andi f frigo?", "9addech ysalni Mohamed?", "chkoun ma khallasch?", "9addech bi3na lyoum?"; a driver: "chnowa 3andi fel camion?". | now |
| C4 | Ask to do something: "7a4arli fatoura l Mohamed 12 kg 9ar3oun". The bot shows a summary with **Confirmer / Annuler**; nothing is saved before "Confirmer". | T02 |
| C5 | Voice notes instead of typing. | T03 |
| C6 | "Ab3athli el fatoura" → the PDF in the chat; a receipt photo with an expense. | T04 |
| C7 | What the role cannot see or do: "ma3andekch l7a9", as in the app. A number not registered, a user or company switched off: a refusal, nothing else. | now |
| C8 | A person working for two client companies with one phone: the bot asks which company. | T05 |
| C9 | Without WhatsApp: the menu **Assistant IA** of the application. Write, or touch the micro and speak (تونسي or Français); "Écouter" reads an answer aloud. | now, owner only (D-314) |
