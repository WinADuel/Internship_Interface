<script lang="ts">
  import { push } from "svelte-spa-router";
  import { login } from "../lib/stores/session";

  let username = $state("");
  let password = $state("");
  let totpCode = $state("");
  let error = $state("");
  let submitting = $state(false);

  async function submit(event: Event) {
    event.preventDefault();
    error = "";
    submitting = true;
    try {
      await login(username, password, totpCode);
      await push("/");
    } catch (e) {
      error = e instanceof Error ? e.message : "Login failed";
    } finally {
      submitting = false;
    }
  }
</script>

<form onsubmit={submit}>
  <h1>Sign in</h1>
  <label for="username">Username</label>
  <input id="username" autocomplete="username" bind:value={username} />
  <label for="password">Password</label>
  <input id="password" type="password" autocomplete="current-password" bind:value={password} />
  <label for="totp">Authenticator code</label>
  <input id="totp" inputmode="numeric" autocomplete="one-time-code" bind:value={totpCode} />
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  <button type="submit" disabled={submitting}>Log in</button>
</form>

<style>
  form { display: flex; flex-direction: column; gap: 0.5rem; max-width: 20rem; margin: 4rem auto; }
  .error { color: #b3261e; margin: 0; }
</style>
