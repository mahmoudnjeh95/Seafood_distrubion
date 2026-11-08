import { useGetFinanceSettings } from "@frutti/api";
import type { Session } from "@frutti/auth";

/** Who is printed in the header of a document shown in the app (D-131), see `DocumentFrame`. */
export type DocumentSeller = {
  name: string;
  address: string;
  phone: string;
  tax_id: string;
  trade_register: string;
};

export type DocumentParty = {
  name: string;
  /** The customer's code; the row is left out when undefined. */
  reference?: string;
  address: string;
  city: string;
  phone: string;
  tax_id: string;
  /** What `tax_id` is (D-283): the row's label follows it ("MF", "CIN"…). */
  id_type?: string;
};

/** The company as the finance settings in force describe it (what a quote or a BL prints, D-043). */
export function useSeller(session: Session): DocumentSeller {
  const query = useGetFinanceSettings();
  const version = query.data?.in_force;
  return {
    name: version?.legal_name || session.organization.name,
    address: version?.address ?? "",
    phone: version?.phone ?? "",
    tax_id: version?.tax_id ?? "",
    trade_register: version?.trade_register ?? "",
  };
}

/** The "Identifiant unique" of a Tunisian tax id: its number and key letter (1902781/R/N/M/000 → 1902781R). */
export function uniqueIdentifier(taxId: string): string {
  const parts = taxId.replace(/\s/g, "").toUpperCase().split("/");
  const [number = "", key = ""] = parts;
  return parts.length >= 2 && /^\d+$/.test(number) && /^[A-Z]+$/.test(key) ? number + key : "";
}
