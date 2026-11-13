# TEIF files for El Fatoora (P11-T05b)

Found on the internet on 2026-11-13 (owner request), to build and test the invoice XML before a client's TTN
documents arrive. **Not received from TTN:** confirm the version TTN asks for at enrolment before going live.

| File | What |
|---|---|
| `teif-1.8.8-withoutSig.xsd` | The schema of an unsigned invoice, version 1.8.8 ("ajout contrôle MF"). XSD 1.0 form, usable with `xmllint` and `lxml`. |
| `teif-1.8.8-withSig.xsd`, `xmldsig-core-schema.xsd` | The schema of a signed invoice and the signature schema it imports. |
| `samples/minimal-invoice.xml`, `samples/sender-cin.xml` | Unsigned invoices that validate. |
| `samples/signed-supplier-submission.xml` | A signed invoice that validates against the signed schema. |

Source: <https://github.com/ayoubgaouet/tn-einvoice-validator> (MIT, licence copied here), which says it implements
TTN's XSD 1.8.8 and the "Guide d'Implémentation TEIF V2.0". Its `docs/TRACEABILITY.md` and rule catalogue list the
rules the guide adds to the schema (tax ID check, dates, code lists).

Check: `xmllint --nonet --noout --schema teif-1.8.8-withoutSig.xsd samples/minimal-invoice.xml` → "validates"
(run on 2026-11-13: the three samples validate, the project's invalid fixtures fail).

Version to confirm: another public project (<https://github.com/moncef110250/facture-electronique-ttn>) writes
`version="1.9.0"` with other element names (`AlcDetails`); its sample does not validate against this schema.
