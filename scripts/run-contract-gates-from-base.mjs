import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

const index = process.argv.indexOf("--base-ref");
const baseRef = index === -1 ? null : process.argv[index + 1];
if (!baseRef) {
  throw new Error("Usage: node scripts/run-contract-gates-from-base.mjs --base-ref <trusted-ref>");
}

const commit = spawnSync("git", ["rev-parse", "--verify", `${baseRef}^{commit}`], {
  stdio: "ignore",
});
if (commit.status !== 0) throw new Error(`Trusted base ref does not exist: ${baseRef}`);

function existsAtRef(path) {
  return spawnSync("git", ["cat-file", "-e", `${baseRef}:${path}`], {
    stdio: "ignore",
  }).status === 0;
}

const hasOpenApi = existsAtRef("packages/contracts/platform/openapi.json");
const hasAsyncApi = existsAtRef("packages/contracts/platform/asyncapi.json");
const hasRegistry = existsAtRef("packages/contracts/platform/registry.json");
if (new Set([hasOpenApi, hasAsyncApi, hasRegistry]).size !== 1) {
  throw new Error(
    `Trusted base ${baseRef} contains only part of the OpenAPI/AsyncAPI/registry contract family; refusing a partial bootstrap.`,
  );
}

const args = ["--base-ref", baseRef];
if (!hasOpenApi) {
  args.push("--allow-bootstrap");
  console.log(
    `One-time contract bootstrap: ${baseRef} contains no OpenAPI, AsyncAPI or registry.`,
  );
}
const result = spawnSync(
  process.execPath,
  [resolve("scripts/run-contract-gates.mjs"), ...args],
  { stdio: "inherit" },
);
process.exit(result.status ?? 1);
