export const CONTENT_STATUSES = [
  "DRAFT",
  "GENERATED",
  "PENDING_REVIEW",
  "APPROVED",
  "REJECTED",
] as const;

export type ContentStatus = (typeof CONTENT_STATUSES)[number];

export const REVIEW_DECISIONS = ["APPROVED", "REJECTED"] as const;
export type ReviewDecision = (typeof REVIEW_DECISIONS)[number];

export const ROLES = ["MERCHANT", "OPERATOR", "BUYER"] as const;
export type Role = (typeof ROLES)[number];

export const REJECTION_REASONS = [
  { code: "MISLEADING_CLAIM", label: "宣传表述可能误导" },
  { code: "INCOMPLETE_INFORMATION", label: "商品信息不完整" },
  { code: "MEDIA_QUALITY", label: "视频或素材质量不达标" },
  { code: "PLATFORM_POLICY", label: "不符合平台内容规范" },
  { code: "OTHER", label: "其他原因" },
] as const;

export type RejectionReasonCode = (typeof REJECTION_REASONS)[number]["code"];

export interface ReviewRecord {
  reviewId: string;
  contentId: string;
  decision: ReviewDecision;
  reasonCode: string | null;
  comment: string | null;
  reviewerId: string;
  reviewerName: string;
  reviewedAt: string;
  contentVersion: number;
  previousStatus: ContentStatus;
  nextStatus: ContentStatus;
}

export interface ReviewContentSummary {
  contentId: string;
  merchantId: string;
  merchantName: string;
  productId: string;
  productTitle: string;
  title: string;
  status: ContentStatus;
  contentVersion: number;
  submittedAt: string;
}

export interface ReviewContentDetail extends ReviewContentSummary {
  copy: string;
  videoUrl: string;
  sellingPoints: string[];
  targetAudience: string;
  reviewHistory: ReviewRecord[];
}

export interface PendingReviewsQuery {
  page?: number;
  pageSize?: number;
  merchantId?: string;
  submittedFrom?: string;
  submittedTo?: string;
}

export interface PendingReviewsPage {
  items: ReviewContentSummary[];
  page: number;
  pageSize: number;
  total: number;
}

export interface ApproveReviewInput {
  contentVersion: number;
  comment?: string;
}

export interface RejectReviewInput {
  contentVersion: number;
  reasonCode?: RejectionReasonCode;
  comment: string;
}

export interface ReviewDecisionResult {
  content: ReviewContentSummary;
  review: ReviewRecord;
}

export interface SuccessResponse<T> {
  data: T;
  requestId: string;
}

export interface ErrorResponse {
  errorCode: string;
  message: string;
  requestId: string;
  details?: Record<string, unknown>;
}

export const PUBLICATION_STATUSES = [
  "QUEUED",
  "PUBLISHING",
  "SUCCEEDED",
  "FAILED",
] as const;
export type PublicationStatus = (typeof PUBLICATION_STATUSES)[number];

export const INQUIRY_STATUSES = [
  "NEW",
  "CONTACTED",
  "QUOTED",
  "WON",
  "LOST",
] as const;
export type InquiryStatus = (typeof INQUIRY_STATUSES)[number];

export const CHANNELS = ["DOUYIN", "XIAOHONGSHU"] as const;
export type Channel = (typeof CHANNELS)[number];

export interface AuditFields {
  createdAt: string;
  updatedAt: string;
  createdBy?: string;
  updatedBy?: string;
}

export interface Product extends AuditFields {
  productId: string;
  merchantId: string;
  name: string;
  description: string;
  imageUrls: string[];
  isPublic: boolean;
}

export interface Content extends AuditFields {
  contentId: string;
  merchantId: string;
  productId: string;
  caption: string;
  videoUrl: string;
  status: ContentStatus;
  rejectionReason?: string;
}

export interface AuthorizedAccount {
  accountId: string;
  channel: Channel;
  displayName: string;
  available: boolean;
}

export interface Publication extends AuditFields {
  publicationId: string;
  merchantId: string;
  productId: string;
  contentId: string;
  accountId: string;
  channel: Channel;
  status: PublicationStatus;
  externalWorkId?: string;
  externalWorkUrl?: string;
  failureReason?: string;
}

export interface Inquiry extends AuditFields {
  inquiryId: string;
  merchantId: string;
  productId: string;
  contentId: string;
  publicationId: string;
  channel: Channel;
  accountId: string;
  buyerName: string;
  contact: string;
  message: string;
  status: InquiryStatus;
}

export interface FeedItem {
  publicationId: string;
  productId: string;
  contentId: string;
  merchantId: string;
  channel: Channel;
  caption: string;
  videoUrl: string;
  externalWorkUrl: string;
  productName: string;
}

export interface StorefrontProduct {
  product: Product;
  merchantName: string;
}

export interface CreateProductInput {
  name: string;
  description: string;
  imageUrls: string[];
}

export interface GenerateContentInput {
  productId: string;
}

export interface UpdateContentInput {
  caption?: string;
  videoUrl?: string;
}

export type MockPublicationScenario =
  | "SUCCESS"
  | "PROCESSING"
  | "FAILURE";

export interface CreatePublicationInput {
  contentId: string;
  accountId: string;
  channel: Channel;
  scenario?: MockPublicationScenario;
}

export interface PublicationCallbackInput {
  callbackEventId: string;
  publicationId: string;
  status: Extract<PublicationStatus, "SUCCEEDED" | "FAILED">;
  externalWorkId?: string;
  externalWorkUrl?: string;
  failureReason?: string;
}

export interface CreateInquiryInput {
  publicationId: string;
  buyerName: string;
  contact: string;
  message: string;
}

export interface UpdateInquiryStatusInput {
  status: InquiryStatus;
}

export interface Page<T> {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
}
