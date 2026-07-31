import type {
  InquiryId,
  InquiryStatus,
  IsoDateTime,
  MerchantId,
  Page,
  PaginationQuery,
  ProductId,
  PublicationId,
  SourceAttribution,
} from "./common.js";

export interface CreateInquiryInput {
  productId: ProductId;
  publicationId?: PublicationId;
  buyerName: string;
  contact: string;
  quantity?: string;
  message: string;
  referrer?: string;
}

export interface InquiryCreated {
  inquiryId: InquiryId;
  status: Extract<InquiryStatus, "NEW">;
  createdAt: IsoDateTime;
}

export interface Inquiry {
  inquiryId: InquiryId;
  merchantId: MerchantId;
  productId: ProductId;
  buyerName: string;
  contact: string;
  quantity: string | null;
  message: string;
  status: InquiryStatus;
  attribution: SourceAttribution;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export interface MerchantInquiriesQuery extends PaginationQuery {
  status?: InquiryStatus;
}

export type InquiryPage = Page<Inquiry>;

export interface InquiryStatusChange {
  fromStatus: InquiryStatus;
  toStatus: InquiryStatus;
  changedBy: string;
  changedAt: IsoDateTime;
  comment: string | null;
}

export interface InquiryDetail extends Inquiry {
  statusHistory: InquiryStatusChange[];
}

export interface UpdateInquiryStatusInput {
  status: InquiryStatus;
  comment?: string;
}
