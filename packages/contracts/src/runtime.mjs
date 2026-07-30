export const ContentStatus = Object.freeze({
  DRAFT: "DRAFT",
  GENERATED: "GENERATED",
  PENDING_REVIEW: "PENDING_REVIEW",
  APPROVED: "APPROVED",
  REJECTED: "REJECTED",
});

export const PublicationStatus = Object.freeze({
  QUEUED: "QUEUED",
  PUBLISHING: "PUBLISHING",
  SUCCEEDED: "SUCCEEDED",
  FAILED: "FAILED",
});

export const InquiryStatus = Object.freeze({
  NEW: "NEW",
  CONTACTED: "CONTACTED",
  QUOTED: "QUOTED",
  WON: "WON",
  LOST: "LOST",
});

export const Channel = Object.freeze({
  DOUYIN: "DOUYIN",
  XIAOHONGSHU: "XIAOHONGSHU",
});

export const Role = Object.freeze({
  MERCHANT: "MERCHANT",
  OPERATOR: "OPERATOR",
  BUYER: "BUYER",
});

export const CONTENT_TRANSITIONS = Object.freeze({
  DRAFT: ["GENERATED"],
  GENERATED: ["PENDING_REVIEW"],
  PENDING_REVIEW: ["APPROVED", "REJECTED"],
  APPROVED: [],
  REJECTED: ["PENDING_REVIEW"],
});

export const PUBLICATION_TRANSITIONS = Object.freeze({
  QUEUED: ["PUBLISHING", "FAILED"],
  PUBLISHING: ["SUCCEEDED", "FAILED"],
  SUCCEEDED: [],
  FAILED: ["QUEUED"],
});

export const INQUIRY_TRANSITIONS = Object.freeze({
  NEW: ["CONTACTED", "LOST"],
  CONTACTED: ["QUOTED", "LOST"],
  QUOTED: ["WON", "LOST"],
  WON: [],
  LOST: [],
});
