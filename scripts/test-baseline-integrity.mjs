import { spawnSync } from "node:child_process";
import {
  copyFileSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const checker = resolve("scripts/check-baseline-integrity.mjs");
const source = resolve("packages/contracts/platform/baseline");
const temporaryRoot = mkdtempSync(join(tmpdir(), "wotao-baseline-integrity-"));
const baseline = join(temporaryRoot, "baseline");

try {
  const version = readdirSync(source).find((name) => /^\d+\.\d+\.\d+$/.test(name));
  if (!version) throw new Error("No semantic-version baseline exists for the self-test.");
  const sourceVersion = join(source, version);
  const targetVersion = join(baseline, version);
  mkdirSync(targetVersion, { recursive: true });
  for (const file of readdirSync(sourceVersion)) {
    copyFileSync(join(sourceVersion, file), join(targetVersion, file));
  }
  const target = join(baseline, version, "openapi.json");
  const document = JSON.parse(readFileSync(target, "utf8"));
  document.info.title = "Tampered frozen baseline";
  writeFileSync(target, `${JSON.stringify(document, null, 2)}\n`, "utf8");

  const result = spawnSync(
    process.execPath,
    [checker, "--baseline-root", baseline],
    { encoding: "utf8" },
  );
  const output = `${result.stdout ?? ""}\n${result.stderr ?? ""}`;
  if (result.status === 0 || !output.includes("SHA-256 does not match")) {
    throw new Error(`Baseline integrity self-test did not reject tampering.\n${output}`);
  }
  console.log("Baseline integrity gate rejected a tampered frozen artifact.");
} finally {
  rmSync(temporaryRoot, { recursive: true, force: true });
}
