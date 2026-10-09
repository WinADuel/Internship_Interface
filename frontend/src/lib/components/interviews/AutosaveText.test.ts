import { fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import AutosaveText from "./AutosaveText.svelte";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

function setup(save = vi.fn().mockResolvedValue(undefined), value: string | null = "old") {
  const view = render(AutosaveText, { props: { label: "Prep notes", value, save } });
  return { save, view, box: screen.getByLabelText("Prep notes") as HTMLTextAreaElement };
}

describe("AutosaveText", () => {
  it("starts from the value and saves a second after typing stops", async () => {
    const { save, box } = setup();
    expect(box.value).toBe("old");
    await fireEvent.input(box, { target: { value: "new t" } });
    await vi.advanceTimersByTimeAsync(500);
    await fireEvent.input(box, { target: { value: "new text" } });
    await vi.advanceTimersByTimeAsync(999);
    expect(save).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toBe("Unsaved changes…");
    await vi.advanceTimersByTimeAsync(1);
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith("new text");
    expect(screen.getByRole("status").textContent).toBe("Saved");
  });

  it("saves at once on blur, and not again when nothing changed", async () => {
    const { save, box } = setup();
    await fireEvent.input(box, { target: { value: "typed" } });
    await fireEvent.blur(box);
    await vi.advanceTimersByTimeAsync(0);
    expect(save).toHaveBeenCalledWith("typed");
    await fireEvent.blur(box);
    await vi.advanceTimersByTimeAsync(2000);
    expect(save).toHaveBeenCalledTimes(1);
  });

  it("sends null for blank text", async () => {
    const { save, box } = setup();
    await fireEvent.input(box, { target: { value: "   " } });
    await fireEvent.blur(box);
    await vi.advanceTimersByTimeAsync(0);
    expect(save).toHaveBeenCalledWith(null);
  });

  it("shows a failure and retries on the next edit", async () => {
    const save = vi.fn().mockRejectedValueOnce(new Error("down")).mockResolvedValue(undefined);
    const { box } = setup(save);
    await fireEvent.input(box, { target: { value: "a" } });
    await vi.advanceTimersByTimeAsync(1000);
    expect(screen.getByRole("status").textContent).toMatch(/Couldn't save/);
    await fireEvent.input(box, { target: { value: "ab" } });
    await vi.advanceTimersByTimeAsync(1000);
    expect(save).toHaveBeenLastCalledWith("ab");
    expect(screen.getByRole("status").textContent).toBe("Saved");
  });

  it("saves text typed while a save was in flight", async () => {
    let finish: () => void = () => {};
    const save = vi.fn().mockImplementationOnce(() => new Promise<void>((r) => (finish = r))).mockResolvedValue(undefined);
    const { box } = setup(save);
    await fireEvent.input(box, { target: { value: "one" } });
    await vi.advanceTimersByTimeAsync(1000);
    await fireEvent.input(box, { target: { value: "one two" } });
    finish();
    await vi.advanceTimersByTimeAsync(1000);
    expect(save.mock.calls.map((c) => c[0])).toEqual(["one", "one two"]);
  });

  it("saves unsaved text when it goes away", async () => {
    const { save, box, view } = setup();
    await fireEvent.input(box, { target: { value: "leaving" } });
    view.unmount();
    expect(save).toHaveBeenCalledWith("leaving");
  });

  it("doesn't save again when it goes away while a blur's save of the same text is in flight", async () => {
    let finish: () => void = () => {};
    const save = vi.fn().mockImplementationOnce(() => new Promise<void>((r) => (finish = r))).mockResolvedValue(undefined);
    const { box, view } = setup(save);
    await fireEvent.input(box, { target: { value: "leaving" } });
    await fireEvent.blur(box);
    view.unmount();
    finish();
    await vi.advanceTimersByTimeAsync(2000);
    expect(save.mock.calls.map((c) => c[0])).toEqual(["leaving"]);
  });

  it("saves newer text once when the timer and a blur both wait on a save in flight", async () => {
    let finish: () => void = () => {};
    const save = vi.fn().mockImplementationOnce(() => new Promise<void>((r) => (finish = r))).mockResolvedValue(undefined);
    const { box } = setup(save);
    await fireEvent.input(box, { target: { value: "one" } });
    await fireEvent.blur(box);
    await fireEvent.input(box, { target: { value: "one two" } });
    await vi.advanceTimersByTimeAsync(1000); // the timer fires while "one" is still saving
    await fireEvent.blur(box);
    finish();
    await vi.advanceTimersByTimeAsync(2000);
    expect(save.mock.calls.map((c) => c[0])).toEqual(["one", "one two"]);
    expect(screen.getByRole("status").textContent).toBe("Saved");
  });

  it("saves the newest text when it goes away during a save of older text", async () => {
    let finish: () => void = () => {};
    const save = vi.fn().mockImplementationOnce(() => new Promise<void>((r) => (finish = r))).mockResolvedValue(undefined);
    const { box, view } = setup(save);
    await fireEvent.input(box, { target: { value: "one" } });
    await fireEvent.blur(box);
    await fireEvent.input(box, { target: { value: "one two" } });
    view.unmount();
    finish();
    await vi.advanceTimersByTimeAsync(0);
    expect(save.mock.calls.map((c) => c[0])).toEqual(["one", "one two"]);
  });

  it("says when what it saves to no longer exists", async () => {
    const save = vi.fn().mockRejectedValue(new ApiError(404, "interview round not found"));
    const { box } = setup(save);
    await fireEvent.input(box, { target: { value: "a" } });
    await fireEvent.blur(box);
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByRole("status").textContent).toBe("This round no longer exists.");
  });
});
