const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const sourceRoot = path.join(root, "apps", "desktop", "src");

// Byte-shaped sequences created when UTF-8 is accidentally decoded as Latin-1.
// Escapes keep this check independent from the active Windows terminal code page.
const invalid = /(?:[\u00c2\u00c3][\u0080-\u00bf]|\u00e2\u20ac|\u00f0[\u0178\u009f]|\ufffd)/;
const failures = [];
const referencedKeys = new Set();

function walk(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      walk(file);
      continue;
    }
    if (!/\.(?:ts|tsx|json)$/.test(entry.name)) continue;
    const source = fs.readFileSync(file, "utf8");
    if (invalid.test(source)) failures.push(path.relative(root, file));
    if (/\.tsx?$/.test(entry.name) && entry.name !== "i18n.tsx") {
      for (const match of source.matchAll(/\bt\(\s*["'`]([^"'`$]+)["'`]/g)) referencedKeys.add(match[1]);
    }
  }
}

walk(sourceRoot);
const catalogPath = path.join(sourceRoot, "i18n.tsx");
const catalog = fs.readFileSync(catalogPath, "utf8");
const missingKeys = [...referencedKeys].filter((key) => !catalog.includes(`"${key}"`)).sort();
if (missingKeys.length) {
  console.error(`Missing interface keys:\n${missingKeys.join("\n")}`);
  process.exit(1);
}
if (!/id:\s*"ar"[\s\S]{0,120}dir:\s*"rtl"/.test(catalog)) {
  console.error("Arabic locale must explicitly use RTL direction");
  process.exit(1);
}
if (failures.length) {
  console.error(`Encoding corruption found:\n${failures.join("\n")}`);
  process.exit(1);
}
console.log(`Interface encoding, key coverage and RTL checks passed (${referencedKeys.size} static keys)`);
