import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

const forwarded = process.argv.slice(2);
const baseRefIndex = forwarded.indexOf("--base-ref");
if (
  baseRefIndex !== -1 &&
  (!forwarded[baseRefIndex + 1] || forwarded[baseRefIndex + 1].startsWith("--"))
) {
  throw new Error("--base-ref requires a non-empty trusted git ref");
}
const baselineArgs =
  baseRefIndex === -1
    ? []
    : ["--base-ref", forwarded[baseRefIndex + 1]].filter(Boolean);

function run(script, args = []) {
  const result = spawnSync(process.execPath, [resolve(script), ...args], {
    stdio: "inherit",
  });
  if (result.status !== 0) process.exit(result.status ?? 1);
}

run("scripts/test-contract-breaking.mjs");
run("scripts/test-baseline-integrity.mjs");
run("scripts/test-gate-arguments.mjs");
run("scripts/check-baseline-integrity.mjs", baselineArgs);
run("scripts/check-contract-breaking.mjs", forwarded);
