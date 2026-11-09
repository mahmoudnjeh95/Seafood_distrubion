import { applyLanguage } from "@frutti/i18n";
import { QueryClientProvider, useMutation } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { LoginPage } from "./LoginPage";
import { RequireRole } from "./RequireRole";
import { apiFetch } from "@frutti/api";

import { createQueryClient, type Role, type Session, useLogout } from "./session";

function sessionFor(role: Role): Session {
  return {
    user: { id: 1, username: "sami", first_name: "Sami", last_name: "B.", email: "", language: "fr", avatar_url: null },
    organization: { id: 1, name: "Frutti Del Mare", logo_url: null },
    role,
    role_label: role,
    access: {},
    can_buy: false,
    truck: null,
  };
}

function json(status: number, body: unknown) {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** A fake server: `/me` answers with the current session, login and logout change it. */
function fakeServer(initial: Session | null, accounts: Record<string, Session> = {}) {
  let current = initial;
  // Lets a test log another account in "from another tab": the cookie, hence the session, is replaced.
  switchTo = (session) => {
    current = session;
  };
  const calls: { path: string; method: string; csrf: string | null }[] = [];
  const handler = vi.fn((input: string, init?: RequestInit) => {
    const path = input.replace("/api/v1", "");
    const method = init?.method ?? "GET";
    calls.push({ path, method, csrf: new Headers(init?.headers).get("X-CSRFToken") });
    if (path === "/auth/csrf") {
      document.cookie = "csrftoken=test-token";
      return Promise.resolve(json(204, null));
    }
    if (path === "/me") return Promise.resolve(current ? json(200, current) : json(401, { detail: "Non connecté" }));
    if (path === "/auth/login") {
      const { username, password } = JSON.parse(typeof init?.body === "string" ? init.body : "{}") as {
        username: string;
        password: string;
      };
      const account = accounts[username];
      if (!account || password !== "secret") {
        return Promise.resolve(json(401, { detail: "Identifiant ou mot de passe incorrect." }));
      }
      current = account;
      return Promise.resolve(json(200, account));
    }
    if (path === "/products/5") {
      const allowed = current?.role === "owner";
      return Promise.resolve(allowed ? json(200, {}) : json(current ? 403 : 401, { detail: "Refusé" }));
    }
    if (path === "/auth/logout") {
      current = null;
      return Promise.resolve(json(204, null));
    }
    return Promise.resolve(json(404, { detail: "Not found" }));
  });
  vi.stubGlobal("fetch", handler);
  return calls;
}

let switchTo: (session: Session | null) => void = () => undefined;

// The logout button lives in a child of the guard, as in the real apps.
function Home({ session }: { session: Session }) {
  const logout = useLogout();
  const save = useMutation({ mutationFn: () => apiFetch("/api/v1/products/5", { method: "PATCH" }) });
  return (
    <>
      <p>Bonjour {session.user.first_name}</p>
      <button type="button" onClick={() => save.mutate()}>
        Enregistrer
      </button>
      <button type="button" onClick={() => logout.mutate()}>
        Quitter
      </button>
    </>
  );
}

function renderApp(allow: Role[], start = "/") {
  const queryClient = createQueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[start]}>
        <Routes>
          <Route path="/login" element={<LoginPage title="Connexion" app="admin" />} />
          <Route
            path="/"
            element={
              <RequireRole allow={allow} wrongAppMessage="Mauvaise application">
                {(session) => <Home session={session} />}
              </RequireRole>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  applyLanguage("fr");
});

test("a logged-out visitor is sent to the login screen", async () => {
  fakeServer(null);

  renderApp(["owner"]);

  expect(await screen.findByRole("form", { name: "Connexion" })).toBeDefined();
});

test("logging in shows the protected page and sends the CSRF token", async () => {
  const calls = fakeServer(null, { owner: sessionFor("owner") });
  const user = userEvent.setup();
  renderApp(["owner", "manager"]);

  await user.type(await screen.findByLabelText("Identifiant"), "owner");
  await user.type(screen.getByLabelText("Mot de passe"), "secret");
  await user.click(screen.getByRole("button", { name: "Se connecter" }));

  expect(await screen.findByText("Bonjour Sami")).toBeDefined();
  expect(calls.find((call) => call.path === "/auth/login")?.csrf).toBe("test-token");
});

test("a wrong password shows the server's message and stays on the login screen", async () => {
  fakeServer(null, { owner: sessionFor("owner") });
  const user = userEvent.setup();
  renderApp(["owner"]);

  await user.type(await screen.findByLabelText("Identifiant"), "owner");
  await user.type(screen.getByLabelText("Mot de passe"), "wrong");
  await user.click(screen.getByRole("button", { name: "Se connecter" }));

  expect((await screen.findByRole("alert")).textContent).toBe("Identifiant ou mot de passe incorrect.");
  expect(screen.queryByText("Bonjour Sami")).toBeNull();
});

test("a role that belongs to the other app is turned away and can log out", async () => {
  const calls = fakeServer(sessionFor("driver"));
  const user = userEvent.setup();
  renderApp(["owner", "manager", "accountant"]);

  expect((await screen.findByRole("alert")).textContent).toBe("Mauvaise application");
  expect(screen.queryByText("Bonjour Sami")).toBeNull();

  await user.click(screen.getByRole("button", { name: "Se déconnecter" }));

  expect(await screen.findByRole("form", { name: "Connexion" })).toBeDefined();
  await waitFor(() => expect(calls.some((call) => call.path === "/auth/logout" && call.method === "POST")).toBe(true));
});

test("an allowed role sees the protected page straight away", async () => {
  fakeServer(sessionFor("driver"));

  renderApp(["driver"]);

  expect(await screen.findByText("Bonjour Sami")).toBeDefined();
});

test("logging out from the protected page returns to the login screen", async () => {
  fakeServer(sessionFor("driver"));
  const user = userEvent.setup();
  renderApp(["driver"]);

  await user.click(await screen.findByRole("button", { name: "Quitter" }));

  expect(await screen.findByRole("form", { name: "Connexion" })).toBeDefined();
  expect(screen.queryByText("Bonjour Sami")).toBeNull();
});

test("the app follows the language saved on the account, including the reading direction", async () => {
  const driver = sessionFor("driver");
  const arabicDriver: Session = { ...driver, user: { ...driver.user, language: "ar" } };
  fakeServer(arabicDriver);

  renderApp(["driver"]);

  expect(await screen.findByText("Bonjour Sami")).toBeDefined();
  await waitFor(() => expect(document.documentElement.dir).toBe("rtl"));
  expect(document.documentElement.lang).toBe("ar");
});

test("a login to another account in another tab shows at the next refused request", async () => {
  fakeServer({ ...sessionFor("owner"), user: { ...sessionFor("owner").user, first_name: "Nadia" } });
  const user = userEvent.setup();
  renderApp(["owner", "manager", "accountant"]);
  await screen.findByText("Bonjour Nadia");

  switchTo(sessionFor("driver"));
  await user.click(screen.getByRole("button", { name: "Enregistrer" }));

  expect((await screen.findByRole("alert")).textContent).toBe("Mauvaise application");
});

test("a session that ended shows the login screen at the next refused request", async () => {
  fakeServer(sessionFor("owner"));
  const user = userEvent.setup();
  renderApp(["owner"]);
  await screen.findByText("Bonjour Sami");

  switchTo(null);
  await user.click(screen.getByRole("button", { name: "Enregistrer" }));

  expect(await screen.findByRole("form", { name: "Connexion" })).toBeDefined();
});
