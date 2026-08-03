import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const openApiPath = fileURLToPath(
  new URL("../../../packages/contracts/openapi.json", import.meta.url),
);

export const openApi = JSON.parse(readFileSync(openApiPath, "utf8"));

function compilePath(pathTemplate) {
  const parameterNames = [];
  const pattern = pathTemplate.replace(/\{([^}]+)\}/g, (_match, name) => {
    parameterNames.push(name);
    return "([^/]+)";
  });

  return {
    parameterNames,
    regexp: new RegExp(`^${pattern}$`),
  };
}

export const mockOperations = Object.entries(openApi.paths).flatMap(
  ([path, pathItem]) =>
    Object.entries(pathItem).map(([method, operation]) => ({
      method: method.toUpperCase(),
      path,
      operationId: operation.operationId,
      auth: operation["x-auth"],
      roles: operation["x-roles"] ?? [],
      ...compilePath(path),
    })),
);

export function matchOperation(method, pathname) {
  for (const operation of mockOperations) {
    if (operation.method !== method) continue;
    const match = operation.regexp.exec(pathname);
    if (!match) continue;

    const params = Object.fromEntries(
      operation.parameterNames.map((name, index) => [
        name,
        decodeURIComponent(match[index + 1]),
      ]),
    );
    return { ...operation, params };
  }
  return null;
}

export function enumValues(schemaName) {
  const values = openApi.components?.schemas?.[schemaName]?.enum;
  if (!Array.isArray(values)) {
    throw new Error(`OpenAPI schema ${schemaName} must define an enum`);
  }
  return values;
}

export function transitionMap(schemaName) {
  const transitions = openApi.components?.schemas?.[schemaName]?.[
    "x-transitions"
  ];
  if (!transitions || typeof transitions !== "object") {
    throw new Error(`OpenAPI schema ${schemaName} must define x-transitions`);
  }
  return transitions;
}

export function idPrefix(schemaName) {
  const prefix = openApi.components?.schemas?.[schemaName]?.["x-prefix"];
  if (typeof prefix !== "string") {
    throw new Error(`OpenAPI schema ${schemaName} must define x-prefix`);
  }
  return prefix;
}
