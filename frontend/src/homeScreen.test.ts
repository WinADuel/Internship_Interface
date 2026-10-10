// @vitest-environment node
/// <reference types="node" />
// "Add to Home Screen" support (Phase 3 spec §4.6): the links in index.html, the web app
// manifest, and the icons both point at.
import { existsSync, readFileSync } from "node:fs";

const frontendDir = new URL("../", import.meta.url);
const publicDir = new URL("../public/", import.meta.url);
const indexHtml = readFileSync(new URL("index.html", frontendDir), "utf8");

/** Width, height and PNG colour type, read from the IHDR chunk. */
function pngInfo(path: string) {
  const bytes = readFileSync(new URL(path.replace(/^\//, ""), publicDir));
  expect(bytes.subarray(1, 4).toString("ascii")).toBe("PNG");
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20), colourType: bytes[25] };
}

describe("index.html", () => {
  it("links the manifest", () => {
    expect(indexHtml).toContain('<link rel="manifest" href="/manifest.webmanifest" />');
  });

  it("links the apple-touch-icon and the SVG favicon", () => {
    expect(indexHtml).toContain('<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png" />');
    expect(indexHtml).toContain('<link rel="icon" href="/icons/icon.svg" type="image/svg+xml" />');
  });

  it("sets the theme colour to the app's primary colour", () => {
    expect(indexHtml).toContain('<meta name="theme-color" content="#1a5fb4" />');
  });

  it("opens full-screen from the iPhone home screen", () => {
    expect(indexHtml).toContain('<meta name="apple-mobile-web-app-capable" content="yes" />');
    expect(indexHtml).toContain('<meta name="mobile-web-app-capable" content="yes" />');
    expect(indexHtml).toContain('<meta name="apple-mobile-web-app-status-bar-style" content="default" />');
    expect(indexHtml).toContain('<meta name="apple-mobile-web-app-title" content="Tracker" />');
  });

  it("adds no inline scripts, which the CSP would block", () => {
    const scripts = indexHtml.match(/<script\b[^>]*>/g) ?? [];
    expect(scripts).toEqual(['<script type="module" src="/src/main.ts">']);
  });
});

describe("manifest.webmanifest", () => {
  const manifest = JSON.parse(readFileSync(new URL("manifest.webmanifest", publicDir), "utf8"));

  it("names the app, gives it a stable id and opens it standalone at the root", () => {
    expect(manifest.name).toBe("Internship Tracker");
    expect(manifest.short_name).toBe("Tracker");
    expect(manifest.id).toBe("/");
    expect(manifest.start_url).toBe("/");
    expect(manifest.scope).toBe("/");
    expect(manifest.display).toBe("standalone");
    expect(manifest.theme_color).toBe("#1a5fb4");
    expect(manifest.background_color).toBe("#ffffff");
  });

  it("lists 192 and 512 PNG icons whose files have those sizes", () => {
    const pngs = manifest.icons.filter((icon: { type: string }) => icon.type === "image/png");
    expect(pngs.map((icon: { sizes: string }) => icon.sizes).sort()).toEqual(["192x192", "512x512"]);
    for (const icon of pngs) {
      const size = Number(icon.sizes.split("x")[0]);
      expect(pngInfo(icon.src)).toMatchObject({ width: size, height: size });
    }
  });

  it("lists the SVG source as a scalable icon", () => {
    const svg = manifest.icons.find((icon: { type: string }) => icon.type === "image/svg+xml");
    expect(svg).toMatchObject({ src: "/icons/icon.svg", sizes: "any" });
    expect(existsSync(new URL("icons/icon.svg", publicDir))).toBe(true);
  });
});

describe("apple-touch-icon", () => {
  it("is 180×180 and opaque (iOS fills transparency with black)", () => {
    // Colour type 2 is RGB with no alpha channel.
    expect(pngInfo("/icons/apple-touch-icon.png")).toEqual({ width: 180, height: 180, colourType: 2 });
  });
});
