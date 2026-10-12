// Render SVG files to PNG at given sizes and screenshot review sheets.
// Usage: node render.js svg <size> <out.png> <in.svg> [more.svg...]   (out is a dir when several)
//        node render.js html <width> <out.png> <in.html>
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

async function main() {
  const [mode, sizeArg, out, ...inputs] = process.argv.slice(2);
  const size = parseInt(sizeArg, 10);
  const browser = await chromium.launch();
  try {
    if (mode === 'svg') {
      const page = await browser.newPage({ viewport: { width: size, height: size }, deviceScaleFactor: 1 });
      for (const input of inputs) {
        const svg = fs.readFileSync(input, 'utf8');
        await page.setContent(
          `<style>html,body{margin:0;background:transparent}svg{display:block;width:${size}px;height:${size}px}</style>${svg}`,
          { waitUntil: 'load' });
        const target = inputs.length > 1 ? path.join(out, path.basename(input, '.svg') + `-${size}.png`) : out;
        await page.screenshot({ path: target, omitBackground: true, clip: { x: 0, y: 0, width: size, height: size } });
      }
    } else {
      const page = await browser.newPage({ viewport: { width: size, height: 800 }, deviceScaleFactor: 2 });
      await page.goto('file://' + path.resolve(inputs[0]), { waitUntil: 'load' });
      await page.screenshot({ path: out, fullPage: true });
    }
  } finally {
    await browser.close();
  }
}
main().catch((error) => { console.error(error); process.exit(1); });
