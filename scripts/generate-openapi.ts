import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath, pathToFileURL } from "node:url";
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
  REJECTION_REASONS,
  REVIEW_DECISIONS,
  ROLES,
} from "../packages/contracts/src/index.js";

type Schema = Record<string, unknown>;

const string = (extra: Schema = {}): Schema => ({ type: "string", ...extra });
const integer = (extra: Schema = {}): Schema => ({ type: "integer", ...extra });
const number = (extra: Schema = {}): Schema => ({ type: "number", ...extra });
const boolean = (extra: Schema = {}): Schema => ({ type: "boolean", ...extra });
const ref = (name: string): Schema => ({ $ref: `#/components/schemas/${name}` });
const array = (items: Schema): Schema => ({ type: "array", items });
const nullable = (schema: Schema): Schema => ({ anyOf: [schema, { type: "null" }] });
const object = (
  required: string[],
  properties: Record<string, Schema>,
  extra: Schema = {},
): Schema => ({
  type: "object",
  additionalProperties: false,
  required,
  properties,
  ...extra,
});

const isoDateTime = string({ format: "date-time" });
const requestId = string({ pattern: "^req_[A-Za-z0-9_-]+$" });
const idSchema = (prefix: string): Schema =>
  string({
    pattern: `^${prefix}[A-Za-z0-9][A-Za-z0-9_-]*$`,
    "x-prefix": prefix,
  });

const schemas: Record<string, Schema> = {
  MerchantId: idSchema(BUSINESS_ID_PREFIXES.merchantId),
  ProductId: idSchema(BUSINESS_ID_PREFIXES.productId),
  ContentId: idSchema(BUSINESS_ID_PREFIXES.contentId),
  AccountId: idSchema(BUSINESS_ID_PREFIXES.accountId),
  PublicationId: idSchema(BUSINESS_ID_PREFIXES.publicationId),
  InquiryId: idSchema(BUSINESS_ID_PREFIXES.inquiryId),
  ReviewId: idSchema(BUSINESS_ID_PREFIXES.reviewId),
  GenerationRequestId: idSchema(BUSINESS_ID_PREFIXES.generationRequestId),
  Role: { type: "string", enum: [...ROLES] },
  Channel: { type: "string", enum: [...CHANNELS] },
  ErrorCode: { type: "string", enum: [...ERROR_CODES] },
  ContentStatus: {
    type: "string",
    enum: [...CONTENT_STATUSES],
    "x-transitions": CONTENT_STATUS_TRANSITIONS,
  },
  ContentGenerationStatus: {
    type: "string",
    enum: [...CONTENT_GENERATION_STATUSES],
    "x-transitions": CONTENT_GENERATION_STATUS_TRANSITIONS,
  },
  PublicationStatus: {
    type: "string",
    enum: [...PUBLICATION_STATUSES],
    "x-transitions": PUBLICATION_STATUS_TRANSITIONS,
  },
  InquiryStatus: {
    type: "string",
    enum: [...INQUIRY_STATUSES],
    "x-transitions": INQUIRY_STATUS_TRANSITIONS,
  },
  ProductStatus: {
    type: "string",
    enum: [...PRODUCT_STATUSES],
    "x-transitions": PRODUCT_STATUS_TRANSITIONS,
  },
  PriceMode: { type: "string", enum: [...PRICE_MODES] },
  ReviewDecision: { type: "string", enum: [...REVIEW_DECISIONS] },
  RejectionReasonCode: {
    type: "string",
    enum: REJECTION_REASONS.map((item) => item.code),
  },
  ProductImage: object(["url", "sortOrder", "altText"], {
    url: string({ format: "uri" }),
    sortOrder: integer({ minimum: 0 }),
    altText: nullable(string()),
  }),
  ProductParameter: object(["key", "value"], {
    key: string(),
    value: string(),
  }),
  Product: object(
    [
      "productId",
      "merchantId",
      "name",
      "summary",
      "sellingPoints",
      "images",
      "parameters",
      "priceMode",
      "price",
      "status",
      "createdAt",
      "updatedAt",
    ],
    {
      productId: ref("ProductId"),
      merchantId: ref("MerchantId"),
      name: string(),
      summary: string(),
      sellingPoints: array(string()),
      images: array(ref("ProductImage")),
      parameters: array(ref("ProductParameter")),
      priceMode: ref("PriceMode"),
      price: nullable(number({ minimum: 0 })),
      status: ref("ProductStatus"),
      createdAt: isoDateTime,
      updatedAt: isoDateTime,
    },
  ),
  ProductSummary: object(
    [
      "productId",
      "merchantId",
      "name",
      "primaryImageUrl",
      "sellingPoints",
      "priceMode",
      "price",
      "status",
      "updatedAt",
    ],
    {
      productId: ref("ProductId"),
      merchantId: ref("MerchantId"),
      name: string(),
      primaryImageUrl: nullable(string({ format: "uri" })),
      sellingPoints: array(string()),
      priceMode: ref("PriceMode"),
      price: nullable(number({ minimum: 0 })),
      status: ref("ProductStatus"),
      updatedAt: isoDateTime,
    },
  ),
  CreateProductInput: object(["name", "sellingPoints", "priceMode"], {
    name: string(),
    summary: string(),
    sellingPoints: array(string()),
    images: array(ref("ProductImage")),
    parameters: array(ref("ProductParameter")),
    priceMode: ref("PriceMode"),
    price: nullable(number({ minimum: 0 })),
  }),
  UpdateProductInput: object([], {
    name: string(),
    summary: string(),
    sellingPoints: array(string()),
    images: array(ref("ProductImage")),
    parameters: array(ref("ProductParameter")),
    priceMode: ref("PriceMode"),
    price: nullable(number({ minimum: 0 })),
  }),
  ProductImageUploadResult: object(["url", "contentType", "size"], {
    url: string({ format: "uri" }),
    contentType: string(),
    size: integer({ minimum: 0 }),
  }),
  ProductImageUpload: object(["file"], {
    file: string({ format: "binary" }),
  }),
  GenerateContentInput: object(
    ["productId", "targetAudience", "sellingPoints", "style", "duration"],
    {
      productId: ref("ProductId"),
      targetAudience: string(),
      sellingPoints: array(string()),
      style: string(),
      duration: integer({ minimum: 1 }),
    },
  ),
  ContentDetail: object(
    [
      "contentId",
      "merchantId",
      "productId",
      "title",
      "copy",
      "videoUrl",
      "targetAudience",
      "style",
      "duration",
      "status",
      "generationRequestId",
      "generationStatus",
      "generationErrorCode",
      "contentVersion",
      "submittedAt",
      "createdAt",
      "updatedAt",
    ],
    {
      contentId: ref("ContentId"),
      merchantId: ref("MerchantId"),
      productId: ref("ProductId"),
      title: nullable(string()),
      copy: nullable(string()),
      videoUrl: nullable(string({ format: "uri" })),
      targetAudience: string(),
      style: string(),
      duration: integer({ minimum: 1 }),
      status: ref("ContentStatus"),
      generationRequestId: ref("GenerationRequestId"),
      generationStatus: ref("ContentGenerationStatus"),
      generationErrorCode: nullable(ref("ErrorCode")),
      contentVersion: integer({ minimum: 1 }),
      submittedAt: nullable(isoDateTime),
      createdAt: isoDateTime,
      updatedAt: isoDateTime,
    },
  ),
  ContentGenerationStatusResult: object(
    ["contentId", "generationRequestId", "status", "errorCode", "errorMessage", "updatedAt"],
    {
      contentId: ref("ContentId"),
      generationRequestId: ref("GenerationRequestId"),
      status: ref("ContentGenerationStatus"),
      errorCode: nullable(ref("ErrorCode")),
      errorMessage: nullable(string()),
      updatedAt: isoDateTime,
    },
  ),
  UpdateContentInput: object(["contentVersion"], {
    contentVersion: integer({ minimum: 1 }),
    title: string(),
    copy: string(),
    videoUrl: string({ format: "uri" }),
    targetAudience: string(),
    style: string(),
    duration: integer({ minimum: 1 }),
  }),
  RegenerateContentInput: object(["contentVersion"], {
    contentVersion: integer({ minimum: 1 }),
    targetAudience: string(),
    sellingPoints: array(string()),
    style: string(),
    duration: integer({ minimum: 1 }),
  }),
  SubmitReviewInput: object(["contentVersion"], {
    contentVersion: integer({ minimum: 1 }),
  }),
  ReviewRecord: object(
    [
      "reviewId",
      "contentId",
      "decision",
      "reasonCode",
      "comment",
      "reviewerId",
      "reviewerName",
      "reviewedAt",
      "contentVersion",
      "previousStatus",
      "nextStatus",
    ],
    {
      reviewId: ref("ReviewId"),
      contentId: ref("ContentId"),
      decision: ref("ReviewDecision"),
      reasonCode: nullable(ref("RejectionReasonCode")),
      comment: nullable(string()),
      reviewerId: string(),
      reviewerName: string(),
      reviewedAt: isoDateTime,
      contentVersion: integer({ minimum: 1 }),
      previousStatus: ref("ContentStatus"),
      nextStatus: ref("ContentStatus"),
    },
  ),
  ReviewContentSummary: object(
    [
      "contentId",
      "merchantId",
      "merchantName",
      "productId",
      "productTitle",
      "title",
      "status",
      "contentVersion",
      "submittedAt",
    ],
    {
      contentId: ref("ContentId"),
      merchantId: ref("MerchantId"),
      merchantName: string(),
      productId: ref("ProductId"),
      productTitle: string(),
      title: string(),
      status: ref("ContentStatus"),
      contentVersion: integer({ minimum: 1 }),
      submittedAt: isoDateTime,
    },
  ),
  ReviewContentDetail: object(
    [
      "contentId",
      "merchantId",
      "merchantName",
      "productId",
      "productTitle",
      "title",
      "status",
      "contentVersion",
      "submittedAt",
      "copy",
      "videoUrl",
      "sellingPoints",
      "targetAudience",
      "reviewHistory",
    ],
    {
      contentId: ref("ContentId"),
      merchantId: ref("MerchantId"),
      merchantName: string(),
      productId: ref("ProductId"),
      productTitle: string(),
      title: string(),
      status: ref("ContentStatus"),
      contentVersion: integer({ minimum: 1 }),
      submittedAt: isoDateTime,
      copy: string(),
      videoUrl: string({ format: "uri" }),
      sellingPoints: array(string()),
      targetAudience: string(),
      reviewHistory: array(ref("ReviewRecord")),
    },
  ),
  ApproveReviewInput: object(["contentVersion"], {
    contentVersion: integer({ minimum: 1 }),
    comment: string(),
  }),
  RejectReviewInput: object(["contentVersion", "comment"], {
    contentVersion: integer({ minimum: 1 }),
    reasonCode: ref("RejectionReasonCode"),
    comment: string({ minLength: 1 }),
  }),
  ReviewDecisionResult: object(["content", "review"], {
    content: ref("ReviewContentSummary"),
    review: ref("ReviewRecord"),
  }),
  AuthorizedAccount: object(["accountId", "channel", "displayLabel", "available"], {
    accountId: ref("AccountId"),
    channel: ref("Channel"),
    displayLabel: string(),
    available: boolean(),
  }),
  CreatePublicationInput: object(["contentId", "accountId", "channel", "idempotencyKey"], {
    contentId: ref("ContentId"),
    accountId: ref("AccountId"),
    channel: ref("Channel"),
    idempotencyKey: string({ minLength: 8 }),
  }),
  RetryPublicationInput: object(["idempotencyKey"], {
    idempotencyKey: string({ minLength: 8 }),
  }),
  Publication: object(
    [
      "publicationId",
      "merchantId",
      "contentId",
      "productId",
      "channel",
      "accountId",
      "idempotencyKey",
      "status",
      "externalTaskId",
      "externalWorkId",
      "externalUrl",
      "errorCode",
      "errorMessage",
      "requestedBy",
      "publishedAt",
      "createdAt",
      "updatedAt",
    ],
    {
      publicationId: ref("PublicationId"),
      merchantId: ref("MerchantId"),
      contentId: ref("ContentId"),
      productId: ref("ProductId"),
      channel: ref("Channel"),
      accountId: ref("AccountId"),
      idempotencyKey: string(),
      status: ref("PublicationStatus"),
      externalTaskId: nullable(string()),
      externalWorkId: nullable(string()),
      externalUrl: nullable(string({ format: "uri" })),
      errorCode: nullable(ref("ErrorCode")),
      errorMessage: nullable(string()),
      requestedBy: string(),
      publishedAt: nullable(isoDateTime),
      createdAt: isoDateTime,
      updatedAt: isoDateTime,
    },
  ),
  PublicationCallbackAck: object(["accepted", "duplicate"], {
    accepted: boolean(),
    duplicate: boolean(),
  }),
  PublicSourceAttribution: object(
    ["merchantId", "productId", "contentId", "publicationId", "channel", "externalWorkId", "referrer"],
    {
      merchantId: ref("MerchantId"),
      productId: ref("ProductId"),
      contentId: nullable(ref("ContentId")),
      publicationId: nullable(ref("PublicationId")),
      channel: nullable(ref("Channel")),
      externalWorkId: nullable(string()),
      referrer: nullable(string()),
    },
  ),
  SourceAttribution: object(
    ["merchantId", "productId", "contentId", "publicationId", "channel", "accountId", "externalWorkId", "referrer"],
    {
      merchantId: ref("MerchantId"),
      productId: ref("ProductId"),
      contentId: nullable(ref("ContentId")),
      publicationId: nullable(ref("PublicationId")),
      channel: nullable(ref("Channel")),
      accountId: nullable(ref("AccountId")),
      externalWorkId: nullable(string()),
      referrer: nullable(string()),
    },
  ),
  FeedItem: object(
    [
      "publicationId",
      "contentId",
      "productId",
      "merchantId",
      "channel",
      "externalWorkId",
      "externalUrl",
      "videoUrl",
      "title",
      "productName",
      "merchantName",
      "sellingPoints",
      "publishedAt",
    ],
    {
      publicationId: ref("PublicationId"),
      contentId: ref("ContentId"),
      productId: ref("ProductId"),
      merchantId: ref("MerchantId"),
      channel: ref("Channel"),
      externalWorkId: string(),
      externalUrl: string({ format: "uri" }),
      videoUrl: string({ format: "uri" }),
      title: string(),
      productName: string(),
      merchantName: string(),
      sellingPoints: array(string()),
      publishedAt: isoDateTime,
    },
  ),
  StorefrontProduct: object(
    [
      "productId",
      "merchantId",
      "merchantName",
      "name",
      "summary",
      "sellingPoints",
      "images",
      "parameters",
      "priceMode",
      "price",
      "available",
      "attribution",
    ],
    {
      productId: ref("ProductId"),
      merchantId: ref("MerchantId"),
      merchantName: string(),
      name: string(),
      summary: string(),
      sellingPoints: array(string()),
      images: array(ref("ProductImage")),
      parameters: array(ref("ProductParameter")),
      priceMode: ref("PriceMode"),
      price: nullable(number()),
      available: boolean(),
      attribution: ref("PublicSourceAttribution"),
    },
  ),
  StorefrontMerchant: object(["merchantId", "name", "summary", "primaryBusiness"], {
    merchantId: ref("MerchantId"),
    name: string(),
    summary: string(),
    primaryBusiness: string(),
  }),
  StorefrontPublication: object(
    ["publicationId", "merchantId", "productId", "contentId", "channel", "externalWorkId", "externalUrl", "publishedAt"],
    {
      publicationId: ref("PublicationId"),
      merchantId: ref("MerchantId"),
      productId: ref("ProductId"),
      contentId: ref("ContentId"),
      channel: ref("Channel"),
      externalWorkId: string(),
      externalUrl: string({ format: "uri" }),
      publishedAt: isoDateTime,
    },
  ),
  CreateInquiryInput: object(["productId", "buyerName", "contact", "message"], {
    productId: ref("ProductId"),
    publicationId: ref("PublicationId"),
    buyerName: string(),
    contact: string(),
    quantity: string(),
    message: string(),
    referrer: string(),
  }),
  InquiryCreated: object(["inquiryId", "status", "createdAt"], {
    inquiryId: ref("InquiryId"),
    status: { type: "string", const: "NEW" },
    createdAt: isoDateTime,
  }),
  Inquiry: object(
    ["inquiryId", "merchantId", "productId", "buyerName", "contact", "quantity", "message", "status", "attribution", "createdAt", "updatedAt"],
    {
      inquiryId: ref("InquiryId"),
      merchantId: ref("MerchantId"),
      productId: ref("ProductId"),
      buyerName: string(),
      contact: string(),
      quantity: nullable(string()),
      message: string(),
      status: ref("InquiryStatus"),
      attribution: ref("SourceAttribution"),
      createdAt: isoDateTime,
      updatedAt: isoDateTime,
    },
  ),
  InquiryStatusChange: object(["fromStatus", "toStatus", "changedBy", "changedAt", "comment"], {
    fromStatus: ref("InquiryStatus"),
    toStatus: ref("InquiryStatus"),
    changedBy: string(),
    changedAt: isoDateTime,
    comment: nullable(string()),
  }),
  InquiryDetail: object(
    ["inquiryId", "merchantId", "productId", "buyerName", "contact", "quantity", "message", "status", "attribution", "createdAt", "updatedAt", "statusHistory"],
    {
      inquiryId: ref("InquiryId"),
      merchantId: ref("MerchantId"),
      productId: ref("ProductId"),
      buyerName: string(),
      contact: string(),
      quantity: nullable(string()),
      message: string(),
      status: ref("InquiryStatus"),
      attribution: ref("SourceAttribution"),
      createdAt: isoDateTime,
      updatedAt: isoDateTime,
      statusHistory: array(ref("InquiryStatusChange")),
    },
  ),
  UpdateInquiryStatusInput: object(["status"], {
    status: ref("InquiryStatus"),
    comment: string(),
  }),
  ProductPage: object(["items", "page", "pageSize", "total"], {
    items: array(ref("ProductSummary")),
    page: integer({ minimum: 1 }),
    pageSize: integer({ minimum: 1 }),
    total: integer({ minimum: 0 }),
  }),
  PendingReviewsPage: object(["items", "page", "pageSize", "total"], {
    items: array(ref("ReviewContentSummary")),
    page: integer({ minimum: 1 }),
    pageSize: integer({ minimum: 1 }),
    total: integer({ minimum: 0 }),
  }),
  PublicationPage: object(["items", "page", "pageSize", "total"], {
    items: array(ref("Publication")),
    page: integer({ minimum: 1 }),
    pageSize: integer({ minimum: 1 }),
    total: integer({ minimum: 0 }),
  }),
  FeedPage: object(["items", "page", "pageSize", "total"], {
    items: array(ref("FeedItem")),
    page: integer({ minimum: 1 }),
    pageSize: integer({ minimum: 1 }),
    total: integer({ minimum: 0 }),
  }),
  InquiryPage: object(["items", "page", "pageSize", "total"], {
    items: array(ref("Inquiry")),
    page: integer({ minimum: 1 }),
    pageSize: integer({ minimum: 1 }),
    total: integer({ minimum: 0 }),
  }),
  ErrorResponse: object(["errorCode", "message", "requestId"], {
    errorCode: ref("ErrorCode"),
    message: string(),
    requestId,
    details: { type: "object", additionalProperties: true },
  }),
};

const operationShapes: Record<
  string,
  { body?: string; data: Schema; status?: number; query?: string[] }
> = {
  "foundation.health": { data: object(["status"], { status: { type: "string", const: "ok" } }) },
  "product.create": { body: "CreateProductInput", data: ref("Product"), status: 201 },
  "product.list": { data: ref("ProductPage"), query: ["page", "pageSize", "status"] },
  "product.get": { data: ref("Product") },
  "product.update": { body: "UpdateProductInput", data: ref("Product") },
  "product.activate": { data: ref("Product") },
  "product.deactivate": { data: ref("Product") },
  "product.uploadImage": { body: "ProductImageUpload", data: ref("ProductImageUploadResult"), status: 201 },
  "content.generate": { body: "GenerateContentInput", data: ref("ContentGenerationStatusResult"), status: 201 },
  "content.get": { data: ref("ContentDetail") },
  "content.generationStatus": { data: ref("ContentGenerationStatusResult") },
  "content.update": { body: "UpdateContentInput", data: ref("ContentDetail") },
  "content.regenerate": { body: "RegenerateContentInput", data: ref("ContentGenerationStatusResult") },
  "content.submitReview": { body: "SubmitReviewInput", data: ref("ContentDetail") },
  "review.pending": { data: ref("PendingReviewsPage"), query: ["page", "pageSize", "merchantId", "submittedFrom", "submittedTo"] },
  "review.get": { data: ref("ReviewContentDetail") },
  "review.approve": { body: "ApproveReviewInput", data: ref("ReviewDecisionResult") },
  "review.reject": { body: "RejectReviewInput", data: ref("ReviewDecisionResult") },
  "review.history": { data: array(ref("ReviewRecord")) },
  "publishing.accounts": { data: array(ref("AuthorizedAccount")), query: ["channel"] },
  "publishing.create": { body: "CreatePublicationInput", data: ref("Publication"), status: 201 },
  "publishing.get": { data: ref("Publication") },
  "publishing.list": { data: ref("PublicationPage"), query: ["page", "pageSize", "status", "channel"] },
  "publishing.retry": { body: "RetryPublicationInput", data: ref("Publication") },
  "publishing.callback": { body: "ProviderCallback", data: ref("PublicationCallbackAck") },
  "storefront.feed": { data: ref("FeedPage"), query: ["page", "pageSize"] },
  "storefront.product": { data: ref("StorefrontProduct"), query: ["publicationId"] },
  "storefront.merchant": { data: ref("StorefrontMerchant") },
  "storefront.publication": { data: ref("StorefrontPublication") },
  "inquiry.create": { body: "CreateInquiryInput", data: ref("InquiryCreated"), status: 201 },
  "inquiry.list": { data: ref("InquiryPage"), query: ["page", "pageSize", "status"] },
  "inquiry.get": { data: ref("InquiryDetail") },
  "inquiry.updateStatus": { body: "UpdateInquiryStatusInput", data: ref("InquiryDetail") },
};

schemas.ProviderCallback = {
  type: "object",
  additionalProperties: true,
  description: "Provider-specific callback body; verified and normalized by the publishing adapter.",
};

function queryParameter(name: string): Schema {
  const byName: Record<string, Schema> = {
    page: integer({ minimum: 1, default: 1 }),
    pageSize: integer({ minimum: 1, maximum: 100, default: 20 }),
    status: string(),
    channel: ref("Channel"),
    merchantId: ref("MerchantId"),
    submittedFrom: isoDateTime,
    submittedTo: isoDateTime,
    publicationId: ref("PublicationId"),
  };
  return {
    name,
    in: "query",
    required: name === "channel",
    schema: byName[name],
  };
}

function successSchema(data: Schema): Schema {
  return object(["data", "requestId"], { data, requestId });
}

export function createOpenApiDocument(): Schema {
  const paths: Record<string, Record<string, Schema>> = {};

  for (const contract of MVP_API_CONTRACTS) {
    const shape = operationShapes[contract.operationId];
    if (!shape) throw new Error(`Missing OpenAPI shape for ${contract.operationId}`);

    const parameters: Schema[] = [];
    for (const name of contract.path.matchAll(/\{([^}]+)\}/g)) {
      parameters.push({
        name: name[1],
        in: "path",
        required: true,
        schema: ref(name[1][0].toUpperCase() + name[1].slice(1)),
      });
    }
    for (const query of shape.query ?? []) parameters.push(queryParameter(query));

    const status = String(shape.status ?? 200);
    const operation: Schema = {
      operationId: contract.operationId,
      summary: contract.operationId,
      "x-module": contract.module,
      "x-auth": contract.auth,
      "x-roles": [...contract.roles],
      "x-errors": [...contract.errors],
      "x-idempotency": contract.idempotency,
      security:
        contract.auth === "ACTOR" ? [{ roleHeader: [], userHeader: [] }] : [],
      parameters,
      responses: {
        [status]: {
          description: "Success",
          content: {
            "application/json": { schema: successSchema(shape.data) },
          },
        },
        default: {
          description: "Error",
          content: {
            "application/json": { schema: ref("ErrorResponse") },
          },
        },
      },
    };

    if (shape.body) {
      operation.requestBody = {
        required: true,
        content: {
          [contract.operationId === "product.uploadImage"
            ? "multipart/form-data"
            : "application/json"]: { schema: ref(shape.body) },
        },
      };
    }

    paths[contract.path] ??= {};
    paths[contract.path][contract.method.toLowerCase()] = operation;
  }

  return {
    openapi: "3.1.0",
    info: {
      title: "Wotao MVP Integration API",
      version: "1.0.0",
      description: "Generated from the integration TypeScript contract manifest.",
    },
    paths,
    components: {
      securitySchemes: {
        roleHeader: { type: "apiKey", in: "header", name: "x-role" },
        userHeader: { type: "apiKey", in: "header", name: "x-user-id" },
      },
      schemas,
    },
  };
}

const outputPath = fileURLToPath(
  new URL("../packages/contracts/openapi.json", import.meta.url),
);
const rendered = `${JSON.stringify(createOpenApiDocument(), null, 2)}\n`;

async function main(): Promise<void> {
  if (process.argv.includes("--check")) {
    const current = await readFile(outputPath, "utf8");
    if (current !== rendered) {
      throw new Error("packages/contracts/openapi.json is out of date");
    }
  } else {
    await writeFile(outputPath, rendered, "utf8");
    console.log(`Generated ${outputPath}`);
  }
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  main().catch((error: unknown) => {
    console.error(error);
    process.exitCode = 1;
  });
}
