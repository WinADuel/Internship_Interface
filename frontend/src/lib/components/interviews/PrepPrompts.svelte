<script lang="ts">
  import { buildPrepPrompts, type PromptContext } from "../../prep/prompts";
  import { showToast } from "../../stores/toast";

  let { context }: { context: PromptContext } = $props();

  const prompts = $derived(buildPrepPrompts(context));

  async function copy(text: string) {
    try {
      if (!navigator.clipboard) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(text);
      showToast("Copied. Paste it into claude.ai.", "info");
    } catch {
      showToast("Could not copy. Select the text and copy it manually.");
    }
  }
</script>

<section aria-labelledby="prompts-heading">
  <h2 id="prompts-heading">Claude prompts</h2>
  <p class="intro">
    Copy a prompt, filled in for this round, and paste it into
    <a href="https://claude.ai" target="_blank" rel="noopener noreferrer">claude.ai</a>.
  </p>
  <ul>
    {#each prompts as p (p.id)}
      <li>
        <details>
          <summary>{p.title}</summary>
          <pre>{p.prompt}</pre>
        </details>
        <button type="button" aria-label={`Copy ${p.title} prompt`} onclick={() => copy(p.prompt)}>Copy</button>
      </li>
    {/each}
  </ul>
</section>

<style>
  h2 { font-size: 1.05rem; margin: 0 0 0.4rem; }
  .intro { font-size: 0.9rem; color: #555; margin: 0 0 0.4rem; }
  ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.4rem; }
  li { display: flex; align-items: flex-start; justify-content: space-between; gap: 0.5rem; }
  details { min-width: 0; flex: 1 1 auto; }
  summary { cursor: pointer; }
  pre { white-space: pre-wrap; overflow-wrap: anywhere; font-family: inherit; font-size: 0.85rem; background: #f6f6f6; padding: 0.5rem; border-radius: 6px; user-select: text; }
</style>
