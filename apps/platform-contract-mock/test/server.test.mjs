import assert from "node:assert/strict";
import { once } from "node:events";
import test from "node:test";
import { fixtures, openApi } from "../src/contract.mjs";
import { createPlatformContractMock } from "../src/server.mjs";

async function withServer(run) {
  const { server } = createPlatformContractMock();
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  try {
    await run(`http://127.0.0.1:${address.port}`);
  } finally {
    server.close();
    await once(server, "close");
  }
}

function fixtureRequest(
  baseUrl,
  operationId,
  fixture,
  extraHeaders = {},
  requestFixture = fixture.request,
) {
  let path = fixture.path;
  for (const [name, value] of Object.entries(requestFixture.params ?? {})) {
    path = path.replace(`{${name}}`, encodeURIComponent(String(value)));
  }
  assert.equal(path.includes("{"), false, `${operationId}: unresolved path parameter`);
  const url = new URL(path, baseUrl);
  for (const [name, value] of Object.entries(requestFixture.query ?? {})) {
    if (value === null || value === undefined) continue;
    for (const item of Array.isArray(value) ? value : [value]) {
      url.searchParams.append(name, String(item));
    }
  }

  const headers = new Headers(requestFixture.headers ?? {});
  headers.set("x-trace-id", `trace_smoke_${operationId.replaceAll(".", "_")}`);
  const mode = fixture.auth?.mode;
  if (["ACTOR", "USER_SESSION", "USER_SESSION_STRONG"].includes(mode)) {
    headers.set("authorization", "Bearer contract-smoke");
  }
  if (mode === "USER_SESSION_STRONG") {
    headers.set("x-csrf-token", "csrf-contract-smoke");
  }
  if (["SERVICE", "SERVICE_MTLS", "SERVICE_MTLS_USER_DELEGATION"].includes(mode)) {
    headers.set("x-mtls-verified", "true");
  }
  if (mode === "SERVICE_MTLS_USER_DELEGATION") {
    headers.set("x-user-delegation", "delegation-contract-smoke-token-0001");
  }
  if (["CALLBACK", "SIGNED_PROVIDER_CALLBACK"].includes(mode)) {
    headers.set("x-provider-signature", "contract-provider-signature");
    headers.set("x-provider-timestamp", "2026-08-10T02:00:00Z");
    headers.set("x-provider-nonce", `nonce-${operationId}`);
  }
  if (fixture.idempotency?.source === "HEADER") {
    headers.set("idempotency-key", `CONTRACT_SMOKE:${operationId}`);
  }
  for (const [name, value] of Object.entries(extraHeaders)) headers.set(name, value);

  const body = requestFixture.body;
  if (body !== undefined) headers.set("content-type", "application/json");
  return {
    url,
    init: {
      method: fixture.method,
      headers,
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    },
  };
}

test("health endpoint exposes the full-platform contract version", async () => {
  await withServer(async (baseUrl) => {
    const response = await fetch(`${baseUrl}/healthz`);
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.data.contractVersion, openApi.info.version);
    assert.match(body.requestId, /^req_/);
    assert.match(body.traceId, /^tr_/);
  });
});

test("actor endpoints reject an untrusted tenant-only request", async () => {
  await withServer(async (baseUrl) => {
    const response = await fetch(`${baseUrl}/api/v1/me/context`, {
      headers: { "x-enterprise-id": "ent_attacker" },
    });
    assert.equal(response.status, 401);
    const body = await response.json();
    assert.equal(body.code, "AUTH_REQUIRED");
  });
});

test("fixed actor fixture conforms to OpenAPI", async () => {
  await withServer(async (baseUrl) => {
    const response = await fetch(`${baseUrl}/api/v1/me/context`, {
      headers: {
        authorization: "Bearer contract-test",
        "x-trace-id": "trace_contract_test_001",
      },
    });
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.data.enterpriseId, "ent_001");
    assert.equal(body.requestId.startsWith("req_"), true);
  });
});

test("service routes require a simulated verified mTLS identity", async () => {
  await withServer(async (baseUrl) => {
    const url = `${baseUrl}/internal/v1/opc/assignments/aas_001/status`;
    const rejected = await fetch(url);
    assert.equal(rejected.status, 401);
    assert.equal((await rejected.json()).code, "AUTH_REQUIRED");

    const accepted = await fetch(url, {
      headers: {
        "x-mtls-verified": "true",
        "x-trace-id": "trace_contract_test_002",
      },
    });
    assert.equal(accepted.status, 200);
    assert.equal((await accepted.json()).data.assignmentStatus, "ACTIVE");
  });
});

test("header idempotency replays the original result and rejects payload drift", async () => {
  await withServer(async (baseUrl) => {
    const fixture = fixtures.operations["sys01.enterprise.create"];
    const headers = {
      authorization: "Bearer contract-test",
      "content-type": "application/json",
      "idempotency-key": "ENTERPRISE_CREATE:usr_001:req_enterprise_001",
      "x-trace-id": "trace_contract_test_003",
    };
    const first = await fetch(`${baseUrl}${fixture.path}`, {
      method: fixture.method,
      headers,
      body: JSON.stringify(fixture.request.body),
    });
    assert.equal(first.status, 201);
    const firstBody = await first.json();

    const replay = await fetch(`${baseUrl}${fixture.path}`, {
      method: fixture.method,
      headers,
      body: JSON.stringify(fixture.request.body),
    });
    assert.equal(replay.status, 201);
    assert.deepEqual(await replay.json(), firstBody);

    const conflict = await fetch(`${baseUrl}${fixture.path}`, {
      method: fixture.method,
      headers,
      body: JSON.stringify({ ...fixture.request.body, name: "另一个示例企业" }),
    });
    assert.equal(conflict.status, 409);
    assert.equal((await conflict.json()).code, "IDEMPOTENCY_CONFLICT");
  });
});

test("provider callbacks derive idempotency from signed business fields", async () => {
  await withServer(async (baseUrl) => {
    const fixture = fixtures.operations["sys08.payment.receiveResult"];
    const headers = {
      "content-type": "application/json",
      "x-provider-signature": "contract-provider-signature",
      "x-provider-timestamp": "2026-08-10T02:00:00Z",
      "x-provider-nonce": "provider_nonce_001",
      "x-trace-id": "trace_contract_test_004",
    };
    const response = await fetch(`${baseUrl}/callbacks/v1/payments/WECHAT`, {
      method: fixture.method,
      headers,
      body: JSON.stringify(fixture.request.body),
    });
    assert.equal(response.status, 200);
    assert.equal((await response.json()).data.accepted, true);
  });
});

test("array query parameters use repeated form values", async () => {
  await withServer(async (baseUrl) => {
    const response = await fetch(
      `${baseUrl}/api/v1/analytics/metrics/met_sales_paid?period=DAY&dimensions=STORE&dimensions=CHANNEL`,
      {
        headers: {
          authorization: "Bearer contract-test",
          "x-trace-id": "trace_contract_test_005",
        },
      },
    );
    assert.equal(response.status, 200);
    assert.equal((await response.json()).data.metricId, "met_sales_paid");
  });
});

test("all fixed success and registered failure fixtures traverse the real mock path", async () => {
  await withServer(async (baseUrl) => {
    for (const [operationId, fixture] of Object.entries(fixtures.operations)) {
      const successRequest = fixtureRequest(baseUrl, operationId, fixture);
      const successResponse = await fetch(successRequest.url, successRequest.init);
      const successBody = await successResponse.text();
      assert.equal(
        successResponse.status,
        fixture.status,
        `${operationId} success: expected ${fixture.status}, received ${successResponse.status}: ${successBody}`,
      );

      const failureRequest = fixtureRequest(
        baseUrl,
        operationId,
        fixture,
        { "x-contract-scenario": "failure" },
        fixture.failure.request,
      );
      const failureResponse = await fetch(failureRequest.url, failureRequest.init);
      const failureBody = await failureResponse.json();
      assert.equal(
        failureResponse.status,
        fixture.failure.status,
        `${operationId} default failure: ${JSON.stringify(failureBody)}`,
      );
      assert.equal(failureBody.code, fixture.failure.response.code, operationId);
      assert.equal(failureBody.data, undefined, operationId);

      for (const [code, failure] of Object.entries(fixture.failures)) {
        const errorRequest = fixtureRequest(
          baseUrl,
          operationId,
          fixture,
          { "x-contract-scenario": `error:${code}` },
          failure.request,
        );
        const errorResponse = await fetch(errorRequest.url, errorRequest.init);
        const errorBody = await errorResponse.json();
        assert.equal(
          errorResponse.status,
          failure.status,
          `${operationId} ${code}: ${JSON.stringify(errorBody)}`,
        );
        assert.equal(errorBody.code, code, operationId);
        assert.equal(errorBody.data, undefined, operationId);
      }
    }
  });
});

test("named failure scenarios return a schema-validated business conflict", async () => {
  await withServer(async (baseUrl) => {
    const operationId = "sys01.enterprise.updateProfile";
    const fixture = fixtures.operations[operationId];
    const request = fixtureRequest(
      baseUrl,
      operationId,
      fixture,
      { "x-contract-scenario": "error:VERSION_CONFLICT" },
      fixture.failures.VERSION_CONFLICT.request,
    );
    const response = await fetch(request.url, request.init);
    const body = await response.json();
    assert.equal(response.status, 409);
    assert.equal(body.code, "VERSION_CONFLICT");
    assert.equal(body.data, undefined);
    assert.match(body.requestId, /^req_/);
  });
});
