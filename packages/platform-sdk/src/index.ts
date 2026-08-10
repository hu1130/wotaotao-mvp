import createClient, {
  type Client,
  type ClientOptions,
  type Middleware,
} from "openapi-fetch";
import type { paths } from "./generated/schema.js";

export type PlatformApiPaths = paths;
export type PlatformApiClient = Client<paths>;

export interface PlatformClientOptions
  extends Omit<ClientOptions, "baseUrl" | "headers"> {
  baseUrl: string;
  accessToken?: string;
  serviceToken?: string;
  traceIdFactory?: () => string;
  headers?: HeadersInit;
}

function defaultTraceId(): string {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}`;
  return `tr_${random.replaceAll("-", "")}`;
}

/**
 * Creates the generated full-platform API client.
 *
 * Browser callers use `accessToken`. Service-to-service callers use
 * `serviceToken` only behind an mTLS boundary; the token does not replace mTLS.
 * Tenant and actor identifiers are deliberately not accepted here because they
 * must be derived from the trusted authentication context.
 */
export function createPlatformClient(
  options: PlatformClientOptions,
): PlatformApiClient {
  const {
    accessToken,
    baseUrl,
    headers,
    serviceToken,
    traceIdFactory = defaultTraceId,
    ...clientOptions
  } = options;
  const client = createClient<paths>({
    ...clientOptions,
    baseUrl: baseUrl.replace(/\/$/, ""),
    ...(headers === undefined ? {} : { headers }),
  });

  const authentication: Middleware = {
    async onRequest({ request }) {
      const next = new Request(request);
      next.headers.set("X-Trace-Id", traceIdFactory());
      if (accessToken) next.headers.set("Authorization", `Bearer ${accessToken}`);
      if (serviceToken) next.headers.set("X-Service-Authorization", serviceToken);
      return next;
    },
  };
  client.use(authentication);
  return client;
}

export type { components, operations, paths } from "./generated/schema.js";
