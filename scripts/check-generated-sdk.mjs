import { execFileSync } from "node:child_process";
import {
  mkdtempSync,
  readFileSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const sdkDirectory = resolve("packages/platform-sdk");
const specification = "../contracts/platform/openapi.json";
const generated = resolve("packages/platform-sdk/src/generated/schema.ts");
const generator = resolve(
  "packages/platform-sdk/node_modules/openapi-typescript/bin/cli.js",
);
const temporaryDirectory = mkdtempSync(join(tmpdir(), "wotao-sdk-check-"));
const temporaryOutput = join(temporaryDirectory, "schema.ts");
try {
  execFileSync(
    process.execPath,
    [generator, specification, "-o", temporaryOutput],
    { cwd: sdkDirectory, stdio: "inherit" },
  );
  const expected = readFileSync(temporaryOutput, "utf8").replaceAll("\r\n", "\n");
  const actual = readFileSync(generated, "utf8").replaceAll("\r\n", "\n");
  if (expected !== actual) {
    console.error(
      "Generated SDK types are stale. Run `pnpm sdk:generate` and commit the result.",
    );
    process.exitCode = 1;
  } else {
    console.log("Generated SDK types match the full-platform OpenAPI contract.");
  }
} finally {
  rmSync(temporaryDirectory, { recursive: true, force: true });
}
