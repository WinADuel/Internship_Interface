import { describe, it, expect } from "vitest";
import { get } from "svelte/store";
import { toasts, showToast, dismissToast } from "./toast";

describe("toast store", () => {
  it("showToast appends a message that dismissToast removes", () => {
    showToast("something failed");
    const [message] = get(toasts);
    expect(message.text).toBe("something failed");
    expect(message.kind).toBe("error");
    dismissToast(message.id);
    expect(get(toasts)).toEqual([]);
  });
});
