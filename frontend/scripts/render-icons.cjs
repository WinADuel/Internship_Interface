// Renders the app icons in public/icons/ from public/icons/icon.svg, in headless Chromium.
// Run from frontend/ after editing the SVG, then commit the PNGs:
//   NODE_PATH="$(npm root -g)" node scripts/render-icons.cjs
// It needs Playwright (npm i -g playwright) and its Chromium (npx playwright install chromium).
// Playwright is not a project dependency, as this only runs when the icon changes.
const { readFileSync, writeFileSync } = require("node:fs");
const { join } = require("node:path");
const zlib = require("node:zlib");
const { chromium } = require("playwright");

const ICONS = join(__dirname, "..", "public", "icons");
const PRIMARY = "#1a5fb4";

// apple-touch-icon must be opaque (iOS shows transparency as black) and iOS rounds the
// corners itself, so it is drawn full-bleed on the primary colour.
const OUTPUTS = [
  { file: "icon-192.png", size: 192 },
  { file: "icon-512.png", size: 512 },
  { file: "apple-touch-icon.png", size: 180, background: PRIMARY },
];

/** A minimal PNG encoder: 8-bit RGBA (colour type 6), or RGB (type 2) when `opaque`. */
function encodePng(width, height, rgba, opaque) {
  const channels = opaque ? 3 : 4;
  const raw = Buffer.alloc(height * (1 + width * channels));
  let o = 0;
  for (let y = 0; y < height; y++) {
    raw[o++] = 0; // filter: none
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      for (let c = 0; c < channels; c++) raw[o++] = rgba[i + c];
    }
  }
  const chunk = (type, data) => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(zlib.crc32(body));
    return Buffer.concat([len, body, crc]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = opaque ? 2 : 6;
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", zlib.deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

async function main() {
  const svg = readFileSync(join(ICONS, "icon.svg"), "utf8");
  const svgUrl = `data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}`;
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    for (const { file, size, background } of OUTPUTS) {
      const pixels = await page.evaluate(
        async ({ svgUrl, size, background }) => {
          const img = new Image();
          img.src = svgUrl;
          await img.decode();
          const canvas = document.createElement("canvas");
          canvas.width = canvas.height = size;
          const ctx = canvas.getContext("2d");
          if (background) {
            ctx.fillStyle = background;
            ctx.fillRect(0, 0, size, size);
          }
          ctx.drawImage(img, 0, 0, size, size);
          return Array.from(ctx.getImageData(0, 0, size, size).data);
        },
        { svgUrl, size, background },
      );
      const png = encodePng(size, size, Buffer.from(pixels), Boolean(background));
      writeFileSync(join(ICONS, file), png);
      console.log(`${file}: ${size}x${size}, ${png.length} bytes`);
    }
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
