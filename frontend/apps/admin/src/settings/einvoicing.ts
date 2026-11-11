import type { EInvoicingSettingsOverview } from "@frutti/api";

/** The status shown on the Paramètres card and at the top of the page (P11-T05a, D-310). */
export function einvoicingStatus(overview: EInvoicingSettingsOverview): "off" | "incomplete" | "ready" | "on" {
  if (overview.settings.enabled) return "on";
  return overview.ready ? "ready" : "incomplete";
}
