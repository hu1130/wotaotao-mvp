import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  Channel,
  ContentStatus,
  InquiryStatus,
  PublicationStatus,
  Role,
} from "../packages/contracts/src/runtime.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const contract = JSON.parse(
  await readFile(path.join(root, "packages", "contracts", "openapi.json"), "utf8"),
);

const requiredOperations = [
  ["post", "/products"],
  ["get", "/products/{id}"],
  ["post", "/contents/generate"],
  ["put", "/contents/{id}"],
  ["post", "/contents/{id}/submit-review"],
  ["get", "/reviews/pending"],
  ["post", "/reviews/{id}/approve"],
  ["post", "/reviews/{id}/reject"],
  ["get", "/authorized-accounts"],
  ["post", "/publications"],
  ["post", "/publications/callback"],
  ["post", "/publications/{id}/retry"],
  ["get", "/feed"],
  ["get", "/storefront/products/{id}"],
  ["post", "/inquiries"],
  ["get", "/merchant/inquiries"],
  ["patch", "/inquiries/{id}/status"],
];

for (const [method, route] of requiredOperations) {
  const operation = contract.paths?.[route]?.[method];
  assert.ok(operation, `Missing ${method.toUpperCase()} ${route}`);
  assert.ok(operation.summary, `Missing summary for ${method.toUpperCase()} ${route}`);
  assert.ok(
    Array.isArray(operation["x-roles"]) && operation["x-roles"].length > 0,
    `Missing x-roles for ${method.toUpperCase()} ${route}`,
  );
}

const expectedEnums = new Map([
  ["ContentStatus", Object.values(ContentStatus)],
  ["PublicationStatus", Object.values(PublicationStatus)],
  ["InquiryStatus", Object.values(InquiryStatus)],
  ["Channel", Object.values(Channel)],
  ["Role", Object.values(Role)],
]);

for (const [name, expected] of expectedEnums) {
  assert.deepEqual(
    contract.components.schemas[name].enum,
    expected,
    `${name} differs between OpenAPI and runtime constants`,
  );
}

const camelCase = /^[a-z][A-Za-z0-9]*$/;
for (const [schemaName, schema] of Object.entries(contract.components.schemas)) {
  for (const propertyName of Object.keys(schema.properties ?? {})) {
    assert.match(propertyName, camelCase, `${schemaName}.${propertyName} is not camelCase`);
  }
}

for (const responseName of [
  "ProductResponse",
  "ContentResponse",
  "PublicationResponse",
  "InquiryResponse",
  "ErrorResponse",
]) {
  const required = contract.components.schemas[responseName].required;
  assert.ok(required.includes("requestId"), `${responseName} must include requestId`);
}

console.log(
  `Contract OK: ${requiredOperations.length} operations, ${Object.keys(contract.components.schemas).length} schemas.`,
);
