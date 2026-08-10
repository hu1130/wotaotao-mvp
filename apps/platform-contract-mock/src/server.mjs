import { createHash, randomUUID } from "node:crypto";
import { createServer } from "node:http";
import { pathToFileURL } from "node:url";
import {
  fixtureFor,
  matchOperation,
  openApi,
  parameterValidators,
  requestValidator,
  responseValidator,
} from "./contract.mjs";

const JSON_HEADERS = {
  "cache-control": "no-store",
  "content-type": "application/json; charset=utf-8",
};

class MockError extends Error {
  constructor(status, code, message, details) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function traceId(req) {
  const supplied = req.headers["x-trace-id"];
  if (typeof supplied === "string" && supplied.length > 0) return supplied;
  return `tr_${randomUUID().replaceAll("-", "")}`;
}

function requestId() {
  return `req_${randomUUID().replaceAll("-", "")}`;
}

function send(res, status, payload, trace) {
  res.writeHead(status, { ...JSON_HEADERS, "x-trace-id": trace });
  res.end(JSON.stringify(payload));
}

function authorize(req, auth) {
  const mode = typeof auth === "string" ? auth : auth?.mode;
  if (!mode || mode === "PUBLIC") return;
  if (mode === "ACTOR" || mode === "USER_SESSION" || mode === "USER_SESSION_STRONG") {
    const authorization = req.headers.authorization;
    if (typeof authorization !== "string" || !authorization.startsWith("Bearer ")) {
      throw new MockError(401, "AUTH_REQUIRED", "Bearer actor token is required");
    }
    if (
      mode === "USER_SESSION_STRONG" &&
      typeof req.headers["x-csrf-token"] !== "string"
    ) {
      throw new MockError(403, "FORBIDDEN", "X-Csrf-Token is required");
    }
    return;
  }
  if (mode === "SERVICE" || mode === "SERVICE_MTLS" || mode === "SERVICE_MTLS_USER_DELEGATION") {
    if (req.headers["x-mtls-verified"] !== "true") {
      throw new MockError(
        401,
        "AUTH_REQUIRED",
        "The mock uses x-mtls-verified=true to simulate a verified client certificate",
      );
    }
    if (
      mode === "SERVICE_MTLS_USER_DELEGATION" &&
      typeof req.headers["x-user-delegation"] !== "string"
    ) {
      throw new MockError(403, "FORBIDDEN", "X-User-Delegation is required");
    }
    return;
  }
  if (mode === "CALLBACK" || mode === "SIGNED_PROVIDER_CALLBACK") {
    if (
      typeof req.headers["x-provider-signature"] !== "string" ||
      typeof req.headers["x-provider-timestamp"] !== "string" ||
      typeof req.headers["x-provider-nonce"] !== "string"
    ) {
      throw new MockError(
        401,
        "CALLBACK_SIGNATURE_INVALID",
        "Provider signature, timestamp and nonce are required",
      );
    }
  }
}

function validateParameters(req, url, operation) {
  for (const parameter of parameterValidators(operation)) {
    let value;
    if (parameter.location === "path") value = operation.params[parameter.name];
    else if (parameter.location === "query") {
      const values = url.searchParams.getAll(parameter.name);
      value = values.length === 0
        ? undefined
        : parameter.isArray
          ? values
          : values[0];
    }
    else if (parameter.location === "header") value = req.headers[parameter.name.toLowerCase()];
    if (value === undefined && parameter.required) {
      throw new MockError(400, "VALIDATION_ERROR", `Missing ${parameter.location} parameter ${parameter.name}`);
    }
    if (value !== undefined && parameter.validate && !parameter.validate(value)) {
      throw new MockError(400, "VALIDATION_ERROR", `${parameter.location} parameter ${parameter.name} violates OpenAPI`, {
        errors: parameter.validate.errors,
      });
    }
  }
}

async function readBody(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 2 * 1024 * 1024) {
      throw new MockError(413, "VALIDATION_ERROR", "Request body exceeds 2MB");
    }
    chunks.push(chunk);
  }
  if (chunks.length === 0) return undefined;
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new MockError(400, "VALIDATION_ERROR", "Request body is not JSON");
  }
}

function stableHash(value) {
  return createHash("sha256").update(JSON.stringify(value ?? null)).digest("hex");
}

function providerEventKey(format, operation, url, body) {
  let unresolved = false;
  const key = format.replace(/\{([^}]+)\}/g, (_, name) => {
    const value = operation.params[name] ?? body?.[name] ?? url.searchParams.get(name);
    if (value === undefined || value === null) {
      unresolved = true;
      return `{${name}}`;
    }
    return String(value);
  });
  if (unresolved) {
    throw new MockError(
      400,
      "VALIDATION_ERROR",
      "Provider event idempotency fields are incomplete",
      { keyFormat: format },
    );
  }
  return key;
}

function normalizePayload(payload, requestIdValue, trace) {
  if (!payload || typeof payload !== "object") return payload;
  if ("data" in payload || "code" in payload || "errorCode" in payload) {
    return { ...payload, requestId: requestIdValue, traceId: trace };
  }
  return { data: payload, requestId: requestIdValue, traceId: trace };
}

function selectScenario(req, fixture) {
  const requested = req.headers["x-contract-scenario"];
  if (requested === undefined || requested === "success") {
    return { name: "success", fixture };
  }
  if (requested === "failure") {
    return { name: "failure", fixture: fixture.failure };
  }
  if (typeof requested === "string" && requested.startsWith("error:")) {
    const code = requested.slice("error:".length);
    const selected = fixture.failures?.[code];
    if (selected) return { name: requested, fixture: selected };
  }
  throw new MockError(
    400,
    "VALIDATION_ERROR",
    "Unknown X-Contract-Scenario; use success, failure or error:<ERROR_CODE>",
    { requested },
  );
}

export function createPlatformContractMock(options = {}) {
  const idempotencyStore = options.idempotencyStore ?? new Map();
  const server = createServer(async (req, res) => {
    const currentTraceId = traceId(req);
    const currentRequestId = requestId();
    try {
      const url = new URL(req.url ?? "/", "http://contract-mock.local");
      if (url.pathname === "/healthz") {
        return send(
          res,
          200,
          {
            data: { status: "ok", contractVersion: openApi.info.version },
            requestId: currentRequestId,
            traceId: currentTraceId,
          },
          currentTraceId,
        );
      }
      const operation = matchOperation(req.method ?? "GET", url.pathname);
      if (!operation) {
        throw new MockError(404, "NOT_FOUND", "No contract operation matches");
      }
      authorize(req, operation.auth);
      validateParameters(req, url, operation);
      const body = await readBody(req);
      const validateRequest = requestValidator(operation);
      if (validateRequest && !validateRequest(body)) {
        throw new MockError(422, "VALIDATION_ERROR", "Request violates OpenAPI", {
          errors: validateRequest.errors,
        });
      }

      const idempotencySource = operation.idempotency?.source ?? "NONE";
      const suppliedIdempotencyKey = req.headers["idempotency-key"];
      if (
        operation.idempotency?.required === true &&
        idempotencySource === "HEADER" &&
        typeof suppliedIdempotencyKey !== "string"
      ) {
        throw new MockError(
          400,
          "VALIDATION_ERROR",
          "Idempotency-Key is required",
          { keyFormat: operation.idempotency.keyFormat },
        );
      }
      const idempotencyKey =
        idempotencySource === "PROVIDER_EVENT"
          ? providerEventKey(operation.idempotency.keyFormat, operation, url, body)
          : suppliedIdempotencyKey;

      const fixture = fixtureFor(operation.operationId);
      if (!fixture) {
        throw new MockError(501, "DEPENDENCY_UNAVAILABLE", "No fixed fixture exists", {
          operationId: operation.operationId,
        });
      }
      const scenario = selectScenario(req, fixture);
      if (!scenario.fixture) {
        throw new MockError(501, "DEPENDENCY_UNAVAILABLE", "Scenario fixture is missing", {
          operationId: operation.operationId,
          scenario: scenario.name,
        });
      }
      const status = scenario.fixture.status ?? 200;
      const payload = normalizePayload(
        structuredClone(scenario.fixture.response),
        currentRequestId,
        currentTraceId,
      );

      if (typeof idempotencyKey === "string") {
        const key = `${scenario.name}:${operation.operationId}:${idempotencyKey}`;
        const hash = stableHash(body);
        const previous = idempotencyStore.get(key);
        if (previous && previous.hash !== hash) {
          throw new MockError(
            409,
            "IDEMPOTENCY_CONFLICT",
            "The same key was used with a different payload",
          );
        }
        if (previous) {
          return send(res, previous.status, previous.payload, currentTraceId);
        }
        idempotencyStore.set(key, { hash, payload, status });
      }

      const validateResponse = responseValidator(operation, status);
      if (validateResponse && !validateResponse(payload)) {
        throw new MockError(
          500,
          "DEPENDENCY_UNAVAILABLE",
          "Fixed response fixture violates OpenAPI",
          { errors: validateResponse.errors, operationId: operation.operationId },
        );
      }
      return send(res, status, payload, currentTraceId);
    } catch (error) {
      const status = error instanceof MockError ? error.status : 500;
      const errorCode = error instanceof MockError ? error.code : "DEPENDENCY_UNAVAILABLE";
      const message = error instanceof Error ? error.message : "Unexpected error";
      const payload = {
        code: errorCode,
        message,
        retryable: status === 429 || status >= 500,
        requestId: currentRequestId,
        traceId: currentTraceId,
        fieldErrors: [],
      };
      if (error instanceof MockError && error.details !== undefined) {
        payload.details = error.details;
      }
      send(res, status, payload, currentTraceId);
    }
  });
  return { idempotencyStore, server };
}

function isMainModule() {
  return process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
}

if (isMainModule()) {
  const host = process.env.HOST ?? "0.0.0.0";
  const port = Number(process.env.PORT ?? 4011);
  const { server } = createPlatformContractMock();
  server.listen(port, host, () => {
    console.log(`Wotao platform contract mock: http://${host}:${port}`);
  });
}
