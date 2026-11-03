// The phone keeps a copy of the company logo, so the login screen and the browser-tab icon show it before any login
// (D-125, D-154). It is a data: address, not the logo's URL: the server serves the logo only to a logged-in user, so
// the URL fails on the login screen. Not a secret: it is the logo every document already carries. Storage can be
// blocked: then the default icon stays. The printed receipt draws it at the top too (D-282).
const LOGO_KEY = "frutti-truck-logo";

export function rememberedLogo(): string | null {
  try {
    return localStorage.getItem(LOGO_KEY);
  } catch {
    return null;
  }
}

export function remember(logo: string | null): void {
  try {
    if (logo) localStorage.setItem(LOGO_KEY, logo);
    else localStorage.removeItem(LOGO_KEY);
  } catch {
    // Not saved: the next login screen shows the default icon until a login works again.
  }
}
