<script lang="ts">
  import { onMount } from "svelte";
  import { ApiError } from "../../api/client";
  import { startScan } from "../../api/discovery";
  import { formatDateTime } from "../../format";
  import { discoveryStatus, refreshDiscoveryStatus } from "../../stores/discovery";
  import { showToast } from "../../stores/toast";

  let { onfinished }: { onfinished?: () => void } = $props();

  const POLL_MS = 5000;

  let starting = $state(false);
  const scanning = $derived($discoveryStatus?.scanning ?? false);
  // The backend joins per-source errors with "; " (one line each here).
  const errors = $derived(
    ($discoveryStatus?.lastScanError ?? "")
      .split("; ")
      .map((line) => line.trim())
      .filter(Boolean),
  );

  let mounted = true;
  onMount(() => {
    void refreshDiscoveryStatus();
    return () => (mounted = false);
  });

  function markScanning() {
    discoveryStatus.update((s) =>
      s
        ? { ...s, scanning: true }
        : { lastScanAt: null, lastScanError: null, scanning: true, inboxCount: 0 },
    );
  }

  let polling = false;
  async function poll() {
    if (polling) return; // a slow request is still out; don't stack another
    polling = true;
    try {
      const status = await refreshDiscoveryStatus();
      if (mounted && status && !status.scanning) onfinished?.();
    } finally {
      polling = false;
    }
  }

  // Poll only while a scan runs; the cleanup stops it when the scan ends or the page unmounts.
  $effect(() => {
    if (!scanning) return;
    const timer = setInterval(poll, POLL_MS);
    return () => clearInterval(timer);
  });

  async function scanNow() {
    starting = true;
    try {
      await startScan();
      markScanning();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        showToast("A scan is already running", "info");
        markScanning();
      } else {
        showToast(err instanceof ApiError ? `Couldn't start a scan: ${err.message}` : "Couldn't start a scan.");
      }
    } finally {
      starting = false;
    }
  }
</script>

<section class="scan" aria-label="Scan">
  <div class="line">
    <span role="status">
      {#if scanning}
        Scanning…
      {:else if $discoveryStatus?.lastScanAt}
        Last scan: {formatDateTime($discoveryStatus.lastScanAt)}
      {:else if $discoveryStatus}
        No scan yet.
      {/if}
    </span>
    <button type="button" disabled={scanning || starting} onclick={scanNow}>Scan now</button>
  </div>
  {#if errors.length && !scanning}
    <div class="errors">
      <span>Some sources failed in the last scan:</span>
      <ul>
        {#each errors as line, i (i)}
          <li>{line}</li>
        {/each}
      </ul>
    </div>
  {/if}
</section>

<style>
  .scan { display: flex; flex-direction: column; gap: 0.3rem; margin-bottom: 1rem; }
  .line { display: flex; flex-wrap: wrap; align-items: center; gap: 0.75rem; color: #555; }
  .errors { font-size: 0.85rem; color: #8c1d18; }
  .errors ul { margin: 0.2rem 0 0; padding-left: 1.2rem; }
  .errors li { overflow-wrap: anywhere; }
</style>
