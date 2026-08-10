import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { DiagnosticSeverity, fromFile, Parser } from "@asyncapi/parser";
import Ajv2020, { type ErrorObject } from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import { describe, expect, it } from "vitest";
import {
  PLATFORM_ERROR_REGISTRY,
  PLATFORM_HTTP_CONTRACTS,
  validatePlatformHttpContracts,
} from "../src/platform/http-contracts.js";
import {
  PLATFORM_EVENT_CONTRACTS,
  validatePlatformEventContracts,
} from "../src/platform/event-contracts.js";

type JsonObject = Record<string, unknown>;

function readJson(path: string): JsonObject {
  return JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8")) as JsonObject;
}

function validationMessage(errors: ErrorObject[] | null | undefined): string {
  return errors?.map((error) => `${error.instancePath || "/"} ${error.message}`).join("; ") ?? "";
}

function operationAt(openApi: JsonObject, method: string, path: string): JsonObject {
  const paths = openApi.paths as Record<string, Record<string, JsonObject>>;
  return paths[path]?.[method.toLowerCase()] ?? {};
}

describe("full-platform provider contracts", () => {
  it("freezes internally consistent HTTP and event registries", () => {
    expect(validatePlatformHttpContracts()).toEqual([]);
    expect(validatePlatformEventContracts()).toEqual([]);
    expect(PLATFORM_HTTP_CONTRACTS.length).toBeGreaterThanOrEqual(40);
    expect(PLATFORM_EVENT_CONTRACTS.length).toBeGreaterThanOrEqual(20);
    expect(new Set(PLATFORM_HTTP_CONTRACTS.map((item) => item.operationId)).size)
      .toBe(PLATFORM_HTTP_CONTRACTS.length);
    expect(new Set(PLATFORM_EVENT_CONTRACTS.map((item) => item.eventType)).size)
      .toBe(PLATFORM_EVENT_CONTRACTS.length);
  });

  it("validates every fixed HTTP request, success response and failure response", () => {
    for (const contract of PLATFORM_HTTP_CONTRACTS) {
      const ajv = new Ajv2020({ allErrors: true, strict: false });
      addFormats(ajv);
      const validateRequest = ajv.compile(contract.request.schema);
      const validateSuccess = ajv.compile(contract.response.successSchema);
      const validateFailure = ajv.compile(contract.response.errorSchema);

      expect(
        validateRequest(contract.examples.success.request),
        `${contract.operationId} request: ${validationMessage(validateRequest.errors)}`,
      ).toBe(true);
      expect(
        validateSuccess(contract.examples.success.response),
        `${contract.operationId} response: ${validationMessage(validateSuccess.errors)}`,
      ).toBe(true);
      expect(
        validateFailure(contract.examples.failure.response),
        `${contract.operationId} failure: ${validationMessage(validateFailure.errors)}`,
      ).toBe(true);
    }
  });

  it("keeps generated OpenAPI operations and deterministic fixtures aligned", () => {
    const openApi = readJson("../platform/openapi.json");
    const fixtures = readJson("../platform/fixtures/http/index.json");
    const fixtureOperations = fixtures.operations as Record<string, JsonObject>;

    expect(openApi.openapi).toBe("3.1.0");
    for (const contract of PLATFORM_HTTP_CONTRACTS) {
      const operation = operationAt(openApi, contract.method, contract.path);
      expect(operation.operationId).toBe(contract.operationId);
      expect(operation["x-owner"]).toBe(contract.owner);
      expect(operation["x-consumers"]).toEqual(contract.consumer);
      expect(fixtureOperations[contract.operationId]?.status)
        .toBe(contract.response.successStatus);
      expect(fixtureOperations[contract.operationId]?.response)
        .toEqual(contract.examples.success.response);

      if (contract.idempotency.source === "HEADER") {
        const parameters = operation.parameters as JsonObject[];
        expect(parameters.some((parameter) =>
          parameter.in === "header" &&
          String(parameter.name).toLowerCase() === "idempotency-key" &&
          parameter.required === true,
        )).toBe(true);
      }
    }
  });

  it("validates every event fixture against its standalone Draft 2020-12 schema", () => {
    for (const contract of PLATFORM_EVENT_CONTRACTS) {
      const name = `${contract.eventType}.v${contract.schemaVersion}`;
      const schema = readJson(`../platform/events/${name}.schema.json`);
      const fixture = readJson(`../platform/fixtures/events/${name}.json`);
      const ajv = new Ajv2020({ allErrors: true, strict: false });
      addFormats(ajv);
      const validate = ajv.compile(schema);
      expect(
        validate(fixture),
        `${contract.eventType}: ${validationMessage(validate.errors)}`,
      ).toBe(true);
      expect(fixture).toEqual(contract.example);
    }
  });

  it("is accepted by the official AsyncAPI parser", async () => {
    const parser = new Parser();
    const source = fileURLToPath(new URL("../platform/asyncapi.json", import.meta.url));
    const result = await fromFile(parser, source).parse();
    const errors = result.diagnostics.filter(
      (diagnostic) => diagnostic.severity === DiagnosticSeverity.Error,
    );
    expect(errors, JSON.stringify(errors, null, 2)).toEqual([]);
    expect(result.document).toBeDefined();
  });

  it("only publishes registered error codes", () => {
    const registered = new Set(Object.keys(PLATFORM_ERROR_REGISTRY));
    for (const contract of PLATFORM_HTTP_CONTRACTS) {
      for (const error of contract.errors) expect(registered.has(error.code)).toBe(true);
    }
  });
});
