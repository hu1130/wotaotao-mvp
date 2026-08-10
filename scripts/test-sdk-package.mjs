import { execFileSync } from "node:child_process";
import {
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const pnpmCli = process.env.npm_execpath;
if (!pnpmCli) {
  throw new Error("npm_execpath is required to run the SDK package smoke test");
}

const root = resolve(import.meta.dirname, "..");
const sdkDirectory = resolve(root, "packages/platform-sdk");
const temporaryDirectory = mkdtempSync(join(tmpdir(), "wotao-sdk-package-"));
const require = createRequire(import.meta.url);
const tsc = require.resolve("typescript/bin/tsc");

function pnpm(args, cwd = root) {
  execFileSync(process.execPath, [pnpmCli, ...args], {
    cwd,
    stdio: "inherit",
  });
}

try {
  pnpm(["pack", "--pack-destination", temporaryDirectory], sdkDirectory);
  const archiveName = readdirSync(temporaryDirectory).find((name) =>
    name.endsWith(".tgz"),
  );
  if (!archiveName) throw new Error("pnpm pack did not create an SDK archive");
  const archive = resolve(temporaryDirectory, archiveName);

  writeFileSync(
    resolve(temporaryDirectory, "package.json"),
    `${JSON.stringify(
      { name: "sdk-package-consumer", private: true, type: "module" },
      null,
      2,
    )}\n`,
    "utf8",
  );
  pnpm(["add", "--offline", "--ignore-scripts", archive], temporaryDirectory);

  writeFileSync(
    resolve(temporaryDirectory, "runtime.mjs"),
    `import { createPlatformClient } from "@wotao/platform-sdk";\n` +
      `import * as schemaModule from "@wotao/platform-sdk/schema";\n` +
      `if (typeof createPlatformClient !== "function") throw new Error("missing root export");\n` +
      `if (!schemaModule || typeof schemaModule !== "object") throw new Error("missing schema export");\n` +
      `const client = createPlatformClient({ baseUrl: "http://contracts.test" });\n` +
      `if (typeof client.GET !== "function") throw new Error("invalid packed client");\n`,
    "utf8",
  );
  execFileSync(process.execPath, [resolve(temporaryDirectory, "runtime.mjs")], {
    cwd: temporaryDirectory,
    stdio: "inherit",
  });

  writeFileSync(
    resolve(temporaryDirectory, "consumer.mts"),
    `import { createPlatformClient } from "@wotao/platform-sdk";\n` +
      `import type { paths } from "@wotao/platform-sdk/schema";\n` +
      `type ContextResponse = paths["/api/v1/me/context"]["get"]["responses"][200]["content"]["application/json"];\n` +
      `const client = createPlatformClient({ baseUrl: "http://contracts.test" });\n` +
      `void client.GET("/api/v1/me/context");\n` +
      `const response: ContextResponse | undefined = undefined;\n` +
      `void response;\n`,
    "utf8",
  );
  writeFileSync(
    resolve(temporaryDirectory, "tsconfig.json"),
    `${JSON.stringify(
      {
        compilerOptions: {
          lib: ["ES2022", "DOM"],
          module: "NodeNext",
          moduleResolution: "NodeNext",
          noEmit: true,
          skipLibCheck: true,
          strict: true,
          target: "ES2022",
        },
        files: ["consumer.mts"],
      },
      null,
      2,
    )}\n`,
    "utf8",
  );
  execFileSync(process.execPath, [tsc, "-p", "tsconfig.json"], {
    cwd: temporaryDirectory,
    stdio: "inherit",
  });

  const installedPackage = JSON.parse(
    readFileSync(
      resolve(
        temporaryDirectory,
        "node_modules/@wotao/platform-sdk/package.json",
      ),
      "utf8",
    ),
  );
  const contract = JSON.parse(
    readFileSync(resolve(root, "packages/contracts/platform/openapi.json"), "utf8"),
  );
  if (installedPackage.version !== contract.info.version) {
    throw new Error(
      `Packed SDK version ${installedPackage.version} does not match contract ${contract.info.version}`,
    );
  }
  console.log(
    "Packed SDK root/schema imports and TypeScript consumer compilation passed.",
  );
} finally {
  rmSync(temporaryDirectory, { recursive: true, force: true });
}
