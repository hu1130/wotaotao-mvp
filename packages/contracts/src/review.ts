import type {
  ContentId,
  ContentStatus,
  IsoDateTime,
  MerchantId,
  Page,
  PaginationQuery,
  ProductId,
  ReviewId,
} from "./common.js";

export const REVIEW_DECISIONS = ["APPROVED", "REJECTED"] as const;
export type ReviewDecision = (typeof REVIEW_DECISIONS)[number];

export const REJECTION_REASONS = [
  { code: "MISLEADING_CLAIM", label: "宣传表述可能误导" },
  { code: "INCOMPLETE_INFORMATION", label: "商品信息不完整" },
  { code: "MEDIA_QUALITY", label: "视频或素材质量不达标" },
  { code: "PLATFORM_POLICY", label: "不符合平台内容规范" },
  { code: "OTHER", label: "其他原因" },
] as const;

export type RejectionReasonCode = (typeof REJECTION_REASONS)[number]["code"];

export interface ReviewRecord {
  reviewId: ReviewId;
  contentId: ContentId;
  decision: ReviewDecision;
  reasonCode: RejectionReasonCode | null;
  comment: string | null;
  reviewerId: string;
  reviewerName: string;
  reviewedAt: IsoDateTime;
  contentVersion: number;
  previousStatus: ContentStatus;
  nextStatus: ContentStatus;
}

export interface ReviewContentSummary {
  contentId: ContentId;
  merchantId: MerchantId;
  merchantName: string;
  productId: ProductId;
  productTitle: string;
  title: string;
  status: ContentStatus;
  contentVersion: number;
  submittedAt: IsoDateTime;
}

export interface ReviewContentDetail extends ReviewContentSummary {
  copy: string;
  videoUrl: string;
  sellingPoints: string[];
  targetAudience: string;
  reviewHistory: ReviewRecord[];
}

export interface PendingReviewsQuery extends PaginationQuery {
  merchantId?: MerchantId;
  submittedFrom?: IsoDateTime;
  submittedTo?: IsoDateTime;
}

export type PendingReviewsPage = Page<ReviewContentSummary>;

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
