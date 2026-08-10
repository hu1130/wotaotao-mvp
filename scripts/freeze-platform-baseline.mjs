import { createHash } from "node:crypto";
import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

const version = process.argv[2];
if (!version || !/^\d+\.\d+\.\d+$/.test(version)) {
  throw new Error("Usage: node scripts/freeze-platform-baseline.mjs <major.minor.patch>");
}

const root = resolve(import.meta.dirname, "..");
const sourceRoot = resolve(root, "packages/contracts/platform");
const targetRoot = resolve(sourceRoot, "baseline", version);
const artifacts = [
  "openapi.json",
  "asyncapi.json",
  "registry.json",
  "provider-consumer-matrix.json",
];

const openApi = JSON.parse(await readFile(resolve(sourceRoot, "openapi.json"), "utf8"));
const asyncApi = JSON.parse(await readFile(resolve(sourceRoot, "asyncapi.json"), "utf8"));
const registry = JSON.parse(await readFile(resolve(sourceRoot, "registry.json"), "utf8"));
for (const [artifact, artifactVersion] of [
  ["openapi.json", openApi.info?.version],
  ["asyncapi.json", asyncApi.info?.version],
  ["registry.json", registry.contractVersion],
]) {
  if (artifactVersion !== version) {
    throw new Error(
      `${artifact} declares version ${artifactVersion}; refusing to freeze it as ${version}.`,
    );
  }
}

if (existsSync(targetRoot)) {
  throw new Error(
    `Baseline ${version} already exists and is immutable. Publish a new version instead of overwriting it.`,
  );
}

await mkdir(targetRoot, { recursive: true });
const hashes = {};
for (const artifact of artifacts) {
  const source = resolve(sourceRoot, artifact);
  const target = resolve(targetRoot, artifact);
  const content = await readFile(source);
  hashes[artifact] = createHash("sha256").update(content).digest("hex");
  await copyFile(source, target);
}

await writeFile(
  resolve(targetRoot, "manifest.json"),
  `${JSON.stringify({ version, immutable: true, sha256: hashes }, null, 2)}\n`,
  "utf8",
);
console.log(`Frozen full-platform contract baseline ${version}.`);
