import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import {
  existsSync,
  readFileSync,
  readdirSync,
  statSync,
} from "node:fs";
import { basename, relative, resolve, sep } from "node:path";

const DEFAULT_ROOT = resolve("packages/contracts/platform/baseline");

function parseArgs(argv) {
  const result = { baseRef: null, baselineRoot: DEFAULT_ROOT };
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === "--base-ref") {
      const next = argv[++index];
      if (!next || next.startsWith("--")) {
        throw new Error("--base-ref requires a non-empty trusted git ref");
      }
      result.baseRef = next;
    }
    else if (argv[index] === "--baseline-root") {
      result.baselineRoot = resolve(argv[++index] ?? "");
    } else throw new Error(`Unknown argument: ${argv[index]}`);
  }
  return result;
}

function sha256(content) {
  return createHash("sha256").update(content).digest("hex");
}

function allFiles(root) {
  if (!existsSync(root)) return [];
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(root, entry.name);
    return entry.isDirectory() ? allFiles(path) : [path];
  });
}

function verifyManifests(root) {
  if (!existsSync(root)) throw new Error(`Baseline root is missing: ${root}`);
  const versions = readdirSync(root, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && /^\d+\.\d+\.\d+$/.test(entry.name));
  if (versions.length === 0) throw new Error("No frozen contract baseline exists.");

  const errors = [];
  for (const version of versions) {
    const directory = resolve(root, version.name);
    const manifestPath = resolve(directory, "manifest.json");
    if (!existsSync(manifestPath)) {
      errors.push(`${version.name}: manifest.json is missing`);
      continue;
    }
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    if (manifest.version !== version.name) {
      errors.push(`${version.name}: manifest version is ${manifest.version}`);
    }
    if (manifest.immutable !== true) {
      errors.push(`${version.name}: immutable must be true`);
    }
    const recorded = manifest.sha256 ?? {};
    const actualArtifacts = allFiles(directory)
      .filter((path) => basename(path) !== "manifest.json")
      .map((path) => relative(directory, path).split(sep).join("/"))
      .sort();
    const recordedArtifacts = Object.keys(recorded).sort();
    if (JSON.stringify(actualArtifacts) !== JSON.stringify(recordedArtifacts)) {
      errors.push(`${version.name}: manifest artifact list differs from the directory`);
    }
    for (const artifact of recordedArtifacts) {
      const path = resolve(directory, artifact);
      if (!existsSync(path) || !statSync(path).isFile()) {
        errors.push(`${version.name}/${artifact}: recorded artifact is missing`);
        continue;
      }
      const actualHash = sha256(readFileSync(path));
      if (actualHash !== recorded[artifact]) {
        errors.push(`${version.name}/${artifact}: SHA-256 does not match manifest`);
      }
    }
    for (const [artifact, selector] of [
      ["openapi.json", (document) => document.info?.version],
      ["asyncapi.json", (document) => document.info?.version],
      ["registry.json", (document) => document.contractVersion],
    ]) {
      const path = resolve(directory, artifact);
      if (!existsSync(path)) continue;
      try {
        const declaredVersion = selector(JSON.parse(readFileSync(path, "utf8")));
        if (declaredVersion !== version.name) {
          errors.push(
            `${version.name}/${artifact}: declares contract version ${declaredVersion}`,
          );
        }
      } catch (error) {
        errors.push(`${version.name}/${artifact}: invalid JSON (${error.message})`);
      }
    }
  }
  return errors;
}

function filesAtRef(ref) {
  const output = execFileSync(
    "git",
    [
      "ls-tree",
      "-r",
      "--name-only",
      ref,
      "--",
      "packages/contracts/platform/baseline",
    ],
    { encoding: "utf8" },
  );
  return output.split(/\r?\n/).filter(Boolean);
}

function verifyBaseImmutability(ref, root) {
  if (root !== DEFAULT_ROOT) {
    throw new Error("--base-ref cannot be combined with a custom --baseline-root");
  }
  const errors = [];
  const basePaths = filesAtRef(ref);
  const baseSet = new Set(basePaths);
  const prefix = "packages/contracts/platform/baseline/";
  const baseVersions = new Set(
    basePaths.map((path) => path.slice(prefix.length).split("/")[0]),
  );

  for (const path of basePaths) {
    const currentPath = resolve(path);
    if (!existsSync(currentPath)) {
      errors.push(`${path}: published baseline file was removed`);
      continue;
    }
    const previous = execFileSync("git", ["show", `${ref}:${path}`]);
    if (sha256(previous) !== sha256(readFileSync(currentPath))) {
      errors.push(`${path}: published baseline file was modified`);
    }
  }

  for (const currentPath of allFiles(root)) {
    const repositoryPath = relative(process.cwd(), currentPath).split(sep).join("/");
    const version = repositoryPath.slice(prefix.length).split("/")[0];
    if (baseVersions.has(version) && !baseSet.has(repositoryPath)) {
      errors.push(`${repositoryPath}: file was added to published baseline ${version}`);
    }
  }
  return errors;
}

const args = parseArgs(process.argv.slice(2));
const errors = verifyManifests(args.baselineRoot);
const priorBaselineCount = args.baseRef ? filesAtRef(args.baseRef).length : 0;
if (args.baseRef) errors.push(...verifyBaseImmutability(args.baseRef, args.baselineRoot));

if (errors.length > 0) {
  console.error("Frozen baseline integrity check failed:");
  for (const error of errors) console.error(`- ${error}`);
  process.exit(1);
}
console.log(
  args.baseRef
    ? priorBaselineCount > 0
      ? `Frozen baselines match their manifests and remain byte-identical to ${args.baseRef}.`
      : `No baseline exists at ${args.baseRef}; local bootstrap manifests and hashes are valid.`
    : "Frozen baseline manifests and SHA-256 hashes are valid.",
);
