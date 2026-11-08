import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";

import { TrainingTag } from "./TrainingTag";
import { LoginPage } from "./LoginPage";
import { createQueryClient } from "./session";

function serve(instance: { training: boolean; training_admin_url: string; training_driver_url: string }) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) => {
      const body = input.endsWith("/instance") ? instance : { detail: "Non connecté" };
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: input.endsWith("/instance") ? 200 : 401,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }),
  );
}

function renderLogin(app: "admin" | "driver") {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <TrainingTag />
        <LoginPage title="Connexion" app={app} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

test("production's login screen links to the training copy of the same app, without the tag", async () => {
  serve({
    training: false,
    training_admin_url: "https://app1.fruttidelmare.com",
    training_driver_url: "https://ch1.fruttidelmare.com",
  });

  renderLogin("driver");

  const link = await screen.findByRole("link", { name: "Se connecter en mode formation" });
  expect(link.getAttribute("href")).toBe("https://ch1.fruttidelmare.com");
  expect(screen.queryByText("Formation")).toBeNull();
});

test("the training copy shows the Formation tag, kept for when the phone is offline", async () => {
  serve({ training: true, training_admin_url: "", training_driver_url: "" });

  renderLogin("admin");

  expect(await screen.findByText("Formation")).toBeDefined();
  expect(screen.queryByRole("link", { name: "Se connecter en mode formation" })).toBeNull();
  expect(JSON.parse(localStorage.getItem("frutti.instance") ?? "{}")).toMatchObject({ training: true });
});
