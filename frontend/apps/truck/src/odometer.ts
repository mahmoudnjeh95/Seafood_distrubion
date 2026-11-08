// The compteur typed on the "Clôture" screen (P10-T01, D-295).

/** The typed compteur as a number, or null while empty. */
export function parseOdometer(km: string): number | null {
  return /^\d{1,7}$/.test(km) ? Number(km) : null;
}

export function formatKm(km: number): string {
  return `${new Intl.NumberFormat("fr-FR").format(km)} km`;
}
