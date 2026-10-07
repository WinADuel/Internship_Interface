import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@testing-library/svelte";
import * as sessionModule from "../lib/stores/session";
import { ApiError } from "../lib/api/client";
import Login from "./Login.svelte";

describe("Login", () => {
  it("shows an error message when login fails", async () => {
    vi.spyOn(sessionModule, "login").mockRejectedValue(new ApiError(401, "invalid credentials"));
    const { getByLabelText, getByText, findByText } = render(Login);
    await fireEvent.input(getByLabelText("Username"), { target: { value: "dxwu" } });
    await fireEvent.input(getByLabelText("Password"), { target: { value: "wrong" } });
    await fireEvent.input(getByLabelText("Authenticator code"), { target: { value: "000000" } });
    await fireEvent.click(getByText("Log in"));
    expect(await findByText("invalid credentials")).toBeInTheDocument();
  });
});
