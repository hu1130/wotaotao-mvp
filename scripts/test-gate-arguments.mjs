import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

for (const script of [
  "scripts/check-contract-breaking.mjs",
  "scripts/check-baseline-integrity.mjs",
  "scripts/run-contract-gates.mjs",
]) {
  const result = spawnSync(
    process.execPath,
    [resolve(script), "--base-ref", ""],
    { encoding: "utf8" },
  );
  const output = `${result.stdout ?? ""}\n${result.stderr ?? ""}`;
  if (
    result.status === 0 ||
    !output.includes("--base-ref requires a non-empty trusted git ref")
  ) {
    throw new Error(
      `${script} accepted an explicitly empty trusted base ref.\n${output}`,
    );
  }
}

console.log("Contract gates fail closed when --base-ref is explicitly empty.");
