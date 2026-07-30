import type {
  ContentId,
  ContentStatus,
  ErrorCode,
  GenerationRequestId,
  IsoDateTime,
  MerchantId,
  ProductId,
} from "./common.js";

export const CONTENT_GENERATION_STATUSES = [
  "QUEUED",
  "PROCESSING",
  "SUCCEEDED",
  "FAILED",
] as const;
export type ContentGenerationStatus =
  (typeof CONTENT_GENERATION_STATUSES)[number];

export const CONTENT_GENERATION_STATUS_TRANSITIONS = {
  QUEUED: ["PROCESSING", "FAILED"],
  PROCESSING: ["SUCCEEDED", "FAILED"],
  SUCCEEDED: [],
  FAILED: [],
} as const satisfies Record<
  ContentGenerationStatus,
  readonly ContentGenerationStatus[]
>;

export interface GenerateContentInput {
  productId: ProductId;
  targetAudience: string;
  sellingPoints: string[];
  style: string;
  duration: number;
}

export interface ContentDetail {
  contentId: ContentId;
  merchantId: MerchantId;
  productId: ProductId;
  title: string | null;
  copy: string | null;
  videoUrl: string | null;
  targetAudience: string;
  style: string;
  duration: number;
  status: ContentStatus;
  generationRequestId: GenerationRequestId;
  generationStatus: ContentGenerationStatus;
  generationErrorCode: ErrorCode | null;
  contentVersion: number;
  submittedAt: IsoDateTime | null;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export interface ContentGenerationStatusResult {
  contentId: ContentId;
  generationRequestId: GenerationRequestId;
  status: ContentGenerationStatus;
  errorCode: ErrorCode | null;
  errorMessage: string | null;
  updatedAt: IsoDateTime;
}

export interface UpdateContentInput {
  contentVersion: number;
  title?: string;
  copy?: string;
  videoUrl?: string;
  targetAudience?: string;
  style?: string;
  duration?: number;
}

export interface RegenerateContentInput {
  contentVersion: number;
  targetAudience?: string;
  sellingPoints?: string[];
  style?: string;
  duration?: number;
}

export interface SubmitReviewInput {
  contentVersion: number;
}
