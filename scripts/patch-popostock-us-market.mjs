#!/usr/bin/env node

import { createHash } from "node:crypto";
import {
  existsSync,
  readFileSync,
  readdirSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { basename, dirname, join, resolve } from "node:path";

function readArgument(name, fallback) {
  const index = process.argv.indexOf(name);
  return index === -1 ? fallback : process.argv[index + 1];
}

const siteDir = resolve(readArgument("--site-dir", "dist-popostock"));
const assetDir = join(siteDir, "assets");

if (!existsSync(assetDir)) {
  throw new Error(`找不到正式站資產目錄：${assetDir}`);
}

const candidates = readdirSync(assetDir)
  .filter((name) => /^index-[^.]+\.js$/.test(name))
  .map((name) => join(assetDir, name));

let target = null;
for (const path of candidates) {
  const source = readFileSync(path, "utf8");
  if (
    source.includes("children:`台股加權指數大盤`") &&
    source.includes("comparisonCode:`VIXTWN`")
  ) {
    target = { path, source };
    break;
  }
}

if (!target) {
  throw new Error("找不到正式站台股大盤元件，停止加入美股大盤。");
}

if (
  target.source.includes("children:`美股大盤`") &&
  target.source.includes("===`usMarket`")
) {
  console.log(
    JSON.stringify({
      unchanged: true,
      asset: basename(target.path),
    }),
  );
  process.exit(0);
}

const taiexButtonPattern =
  /\(0,([A-Za-z_$][\w$]*)\.jsx\)\(`button`,\{"aria-selected":([A-Za-z_$][\w$]*)===`taiex`,className:\2===`taiex`\?`is-active`:``,onClick:\(\)=>\s*([A-Za-z_$][\w$]*)\(`taiex`\),role:`tab`,type:`button`,children:`台股加權指數大盤`\}\)/;
const buttonMatch = taiexButtonPattern.exec(target.source);
if (!buttonMatch) {
  throw new Error("無法辨識正式站台股大盤分頁按鈕。");
}

const [, factory, viewState, setView] = buttonMatch;
const usButton =
  `(0,${factory}.jsx)(\`button\`,{"aria-selected":${viewState}===\`usMarket\`,` +
  `className:${viewState}===\`usMarket\`?\`is-active\`:\`\`,` +
  `onClick:()=>${setView}(\`usMarket\`),role:\`tab\`,type:\`button\`,` +
  `children:\`美股大盤\`})`;

let patched =
  target.source.slice(0, buttonMatch.index + buttonMatch[0].length) +
  "," +
  usButton +
  target.source.slice(buttonMatch.index + buttonMatch[0].length);

const taiexStart = patched.indexOf(
  `${viewState}===\`taiex\`&&(0,${factory}.jsxs)(\`div\`,`,
);
if (taiexStart === -1) {
  throw new Error("無法辨識正式站台股大盤內容區塊。");
}

const electionMarker = `]}),${viewState}===\`electionTrend\``;
const electionIndex = patched.indexOf(electionMarker, taiexStart);
if (electionIndex === -1) {
  throw new Error("無法辨識台股大盤與選前走勢的區塊邊界。");
}

const taiexBlock = patched.slice(taiexStart, electionIndex);
const chartMatch = new RegExp(
  `\\(0,${factory}\\.jsx\\)\\(([A-Za-z_$][\\w$]*),\\{comparisonCode:\\\`VIXTWN\\\``,
).exec(taiexBlock);
if (!chartMatch) {
  throw new Error("無法辨識正式站市場 K 線元件。");
}
const chartComponent = chartMatch[1];

function instrument(code, name, description) {
  return (
    `(0,${factory}.jsxs)(\`section\`,{className:\`detail-header taiex-header\`,` +
    `"aria-label":\`${code} ${name}\`,children:[` +
    `(0,${factory}.jsxs)(\`div\`,{children:[` +
    `(0,${factory}.jsx)(\`p\`,{className:\`eyebrow\`,children:\`${code} · 美元\`}),` +
    `(0,${factory}.jsx)(\`h2\`,{children:\`${name}\`}),` +
    `(0,${factory}.jsx)(\`p\`,{children:\`${description}\`})]}),` +
    `(0,${factory}.jsx)(${chartComponent},{etfCode:\`${code}\`,etfName:\`${name}\`})]})`
  );
}

const usMarket =
  `${viewState}===\`usMarket\`&&(0,${factory}.jsxs)(\`div\`,` +
  `{className:\`taiex-workspace\`,children:[` +
  `(0,${factory}.jsx)(\`section\`,{className:\`detail-header taiex-header\`,` +
  `"aria-label":\`美股大盤摘要\`,children:(0,${factory}.jsxs)(\`div\`,{children:[` +
  `(0,${factory}.jsx)(\`p\`,{className:\`eyebrow\`,children:\`美國市場\`}),` +
  `(0,${factory}.jsx)(\`h2\`,{children:\`美股大盤\`}),` +
  `(0,${factory}.jsx)(\`p\`,{children:\`SPY、QQQ、SMH 歷史日 K、成交量與可見範圍成交量分佈\`})]})}),` +
  instrument("SPY", "SPDR S&P 500 ETF Trust", "追蹤 S&P 500 指數") +
  "," +
  instrument("QQQ", "Invesco QQQ Trust", "追蹤 Nasdaq-100 指數") +
  "," +
  instrument("SMH", "VanEck Semiconductor ETF", "追蹤美國上市半導體產業") +
  `]}),`;

patched =
  patched.slice(0, electionIndex + 4) +
  usMarket +
  patched.slice(electionIndex + 4);

for (const required of ["美股大盤", "etfCode:`SPY`", "etfCode:`QQQ`", "etfCode:`SMH`"]) {
  if (!patched.includes(required)) {
    throw new Error(`更新後正式站資產缺少 ${required}。`);
  }
}

const digest = createHash("sha256").update(patched).digest("hex").slice(0, 8);
const oldName = basename(target.path);
const newName = oldName.replace(/index-[^.]+\.js$/, `index-${digest}.js`);
const newPath = join(dirname(target.path), newName);

writeFileSync(newPath, patched);
if (newPath !== target.path) unlinkSync(target.path);

for (const htmlName of readdirSync(siteDir).filter((name) =>
  name.endsWith(".html"),
)) {
  const htmlPath = join(siteDir, htmlName);
  const html = readFileSync(htmlPath, "utf8");
  if (html.includes(oldName)) {
    writeFileSync(htmlPath, html.replaceAll(oldName, newName));
  }
}

console.log(
  JSON.stringify({
    unchanged: false,
    oldAsset: oldName,
    newAsset: newName,
    instruments: ["SPY", "QQQ", "SMH"],
  }),
);
