import { writable } from "svelte/store";
import { apiFetch, ApiError, jsonInit, setUnauthorizedHandler } from "../api/client";

export const session = writable<{ loggedIn: boolean; checked: boolean }>({
  loggedIn: false,
  checked: false,
});

setUnauthorizedHandler(() => session.set({ loggedIn: false, checked: true }));

export async function login(username: string, password: string, totpCode: string): Promise<void> {
  await apiFetch("/api/auth/login", jsonInit("POST", { username, password, totp_code: totpCode }));
  session.set({ loggedIn: true, checked: true });
}

export async function logout(): Promise<void> {
  await apiFetch("/api/auth/logout", { method: "POST" });
  session.set({ loggedIn: false, checked: true });
}

export async function checkSession(): Promise<void> {
  let loggedIn = false;
  try {
    try {
      await apiFetch("/api/auth/me");
      loggedIn = true;
    } catch (err) {
      if (!(err instanceof ApiError) || err.status !== 401) throw err;
      await apiFetch("/api/auth/refresh", { method: "POST" });
      await apiFetch("/api/auth/me");
      loggedIn = true;
    }
  } catch {
    loggedIn = false;
  }
  session.set({ loggedIn, checked: true });
}
