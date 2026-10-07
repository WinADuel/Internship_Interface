import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import { fakeApplication } from "../testing/fixtures";
import ApplicationCard from "./ApplicationCard.svelte";

describe("ApplicationCard keyboard", () => {
  function setup() {
    const onopen = vi.fn();
    render(ApplicationCard, { application: fakeApplication({ company: "Globex" }), onopen });
    return { onopen, card: screen.getByRole("button") };
  }

  it("opens on Enter", async () => {
    const { onopen, card } = setup();
    await fireEvent.keyDown(card, { key: "Enter" });
    expect(onopen).toHaveBeenCalledTimes(1);
  });

  it("opens on Space and prevents page scroll", async () => {
    const { onopen, card } = setup();
    const notPrevented = await fireEvent.keyDown(card, { key: " " });
    expect(onopen).toHaveBeenCalledTimes(1);
    expect(notPrevented).toBe(false);
  });

  it("ignores keydown coming from a child element", async () => {
    const { onopen } = setup();
    await fireEvent.keyDown(screen.getByText("Globex"), { key: "Enter" });
    await fireEvent.keyDown(screen.getByText("Globex"), { key: " " });
    expect(onopen).not.toHaveBeenCalled();
  });
});
