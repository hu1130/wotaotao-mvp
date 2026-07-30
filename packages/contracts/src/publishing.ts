import type {
  AccountId,
  Channel,
  ContentId,
  ErrorCode,
  IdempotentInput,
  IsoDateTime,
  MerchantId,
  Page,
  PaginationQuery,
  ProductId,
  PublicationId,
  PublicationStatus,
} from "./common.js";

export interface AuthorizedAccount {
  accountId: AccountId;
  channel: Channel;
  displayLabel: string;
  available: boolean;
}

export interface AuthorizedAccountsQuery {
  channel: Channel;
}

export interface CreatePublicationInput extends IdempotentInput {
  contentId: ContentId;
  accountId: AccountId;
  channel: Channel;
}

export type RetryPublicationInput = IdempotentInput;

export interface Publication {
  publicationId: PublicationId;
  merchantId: MerchantId;
  contentId: ContentId;
  productId: ProductId;
  channel: Channel;
  accountId: AccountId;
  idempotencyKey: string;
  status: PublicationStatus;
  externalTaskId: string | null;
  externalWorkId: string | null;
  externalUrl: string | null;
  errorCode: ErrorCode | null;
  errorMessage: string | null;
  requestedBy: string;
  publishedAt: IsoDateTime | null;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export interface PublicationListQuery extends PaginationQuery {
  status?: PublicationStatus;
  channel?: Channel;
}

export type PublicationPage = Page<Publication>;

/**
 * Internal adapter boundary after a provider-specific callback has been
 * authenticated and normalized. The external callback body remains
 * provider-specific until the real publishing interface is confirmed.
 */
export interface NormalizedPublicationCallback {
  eventId: string;
  externalTaskId: string;
  status: Extract<PublicationStatus, "SUCCEEDED" | "FAILED">;
  externalWorkId: string | null;
  externalUrl: string | null;
  errorCode: ErrorCode | null;
  errorMessage: string | null;
  occurredAt: IsoDateTime;
  payloadDigest: string;
}

export interface PublicationCallbackAck {
  accepted: boolean;
  duplicate: boolean;
}
