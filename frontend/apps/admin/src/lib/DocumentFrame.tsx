import { formatDate, useTranslation } from "@frutti/i18n";
import type { ReactNode } from "react";

import { type DocumentParty, type DocumentSeller, uniqueIdentifier } from "./documentSeller";

/**
 * The header and footer of the company's paper invoice (D-125) on every document shown in the app (D-131), the
 * same frame the PDFs print: logo and company top left; boxed number, Date | Client box and client block top
 * right; the address and phone at the foot.
 */

// The identification types with their own short label (D-283); a tax ID prints "MF".
const ID_SHORT = { cin: true, passport: true, residence_card: true } as const;

function oneLine(text: string): string {
  return text
    .split("\n")
    .map((part) => part.trim())
    .filter(Boolean)
    .join(" - ");
}

export function DocumentHeader({
  seller,
  logoUrl,
  title,
  number,
  date,
  party,
  partyLabel,
  banner,
  meta,
}: {
  seller: DocumentSeller;
  logoUrl?: string | null;
  /** "Facture", "Devis"… */
  title: string;
  number: string;
  /** ISO date, or null when the document has none yet (a draft). */
  date: string | null;
  party: DocumentParty;
  /** "Client" unless said otherwise. */
  partyLabel?: string;
  /** Shown under the boxed number (a status stamp). */
  banner?: ReactNode;
  /** Shown under the client block (delivery notes, due date…). */
  meta?: ReactNode;
}) {
  const { t } = useTranslation();
  const label = partyLabel ?? t("admin.documents.frame.client");
  const unique = uniqueIdentifier(seller.tax_id);
  const address = [party.address, party.city].filter(Boolean).join(", ");
  const rows: [string, ReactNode][] = [
    [label, <b key="name">{party.name}</b>],
    ...(party.reference !== undefined
      ? [
          [
            t("admin.documents.frame.code", { label }),
            <span key="code" className="num">
              {party.reference}
            </span>,
          ] as [string, ReactNode],
        ]
      : []),
    [t("admin.documents.frame.address"), address],
    [
      t("admin.documents.frame.phone"),
      <span key="phone" className="num">
        {party.phone}
      </span>,
    ],
    [
      party.id_type && party.id_type !== "tax_id" && party.id_type in ID_SHORT
        ? t(`admin.customers.idShort.${party.id_type as keyof typeof ID_SHORT}`)
        : t("admin.documents.frame.taxId"),
      <span key="taxId" className="num">
        {party.tax_id}
      </span>,
    ],
  ];

  return (
    <header className="mb-5 flex flex-wrap items-start justify-between gap-6 text-[0.9rem]">
      <div className="min-w-[200px] flex-1">
        {logoUrl ? (
          <img src={logoUrl} alt={seller.name} className="mb-3 max-h-[90px] max-w-[220px] object-contain" />
        ) : (
          <p className="mb-3 font-display text-[1.25rem] font-extrabold text-sea">{seller.name}</p>
        )}
        {seller.address && <p className="whitespace-pre-line">{seller.address}</p>}
        {seller.phone && (
          <p>
            {t("admin.documents.frame.tel")} : <span className="num">{seller.phone}</span>
          </p>
        )}
        {seller.tax_id && (
          <p>
            {t("admin.documents.frame.taxId")} : <span className="num">{seller.tax_id}</span>
          </p>
        )}
        {unique && (
          <p>
            {t("admin.documents.frame.uniqueId")} : <span className="num">{unique}</span>
          </p>
        )}
        {seller.trade_register && (
          <p>
            {t("admin.documents.frame.tradeRegister")} : <span className="num">{seller.trade_register}</span>
          </p>
        )}
      </div>
      <div className="w-[min(340px,100%)]">
        <h2 className="mb-3 border-2 border-ink bg-surface-2 px-3 py-1.5 text-center text-[1rem] font-normal">
          {t("admin.documents.frame.heading", { title, number })}
        </h2>
        {banner && <div className="mb-3 text-center">{banner}</div>}
        <table className="w-full border-collapse text-center">
          <thead>
            <tr>
              <th className="border border-ink bg-surface-2 px-2 py-0.5">{t("admin.documents.frame.date")}</th>
              <th className="border border-ink bg-surface-2 px-2 py-0.5">{label}</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="num border border-ink px-2 py-0.5">{date ? formatDate(date) : "—"}</td>
              <td className="border border-ink px-2 py-0.5">{party.name}</td>
            </tr>
          </tbody>
        </table>
        <dl className="mt-4 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-0.5">
          {rows.map(([term, value]) => (
            <div key={term} className="contents">
              <dt className="font-bold">{term}:</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
        {meta && <div className="mt-3 text-[0.82rem] text-ink-2">{meta}</div>}
      </div>
    </header>
  );
}

export function DocumentFooter({ seller }: { seller: DocumentSeller }) {
  const { t } = useTranslation();
  const parts = [
    seller.address && `${t("admin.documents.frame.address")} : ${oneLine(seller.address)}`,
    seller.phone && `${t("admin.documents.frame.phone")} : ${seller.phone}`,
  ].filter(Boolean);
  if (parts.length === 0) return null;
  return <footer className="mt-6 border-t border-ink pt-2 text-[0.82rem]">{parts.join(" · ")}</footer>;
}
