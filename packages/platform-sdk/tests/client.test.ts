import { describe, expect, it, vi } from "vitest";
import { createPlatformClient } from "../src/index.js";

describe("generated platform SDK client", () => {
  it("adds trace and actor authentication without accepting tenant headers", async () => {
    const fetchMock = vi.fn(async (request: Request) => {
      expect(request.headers.get("authorization")).toBe("Bearer actor-token");
      expect(request.headers.get("x-trace-id")).toBe("tr_contract_test");
      expect(request.headers.has("x-enterprise-id")).toBe(false);
      return new Response(
        JSON.stringify({
          data: {
            user: { userId: "usr_test" },
            enterprise: { enterpriseId: "ent_test" },
            roles: ["ENTERPRISE_ADMIN"],
          },
          requestId: "req_contract_test",
          traceId: "tr_contract_test",
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    });
    const client = createPlatformClient({
      accessToken: "actor-token",
      baseUrl: "http://contracts.test/",
      fetch: fetchMock,
      traceIdFactory: () => "tr_contract_test",
    });

    await client.GET("/api/v1/me/context");
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("omits null optional query values from the wire URL", async () => {
    const fetchMock = vi.fn(async (request: Request) => {
      const url = new URL(request.url);
      expect(url.searchParams.get("period")).toBe("LAST_7_DAYS");
      expect(url.searchParams.has("startAt")).toBe(false);
      expect(url.searchParams.has("endAt")).toBe(false);
      return new Response(
        JSON.stringify({
          data: { cards: [], dataCutoffAt: "2026-08-10T01:59:00Z", generatedAt: "2026-08-10T02:00:00Z" },
          requestId: "req_contract_test",
          traceId: "tr_contract_test",
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    });
    const client = createPlatformClient({
      accessToken: "actor-token",
      baseUrl: "http://contracts.test",
      fetch: fetchMock,
      traceIdFactory: () => "tr_contract_test",
    });

    await client.GET("/api/v1/analytics/overview", {
      params: {
        query: { period: "LAST_7_DAYS", startAt: null, endAt: null },
      },
    });
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});
