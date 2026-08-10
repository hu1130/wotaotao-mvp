import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

const openApiPath = fileURLToPath(
  new URL("../../../packages/contracts/platform/openapi.json", import.meta.url),
);
const fixturesPath = fileURLToPath(
  new URL(
    "../../../packages/contracts/platform/fixtures/http/index.json",
    import.meta.url,
  ),
);

export const openApi = JSON.parse(readFileSync(openApiPath, "utf8"));
export const fixtures = JSON.parse(readFileSync(fixturesPath, "utf8"));

const HTTP_METHODS = new Set(["get", "post", "put", "patch", "delete"]);

function compilePath(pathTemplate) {
  const parameterNames = [];
  const escaped = pathTemplate
    .split(/(\{[^}]+\})/g)
    .map((part) => {
      const match = /^\{([^}]+)\}$/.exec(part);
      if (match) {
        parameterNames.push(match[1]);
        return "([^/]+)";
      }
      return part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    })
    .join("");
  return { parameterNames, regexp: new RegExp(`^${escaped}$`) };
}

export const operations = Object.entries(openApi.paths).flatMap(
  ([path, pathItem]) =>
    Object.entries(pathItem)
      .filter(([method]) => HTTP_METHODS.has(method))
      .map(([method, operation]) => ({
        ...compilePath(path),
        auth: operation["x-auth"] ?? "ACTOR",
        idempotency:
          operation["x-idempotency"] ??
          (operation["x-idempotency-key"]
            ? { required: true, keyFormat: operation["x-idempotency-key"] }
            : { required: false }),
        method: method.toUpperCase(),
        operation,
        operationId: operation.operationId,
        path,
      })),
);

export function matchOperation(method, pathname) {
  for (const candidate of operations) {
    if (candidate.method !== method) continue;
    const match = candidate.regexp.exec(pathname);
    if (!match) continue;
    return {
      ...candidate,
      params: Object.fromEntries(
        candidate.parameterNames.map((name, index) => [
          name,
          decodeURIComponent(match[index + 1]),
        ]),
      ),
    };
  }
  return null;
}

function rewriteRefs(value) {
  if (Array.isArray(value)) return value.map(rewriteRefs);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value).map(([key, child]) => [
      key,
      key === "$ref" && typeof child === "string"
        ? child.replace("#/components/schemas/", "#/$defs/")
        : rewriteRefs(child),
    ]),
  );
}

const ajv = new Ajv2020({ allErrors: true, coerceTypes: true, strict: false });
addFormats(ajv);

export function compileSchema(schema) {
  if (!schema) return null;
  return ajv.compile({
    $defs: rewriteRefs(openApi.components?.schemas ?? {}),
    ...rewriteRefs(schema),
  });
}

export function requestValidator(operation) {
  return compileSchema(
    operation.operation.requestBody?.content?.["application/json"]?.schema,
  );
}

export function parameterValidators(operation) {
  return (operation.operation.parameters ?? []).map((parameter) => ({
    isArray: parameter.schema?.type === "array",
    location: parameter.in,
    name: parameter.name,
    required: parameter.required === true,
    validate: compileSchema(parameter.schema),
  }));
}

export function responseValidator(operation, status) {
  return compileSchema(
    operation.operation.responses?.[String(status)]?.content?.[
      "application/json"
    ]?.schema,
  );
}

export function fixtureFor(operationId) {
  return fixtures.operations?.[operationId] ?? null;
}
