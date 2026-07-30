import type {
  AccountId,
  ContentId,
  ErrorCode,
  InquiryId,
  MerchantId,
  ProductId,
  PublicationId,
  Role,
  SuccessResponse,
} from "./common.js";
import type {
  ContentDetail,
  ContentGenerationStatusResult,
  GenerateContentInput,
  RegenerateContentInput,
  SubmitReviewInput,
  UpdateContentInput,
} from "./content.js";
import type {
  CreateInquiryInput,
  InquiryCreated,
  InquiryDetail,
  InquiryPage,
  MerchantInquiriesQuery,
  UpdateInquiryStatusInput,
} from "./inquiry.js";
import type {
  CreateProductInput,
  Product,
  ProductImageUploadResult,
  ProductListQuery,
  ProductPage,
  UpdateProductInput,
} from "./product.js";
import type {
  AuthorizedAccount,
  AuthorizedAccountsQuery,
  CreatePublicationInput,
  Publication,
  PublicationCallbackAck,
  PublicationListQuery,
  PublicationPage,
  RetryPublicationInput,
} from "./publishing.js";
import type {
  ApproveReviewInput,
  PendingReviewsPage,
  PendingReviewsQuery,
  RejectReviewInput,
  ReviewContentDetail,
  ReviewDecisionResult,
  ReviewRecord,
} from "./review.js";
import type {
  FeedPage,
  FeedQuery,
  StorefrontMerchant,
  StorefrontProduct,
  StorefrontProductQuery,
  StorefrontPublication,
} from "./storefront.js";

export type MvpModuleCode =
  | "01_FOUNDATION"
  | "02_PRODUCT"
  | "03_CONTENT"
  | "04_REVIEW"
  | "05_PUBLISHING"
  | "06_STOREFRONT"
  | "07_INQUIRY"
  | "08_INTEGRATION";

export interface ApiOperationType<
  Params = undefined,
  Query = undefined,
  Body = undefined,
  Data = unknown,
> {
  request: {
    params: Params;
    query: Query;
    body: Body;
  };
  response: SuccessResponse<Data>;
}

export interface MvpApiOperationMap {
  "foundation.health": ApiOperationType<
    undefined,
    undefined,
    undefined,
    { status: "ok" }
  >;

  "product.create": ApiOperationType<
    undefined,
    undefined,
    CreateProductInput,
    Product
  >;
  "product.list": ApiOperationType<
    undefined,
    ProductListQuery,
    undefined,
    ProductPage
  >;
  "product.get": ApiOperationType<
    { productId: ProductId },
    undefined,
    undefined,
    Product
  >;
  "product.update": ApiOperationType<
    { productId: ProductId },
    undefined,
    UpdateProductInput,
    Product
  >;
  "product.activate": ApiOperationType<
    { productId: ProductId },
    undefined,
    undefined,
    Product
  >;
  "product.deactivate": ApiOperationType<
    { productId: ProductId },
    undefined,
    undefined,
    Product
  >;
  "product.uploadImage": ApiOperationType<
    undefined,
    undefined,
    FormData,
    ProductImageUploadResult
  >;

  "content.generate": ApiOperationType<
    undefined,
    undefined,
    GenerateContentInput,
    ContentGenerationStatusResult
  >;
  "content.get": ApiOperationType<
    { contentId: ContentId },
    undefined,
    undefined,
    ContentDetail
  >;
  "content.generationStatus": ApiOperationType<
    { contentId: ContentId },
    undefined,
    undefined,
    ContentGenerationStatusResult
  >;
  "content.update": ApiOperationType<
    { contentId: ContentId },
    undefined,
    UpdateContentInput,
    ContentDetail
  >;
  "content.regenerate": ApiOperationType<
    { contentId: ContentId },
    undefined,
    RegenerateContentInput,
    ContentGenerationStatusResult
  >;
  "content.submitReview": ApiOperationType<
    { contentId: ContentId },
    undefined,
    SubmitReviewInput,
    ContentDetail
  >;

  "review.pending": ApiOperationType<
    undefined,
    PendingReviewsQuery,
    undefined,
    PendingReviewsPage
  >;
  "review.get": ApiOperationType<
    { contentId: ContentId },
    undefined,
    undefined,
    ReviewContentDetail
  >;
  "review.approve": ApiOperationType<
    { contentId: ContentId },
    undefined,
    ApproveReviewInput,
    ReviewDecisionResult
  >;
  "review.reject": ApiOperationType<
    { contentId: ContentId },
    undefined,
    RejectReviewInput,
    ReviewDecisionResult
  >;
  "review.history": ApiOperationType<
    { contentId: ContentId },
    undefined,
    undefined,
    ReviewRecord[]
  >;

  "publishing.accounts": ApiOperationType<
    undefined,
    AuthorizedAccountsQuery,
    undefined,
    AuthorizedAccount[]
  >;
  "publishing.create": ApiOperationType<
    undefined,
    undefined,
    CreatePublicationInput,
    Publication
  >;
  "publishing.get": ApiOperationType<
    { publicationId: PublicationId },
    undefined,
    undefined,
    Publication
  >;
  "publishing.list": ApiOperationType<
    undefined,
    PublicationListQuery,
    undefined,
    PublicationPage
  >;
  "publishing.retry": ApiOperationType<
    { publicationId: PublicationId },
    undefined,
    RetryPublicationInput,
    Publication
  >;
  "publishing.callback": ApiOperationType<
    undefined,
    undefined,
    unknown,
    PublicationCallbackAck
  >;

  "storefront.feed": ApiOperationType<
    undefined,
    FeedQuery,
    undefined,
    FeedPage
  >;
  "storefront.product": ApiOperationType<
    { productId: ProductId },
    StorefrontProductQuery,
    undefined,
    StorefrontProduct
  >;
  "storefront.merchant": ApiOperationType<
    { merchantId: MerchantId },
    undefined,
    undefined,
    StorefrontMerchant
  >;
  "storefront.publication": ApiOperationType<
    { publicationId: PublicationId },
    undefined,
    undefined,
    StorefrontPublication
  >;

  "inquiry.create": ApiOperationType<
    undefined,
    undefined,
    CreateInquiryInput,
    InquiryCreated
  >;
  "inquiry.list": ApiOperationType<
    undefined,
    MerchantInquiriesQuery,
    undefined,
    InquiryPage
  >;
  "inquiry.get": ApiOperationType<
    { inquiryId: InquiryId },
    undefined,
    undefined,
    InquiryDetail
  >;
  "inquiry.updateStatus": ApiOperationType<
    { inquiryId: InquiryId },
    undefined,
    UpdateInquiryStatusInput,
    InquiryDetail
  >;
}

export type MvpApiOperationId = keyof MvpApiOperationMap;
export type MvpApiRequest<K extends MvpApiOperationId> =
  MvpApiOperationMap[K]["request"];
export type MvpApiResponse<K extends MvpApiOperationId> =
  MvpApiOperationMap[K]["response"];

export const MVP_MODULES = [
  {
    module: "01_FOUNDATION",
    dependsOn: [],
    output: "共享类型、状态、权限上下文、响应信封和契约校验",
  },
  {
    module: "02_PRODUCT",
    dependsOn: ["01_FOUNDATION"],
    output: "可归属、可读取的 productId 与商品资料",
  },
  {
    module: "03_CONTENT",
    dependsOn: ["01_FOUNDATION", "02_PRODUCT"],
    output: "可播放、带版本且可提交审核的 contentId",
  },
  {
    module: "04_REVIEW",
    dependsOn: ["01_FOUNDATION", "03_CONTENT"],
    output: "不可覆盖的审核记录与可信 APPROVED 门禁",
  },
  {
    module: "05_PUBLISHING",
    dependsOn: ["01_FOUNDATION", "04_REVIEW"],
    output: "幂等 publicationId、外部作品结果和失败信息",
  },
  {
    module: "06_STOREFRONT",
    dependsOn: ["01_FOUNDATION", "02_PRODUCT", "05_PUBLISHING"],
    output: "仅成功发布内容可见的公开页面及来源上下文",
  },
  {
    module: "07_INQUIRY",
    dependsOn: ["01_FOUNDATION", "02_PRODUCT", "05_PUBLISHING"],
    output: "服务端补全来源的 inquiryId 与跟进状态历史",
  },
  {
    module: "08_INTEGRATION",
    dependsOn: [
      "02_PRODUCT",
      "03_CONTENT",
      "04_REVIEW",
      "05_PUBLISHING",
      "06_STOREFRONT",
      "07_INQUIRY",
    ],
    output: "端到端回归、演示证据、已知限制与上线检查",
  },
] as const satisfies readonly {
  module: MvpModuleCode;
  dependsOn: readonly MvpModuleCode[];
  output: string;
}[];

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH";
export type AuthMode = "PUBLIC" | "ACTOR";
export type IdempotencyMode = "NONE" | "BODY_REQUIRED" | "PROVIDER_EVENT";

export interface ApiContractDescriptor {
  operationId: MvpApiOperationId;
  module: MvpModuleCode;
  method: HttpMethod;
  path: string;
  auth: AuthMode;
  roles: readonly Role[];
  requestType: string;
  responseType: string;
  errors: readonly ErrorCode[];
  idempotency: IdempotencyMode;
}

const COMMON_ACTOR_ERRORS = [
  "UNAUTHENTICATED",
  "FORBIDDEN",
  "VALIDATION_ERROR",
  "INTERNAL_ERROR",
] as const satisfies readonly ErrorCode[];

export const MVP_API_CONTRACTS = [
  {
    operationId: "foundation.health",
    module: "01_FOUNDATION",
    method: "GET",
    path: "/health",
    auth: "PUBLIC",
    roles: [],
    requestType: "none",
    responseType: "{ status: 'ok' }",
    errors: ["INTERNAL_ERROR"],
    idempotency: "NONE",
  },
  {
    operationId: "product.create",
    module: "02_PRODUCT",
    method: "POST",
    path: "/products",
    auth: "ACTOR",
    roles: ["MERCHANT"],
    requestType: "CreateProductInput",
    responseType: "Product",
    errors: [...COMMON_ACTOR_ERRORS, "PRODUCT_VALIDATION_FAILED"],
    idempotency: "NONE",
  },
  {
    operationId: "product.list",
    module: "02_PRODUCT",
    method: "GET",
    path: "/products",
    auth: "ACTOR",
    roles: ["MERCHANT"],
    requestType: "ProductListQuery",
    responseType: "ProductPage",
    errors: COMMON_ACTOR_ERRORS,
    idempotency: "NONE",
  },
  {
    operationId: "product.get",
    module: "02_PRODUCT",
    method: "GET",
    path: "/products/{productId}",
    auth: "ACTOR",
    roles: ["MERCHANT", "OPERATOR"],
    requestType: "{ productId }",
    responseType: "Product",
    errors: [...COMMON_ACTOR_ERRORS, "PRODUCT_NOT_FOUND"],
    idempotency: "NONE",
  },
  {
    operationId: "product.update",
    module: "02_PRODUCT",
    method: "PUT",
    path: "/products/{productId}",
    auth: "ACTOR",
    roles: ["MERCHANT"],
    requestType: "UpdateProductInput",
    responseType: "Product",
    errors: [
      ...COMMON_ACTOR_ERRORS,
      "PRODUCT_NOT_FOUND",
      "PRODUCT_VALIDATION_FAILED",
    ],
    idempotency: "NONE",
  },
  {
    operationId: "product.activate",
    module: "02_PRODUCT",
    method: "POST",
    path: "/products/{productId}/activate",
    auth: "ACTOR",
    roles: ["MERCHANT"],
    requestType: "{ productId }",
    responseType: "Product",
    errors: [...COMMON_ACTOR_ERRORS, "PRODUCT_NOT_FOUND"],
    idempotency: "NONE",
  },
  {
    operationId: "product.deactivate",
    module: "02_PRODUCT",
    method: "POST",
    path: "/products/{productId}/deactivate",
    auth: "ACTOR",
    roles: ["MERCHANT"],
    requestType: "{ productId }",
    responseType: "Product",
    errors: [...COMMON_ACTOR_ERRORS, "PRODUCT_NOT_FOUND"],
    idempotency: "NONE",
  },
  {
    operationId: "product.uploadImage",
    module: "02_PRODUCT",
    method: "POST",
    path: "/uploads/product-images",
    auth: "ACTOR",
    roles: ["MERCHANT"],
    requestType: "multipart/form-data",
    responseType: "ProductImageUploadResult",
    errors: COMMON_ACTOR_ERRORS,
    idempotency: "NONE",
  },
  {
    operationId: "content.generate",
    module: "03_CONTENT",
    method: "POST",
    path: "/contents/generate",
    auth: "ACTOR",
    roles: ["MERCHANT"],
    requestType: "GenerateContentInput",
    responseType: "ContentGenerationStatusResult",
    errors: [
      ...COMMON_ACTOR_ERRORS,
      "PRODUCT_NOT_FOUND",
      "PRODUCT_INACTIVE",
      "PRODUCT_VALIDATION_FAILED",
    ],
    idempotency: "NONE",
  },
  {
    operationId: "content.get",
    module: "03_CONTENT",
    method: "GET",
    path: "/contents/{contentId}",
    auth: "ACTOR",
    roles: ["MERCHANT", "OPERATOR"],
    requestType: "{ contentId }",
    responseType: "ContentDetail",
    errors: [...COMMON_ACTOR_ERRORS, "CONTENT_NOT_FOUND"],
    idempotency: "NONE",
  },
  {
    operationId: "content.generationStatus",
    module: "03_CONTENT",
    method: "GET",
    path: "/contents/{contentId}/generation-status",
    auth: "ACTOR",
    roles: ["MERCHANT"],
    requestType: "{ contentId }",
    responseType: "ContentGenerationStatusResult",
    errors: [...COMMON_ACTOR_ERRORS, "CONTENT_NOT_FOUND"],
    idempotency: "NONE",
  },
  {
    operationId: "content.update",
    module: "03_CONTENT",
    method: "PUT",
    path: "/contents/{contentId}",
    auth: "ACTOR",
    roles: ["MERCHANT"],
    requestType: "UpdateContentInput",
    responseType: "ContentDetail",
    errors: [
      ...COMMON_ACTOR_ERRORS,
      "CONTENT_NOT_FOUND",
      "CONTENT_NOT_EDITABLE",
      "CONTENT_VERSION_CONFLICT",
    ],
    idempotency: "NONE",
  },
  {
    operationId: "content.regenerate",
    module: "03_CONTENT",
    method: "POST",
    path: "/contents/{contentId}/regenerate",
    auth: "ACTOR",
    roles: ["MERCHANT"],
    requestType: "RegenerateContentInput",
    responseType: "ContentGenerationStatusResult",
    errors: [
      ...COMMON_ACTOR_ERRORS,
      "CONTENT_NOT_FOUND",
      "CONTENT_NOT_EDITABLE",
      "CONTENT_VERSION_CONFLICT",
      "GENERATION_IN_PROGRESS",
    ],
    idempotency: "NONE",
  },
  {
    operationId: "content.submitReview",
    module: "03_CONTENT",
    method: "POST",
    path: "/contents/{contentId}/submit-review",
    auth: "ACTOR",
    roles: ["MERCHANT"],
    requestType: "SubmitReviewInput",
    responseType: "ContentDetail",
    errors: [
      ...COMMON_ACTOR_ERRORS,
      "CONTENT_NOT_FOUND",
      "CONTENT_NOT_EDITABLE",
      "CONTENT_VERSION_CONFLICT",
    ],
    idempotency: "NONE",
  },
  {
    operationId: "review.pending",
    module: "04_REVIEW",
    method: "GET",
    path: "/reviews/pending",
    auth: "ACTOR",
    roles: ["OPERATOR"],
    requestType: "PendingReviewsQuery",
    responseType: "PendingReviewsPage",
    errors: COMMON_ACTOR_ERRORS,
    idempotency: "NONE",
  },
  {
    operationId: "review.get",
    module: "04_REVIEW",
    method: "GET",
    path: "/reviews/{contentId}",
    auth: "ACTOR",
    roles: ["OPERATOR"],
    requestType: "{ contentId }",
    responseType: "ReviewContentDetail",
    errors: [...COMMON_ACTOR_ERRORS, "CONTENT_NOT_FOUND"],
    idempotency: "NONE",
  },
  {
    operationId: "review.approve",
    module: "04_REVIEW",
    method: "POST",
    path: "/reviews/{contentId}/approve",
    auth: "ACTOR",
    roles: ["OPERATOR"],
    requestType: "ApproveReviewInput",
    responseType: "ReviewDecisionResult",
    errors: [
      ...COMMON_ACTOR_ERRORS,
      "CONTENT_NOT_FOUND",
      "CONTENT_VERSION_CONFLICT",
      "REVIEW_STATUS_CHANGED",
      "REVIEW_CONFLICT",
    ],
    idempotency: "NONE",
  },
  {
    operationId: "review.reject",
    module: "04_REVIEW",
    method: "POST",
    path: "/reviews/{contentId}/reject",
    auth: "ACTOR",
    roles: ["OPERATOR"],
    requestType: "RejectReviewInput",
    responseType: "ReviewDecisionResult",
    errors: [
      ...COMMON_ACTOR_ERRORS,
      "CONTENT_NOT_FOUND",
      "CONTENT_VERSION_CONFLICT",
      "REVIEW_STATUS_CHANGED",
      "REVIEW_CONFLICT",
      "REJECTION_REASON_REQUIRED",
    ],
    idempotency: "NONE",
  },
  {
    operationId: "review.history",
    module: "04_REVIEW",
    method: "GET",
    path: "/contents/{contentId}/review-history",
    auth: "ACTOR",
    roles: ["MERCHANT", "OPERATOR"],
    requestType: "{ contentId }",
    responseType: "ReviewRecord[]",
    errors: [...COMMON_ACTOR_ERRORS, "CONTENT_NOT_FOUND"],
    idempotency: "NONE",
  },
  {
    operationId: "publishing.accounts",
    module: "05_PUBLISHING",
    method: "GET",
    path: "/authorized-accounts",
    auth: "ACTOR",
    roles: ["OPERATOR"],
    requestType: "AuthorizedAccountsQuery",
    responseType: "AuthorizedAccount[]",
    errors: COMMON_ACTOR_ERRORS,
    idempotency: "NONE",
  },
  {
    operationId: "publishing.create",
    module: "05_PUBLISHING",
    method: "POST",
    path: "/publications",
    auth: "ACTOR",
    roles: ["OPERATOR"],
    requestType: "CreatePublicationInput",
    responseType: "Publication",
    errors: [
      ...COMMON_ACTOR_ERRORS,
      "CONTENT_NOT_FOUND",
      "CONTENT_NOT_APPROVED",
      "ACCOUNT_NOT_AVAILABLE",
      "IDEMPOTENCY_CONFLICT",
    ],
    idempotency: "BODY_REQUIRED",
  },
  {
    operationId: "publishing.get",
    module: "05_PUBLISHING",
    method: "GET",
    path: "/publications/{publicationId}",
    auth: "ACTOR",
    roles: ["MERCHANT", "OPERATOR"],
    requestType: "{ publicationId }",
    responseType: "Publication",
    errors: [...COMMON_ACTOR_ERRORS, "PUBLICATION_NOT_FOUND"],
    idempotency: "NONE",
  },
  {
    operationId: "publishing.list",
    module: "05_PUBLISHING",
    method: "GET",
    path: "/publications",
    auth: "ACTOR",
    roles: ["MERCHANT", "OPERATOR"],
    requestType: "PublicationListQuery",
    responseType: "PublicationPage",
    errors: COMMON_ACTOR_ERRORS,
    idempotency: "NONE",
  },
  {
    operationId: "publishing.retry",
    module: "05_PUBLISHING",
    method: "POST",
    path: "/publications/{publicationId}/retry",
    auth: "ACTOR",
    roles: ["OPERATOR"],
    requestType: "RetryPublicationInput",
    responseType: "Publication",
    errors: [
      ...COMMON_ACTOR_ERRORS,
      "PUBLICATION_NOT_FOUND",
      "IDEMPOTENCY_CONFLICT",
    ],
    idempotency: "BODY_REQUIRED",
  },
  {
    operationId: "publishing.callback",
    module: "05_PUBLISHING",
    method: "POST",
    path: "/publications/callback",
    auth: "PUBLIC",
    roles: [],
    requestType: "provider-specific body; normalize after source verification",
    responseType: "PublicationCallbackAck",
    errors: ["CALLBACK_INVALID", "VALIDATION_ERROR", "INTERNAL_ERROR"],
    idempotency: "PROVIDER_EVENT",
  },
  {
    operationId: "storefront.feed",
    module: "06_STOREFRONT",
    method: "GET",
    path: "/feed",
    auth: "PUBLIC",
    roles: [],
    requestType: "FeedQuery",
    responseType: "FeedPage",
    errors: ["VALIDATION_ERROR", "INTERNAL_ERROR"],
    idempotency: "NONE",
  },
  {
    operationId: "storefront.product",
    module: "06_STOREFRONT",
    method: "GET",
    path: "/storefront/products/{productId}",
    auth: "PUBLIC",
    roles: [],
    requestType: "StorefrontProductQuery",
    responseType: "StorefrontProduct",
    errors: ["PRODUCT_NOT_FOUND", "VALIDATION_ERROR", "INTERNAL_ERROR"],
    idempotency: "NONE",
  },
  {
    operationId: "storefront.merchant",
    module: "06_STOREFRONT",
    method: "GET",
    path: "/storefront/merchants/{merchantId}",
    auth: "PUBLIC",
    roles: [],
    requestType: "{ merchantId }",
    responseType: "StorefrontMerchant",
    errors: ["VALIDATION_ERROR", "INTERNAL_ERROR"],
    idempotency: "NONE",
  },
  {
    operationId: "storefront.publication",
    module: "06_STOREFRONT",
    method: "GET",
    path: "/storefront/publications/{publicationId}",
    auth: "PUBLIC",
    roles: [],
    requestType: "{ publicationId }",
    responseType: "StorefrontPublication",
    errors: [
      "PUBLICATION_NOT_FOUND",
      "VALIDATION_ERROR",
      "INTERNAL_ERROR",
    ],
    idempotency: "NONE",
  },
  {
    operationId: "inquiry.create",
    module: "07_INQUIRY",
    method: "POST",
    path: "/inquiries",
    auth: "PUBLIC",
    roles: [],
    requestType: "CreateInquiryInput",
    responseType: "InquiryCreated",
    errors: [
      "VALIDATION_ERROR",
      "PRODUCT_NOT_FOUND",
      "PUBLICATION_NOT_FOUND",
      "SOURCE_MISMATCH",
      "DUPLICATE_INQUIRY",
      "RATE_LIMITED",
      "INTERNAL_ERROR",
    ],
    idempotency: "NONE",
  },
  {
    operationId: "inquiry.list",
    module: "07_INQUIRY",
    method: "GET",
    path: "/merchant/inquiries",
    auth: "ACTOR",
    roles: ["MERCHANT"],
    requestType: "MerchantInquiriesQuery",
    responseType: "InquiryPage",
    errors: COMMON_ACTOR_ERRORS,
    idempotency: "NONE",
  },
  {
    operationId: "inquiry.get",
    module: "07_INQUIRY",
    method: "GET",
    path: "/merchant/inquiries/{inquiryId}",
    auth: "ACTOR",
    roles: ["MERCHANT"],
    requestType: "{ inquiryId }",
    responseType: "InquiryDetail",
    errors: [...COMMON_ACTOR_ERRORS, "INQUIRY_NOT_FOUND"],
    idempotency: "NONE",
  },
  {
    operationId: "inquiry.updateStatus",
    module: "07_INQUIRY",
    method: "PATCH",
    path: "/inquiries/{inquiryId}/status",
    auth: "ACTOR",
    roles: ["MERCHANT", "OPERATOR"],
    requestType: "UpdateInquiryStatusInput",
    responseType: "InquiryDetail",
    errors: [
      ...COMMON_ACTOR_ERRORS,
      "INQUIRY_NOT_FOUND",
      "INQUIRY_STATUS_INVALID",
    ],
    idempotency: "NONE",
  },
] as const satisfies readonly ApiContractDescriptor[];

type ManifestOperationId = (typeof MVP_API_CONTRACTS)[number]["operationId"];

export const API_OPERATION_MAP_IS_COMPLETE: Exclude<
  MvpApiOperationId,
  ManifestOperationId
> extends never
  ? true
  : never = true;

export function validateMvpApiContracts(): string[] {
  const errors: string[] = [];
  const operationIds = new Set<string>();
  const routes = new Set<string>();

  for (const item of MVP_API_CONTRACTS) {
    const contract: ApiContractDescriptor = item;
    const routeKey = `${contract.method} ${contract.path}`;

    if (operationIds.has(contract.operationId)) {
      errors.push(`duplicate operationId: ${contract.operationId}`);
    }
    operationIds.add(contract.operationId);

    if (routes.has(routeKey)) {
      errors.push(`duplicate route: ${routeKey}`);
    }
    routes.add(routeKey);

    if (!contract.path.startsWith("/")) {
      errors.push(`path must start with '/': ${contract.operationId}`);
    }
    if (contract.auth === "ACTOR" && contract.roles.length === 0) {
      errors.push(`actor route has no role: ${contract.operationId}`);
    }
    if (contract.auth === "PUBLIC" && contract.roles.length > 0) {
      errors.push(
        `public route must not trust a caller role: ${contract.operationId}`,
      );
    }
  }

  const publicationCreate = MVP_API_CONTRACTS.find(
    (contract) => contract.operationId === "publishing.create",
  );
  if (publicationCreate?.idempotency !== "BODY_REQUIRED") {
    errors.push("publishing.create must require a body idempotencyKey");
  }

  const publicationCallback = MVP_API_CONTRACTS.find(
    (contract) => contract.operationId === "publishing.callback",
  );
  if (publicationCallback?.idempotency !== "PROVIDER_EVENT") {
    errors.push("publishing.callback must deduplicate provider events");
  }

  return errors;
}
