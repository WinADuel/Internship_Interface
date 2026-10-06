import { writable } from "svelte/store";
import { apiFetch } from "../api/client";

export const session = writable<{ loggedIn: boolean }>({ loggedIn: false });

export async function login(username: string, password: string, totpCode: string): Promise<void> {
  await apiFetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, totp_code: totpCode }),
  });
  session.set({ loggedIn: true });
}

export async function logout(): Promise<void> {
  await apiFetch("/api/auth/logout", { method: "POST" });
  session.set({ loggedIn: false });
}
