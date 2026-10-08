import { fireEvent, render, screen } from "@testing-library/svelte";
import { tick } from "svelte";
import { describe, expect, it, vi } from "vitest";
import ChipInput from "./ChipInput.svelte";

function setup(props: Partial<{ items: string[]; suggestions: string[]; maxItems: number; maxLength: number; validate: (v: string) => string | null }> = {}) {
  const onchange = vi.fn();
  const result = render(ChipInput, { label: "Terms", items: [], onchange, ...props });
  return { ...result, onchange };
}

async function type(value: string) {
  const input = screen.getByLabelText("Terms");
  await fireEvent.input(input, { target: { value } });
  await fireEvent.keyDown(input, { key: "Enter" });
}

describe("ChipInput", () => {
  it("shows each item as a chip with its own Remove button", () => {
    setup({ items: ["Summer 2027", "Fall 2027"] });
    expect(screen.getByText("Summer 2027")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove Fall 2027 from Terms" })).toBeInTheDocument();
  });

  it("adds a trimmed item on Enter and clears the input", async () => {
    const { onchange } = setup({ items: ["Summer 2027"] });
    await type("  Fall 2027 ");
    expect(onchange).toHaveBeenLastCalledWith(["Summer 2027", "Fall 2027"]);
    expect(screen.getByText("Fall 2027")).toBeInTheDocument();
    expect((screen.getByLabelText("Terms") as HTMLInputElement).value).toBe("");
  });

  it("adds with the Add button too, and Enter never submits the surrounding form", async () => {
    const { onchange } = setup();
    const input = screen.getByLabelText("Terms");
    await fireEvent.input(input, { target: { value: "Winter 2027" } });
    const enter = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
    input.dispatchEvent(enter);
    expect(enter.defaultPrevented).toBe(true);
    await tick();
    await fireEvent.input(input, { target: { value: "Spring 2028" } });
    await fireEvent.click(screen.getByRole("button", { name: "Add to Terms" }));
    expect(onchange).toHaveBeenLastCalledWith(["Winter 2027", "Spring 2028"]);
  });

  it("removes an item", async () => {
    const { onchange } = setup({ items: ["Summer 2027", "Fall 2027"] });
    await fireEvent.click(screen.getByRole("button", { name: "Remove Summer 2027 from Terms" }));
    expect(onchange).toHaveBeenLastCalledWith(["Fall 2027"]);
    expect(screen.queryByText("Summer 2027")).toBeNull();
  });

  it("ignores a duplicate in any case and says so", async () => {
    const { onchange } = setup({ items: ["Summer 2027"] });
    await type("summer 2027");
    expect(onchange).not.toHaveBeenCalled();
    expect(screen.getByText("“summer 2027” is already in the list.")).toBeInTheDocument();
    expect(screen.getAllByText(/Summer 2027/i)).toHaveLength(2); // the chip and the message
  });

  it("ignores blank input", async () => {
    const { onchange } = setup();
    await type("   ");
    expect(onchange).not.toHaveBeenCalled();
  });

  it("enforces the length and count caps", async () => {
    const { onchange } = setup({ items: ["a"], maxItems: 2, maxLength: 5 });
    await type("toolong");
    expect(screen.getByText("Each entry can be at most 5 characters.")).toBeInTheDocument();
    await type("ok");
    expect(onchange).toHaveBeenLastCalledWith(["a", "ok"]);
    await type("more");
    expect(screen.getByText("At most 2 entries.")).toBeInTheDocument();
    expect(onchange).toHaveBeenCalledTimes(1);
  });

  it("runs the custom check", async () => {
    const validate = (v: string) => (v.startsWith("https://") ? null : "Use an https:// link.");
    const { onchange } = setup({ validate });
    await type("http://example.com");
    expect(screen.getByText("Use an https:// link.")).toBeInTheDocument();
    expect(onchange).not.toHaveBeenCalled();
  });

  it("offers suggestions not already present", async () => {
    const { onchange } = setup({ items: ["software"], suggestions: ["Software", "Hardware", "Quant"] });
    expect(screen.queryByRole("button", { name: "Add Software to Terms" })).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Add Quant to Terms" }));
    expect(onchange).toHaveBeenLastCalledWith(["software", "Quant"]);
    expect(screen.queryByRole("button", { name: "Add Quant to Terms" })).toBeNull();
    expect(screen.getByRole("button", { name: "Add Hardware to Terms" })).toBeInTheDocument();
  });

  it("shows an error passed in from the parent", () => {
    render(ChipInput, { label: "Terms", items: [], error: "at most 30 items" });
    expect(screen.getByText("at most 30 items")).toBeInTheDocument();
    expect(screen.getByLabelText("Terms")).toHaveAttribute("aria-invalid", "true");
  });

  it("renders items as plain text", () => {
    const { container } = setup({ items: ["<img src=x onerror=alert(1)>"] });
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
});
