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
