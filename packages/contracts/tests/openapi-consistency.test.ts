import { describe, expect, it } from "vitest";
import openApi from "../openapi.json";
import {
  BUSINESS_ID_PREFIXES,
  CHANNELS,
  CONTENT_GENERATION_STATUSES,
  CONTENT_GENERATION_STATUS_TRANSITIONS,
  CONTENT_STATUSES,
  CONTENT_STATUS_TRANSITIONS,
  ERROR_CODES,
  INQUIRY_STATUSES,
  INQUIRY_STATUS_TRANSITIONS,
  MVP_API_CONTRACTS,
  PRICE_MODES,
  PRODUCT_STATUSES,
  PRODUCT_STATUS_TRANSITIONS,
  PUBLICATION_STATUSES,
  PUBLICATION_STATUS_TRANSITIONS,
  ROLES,
} from "../src/index.js";

type OpenApiOperation = {
  operationId: string;
  "x-module": string;
  "x-auth": string;
  "x-roles": string[];
  "x-errors": string[];
  "x-idempotency": string;
  responses: Record<string, unknown>;
};

const documentedOperations = Object.entries(openApi.paths).flatMap(
  ([path, pathItem]) =>
    Object.entries(pathItem).map(([method, operation]) => ({
      method: method.toUpperCase(),
      path,
      operation: operation as OpenApiOperation,
    })),
);

const schemas = openApi.components.schemas as Record<
  string,
  Record<string, unknown>
>;

describe("OpenAPI and TypeScript contract consistency", () => {
  it("documents exactly the TypeScript manifest operations", () => {
    const documented = documentedOperations
      .map(({ method, path, operation }) => ({
        method,
        path,
        operationId: operation.operationId,
      }))
      .sort((left, right) => left.operationId.localeCompare(right.operationId));
    const manifest = MVP_API_CONTRACTS.map((contract) => ({
        method: contract.method,
        path: contract.path,
        operationId: contract.operationId,
      })).sort((left, right) =>
        left.operationId.localeCompare(right.operationId),
      );
    expect(documented).toEqual(manifest);
  });

  it("keeps auth, roles, errors and idempotency aligned", () => {
    for (const contract of MVP_API_CONTRACTS) {
      const documented = documentedOperations.find(
        ({ operation }) => operation.operationId === contract.operationId,
      );
      expect(documented, contract.operationId).toBeDefined();
      expect(documented?.operation["x-module"]).toBe(contract.module);
      expect(documented?.operation["x-auth"]).toBe(contract.auth);
      expect(documented?.operation["x-roles"]).toEqual([...contract.roles]);
      expect(documented?.operation["x-errors"]).toEqual([...contract.errors]);
      expect(documented?.operation["x-idempotency"]).toBe(
        contract.idempotency,
      );
    }
  });

  it("keeps shared enums and transitions aligned", () => {
    const enumExpectations = {
      Role: ROLES,
      Channel: CHANNELS,
      ErrorCode: ERROR_CODES,
      ContentStatus: CONTENT_STATUSES,
      ContentGenerationStatus: CONTENT_GENERATION_STATUSES,
      PublicationStatus: PUBLICATION_STATUSES,
      InquiryStatus: INQUIRY_STATUSES,
      ProductStatus: PRODUCT_STATUSES,
      PriceMode: PRICE_MODES,
    } as const;

    for (const [name, values] of Object.entries(enumExpectations)) {
      expect(schemas[name]?.enum, name).toEqual([...values]);
    }

    expect(schemas.ContentStatus?.["x-transitions"]).toEqual(
      CONTENT_STATUS_TRANSITIONS,
    );
    expect(schemas.ContentGenerationStatus?.["x-transitions"]).toEqual(
      CONTENT_GENERATION_STATUS_TRANSITIONS,
    );
    expect(schemas.PublicationStatus?.["x-transitions"]).toEqual(
      PUBLICATION_STATUS_TRANSITIONS,
    );
    expect(schemas.InquiryStatus?.["x-transitions"]).toEqual(
      INQUIRY_STATUS_TRANSITIONS,
    );
    expect(schemas.ProductStatus?.["x-transitions"]).toEqual(
      PRODUCT_STATUS_TRANSITIONS,
    );
  });

  it("keeps every business ID prefix aligned", () => {
    for (const [kind, prefix] of Object.entries(BUSINESS_ID_PREFIXES)) {
      const schemaName = kind.charAt(0).toUpperCase() + kind.slice(1);
      expect(schemas[schemaName]?.["x-prefix"], schemaName).toBe(prefix);
    }
  });

  it("uses the common response envelopes for every operation", () => {
    for (const { operation } of documentedOperations) {
      const success = Object.entries(operation.responses).find(
        ([status]) => status !== "default",
      )?.[1] as {
        content?: { "application/json"?: { schema?: { required?: string[] } } };
      };
      expect(
        success.content?.["application/json"]?.schema?.required,
        operation.operationId,
      ).toEqual(["data", "requestId"]);
      expect(operation.responses.default, operation.operationId).toEqual({
        description: "Error",
        content: {
          "application/json": {
            schema: { $ref: "#/components/schemas/ErrorResponse" },
          },
        },
      });
    }
  });

  it("does not reintroduce legacy paths or legacy public fields", () => {
    expect(Object.keys(openApi.paths).some((path) => path.includes("{id}"))).toBe(
      false,
    );
    const schemaFields = new Set(
      Object.values(schemas).flatMap((schema) =>
        Object.keys(
          (schema.properties as Record<string, unknown> | undefined) ?? {},
        ),
      ),
    );
    for (const legacy of [
      "description",
      "imageUrls",
      "isPublic",
      "caption",
      "displayName",
      "externalWorkUrl",
      "failureReason",
      "callbackEventId",
    ]) {
      expect(schemaFields.has(legacy), legacy).toBe(false);
    }
  });
});
