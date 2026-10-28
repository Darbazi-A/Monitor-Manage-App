// Every t("…") / tf("…") in the dashboard has its Georgian, and the scripts parse.   node test/words_test.cjs
const fs = require("fs");
const vm = require("vm");
const path = require("path");
const root = path.join(__dirname, "..", "public");
const ctx = { localStorage: { getItem: () => null, setItem() {} }, document: { documentElement: {} } };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(root, "i18n.js"), "utf8") + ";this.KA = KA;", ctx);
const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
const keys = new Set();
const literals = text => [...text.matchAll(/"((?:[^"\\]|\\.)*)"/g)].map(m => JSON.parse('"' + m[1] + '"'));
for (const match of source.matchAll(/\btf?\(\s*"((?:[^"\\]|\\.)*)"/g)) keys.add(JSON.parse('"' + match[1] + '"'));
// t(a ? "x" : "y"), and the message templates (shown through t())
for (const match of source.matchAll(/\btf?\(([^()`]*\?[^()`]*)\)/g)) literals(match[1]).forEach(k => keys.add(k));
for (const match of source.matchAll(/const MESSAGES = \[([^\]]*)\]/g)) literals(match[1]).forEach(k => keys.add(k));
const missing = [...keys].filter(key => !(key in ctx.KA));
for (const file of ["app.js", "i18n.js"]) new vm.Script(fs.readFileSync(path.join(root, file), "utf8"), { filename: file });
console.log(`${keys.size} words; ${missing.length ? "missing: " + JSON.stringify(missing, null, 1) : "all in Georgian"}; the scripts parse`);
process.exit(missing.length ? 1 : 0);
