import type {
  Channel,
  ContentId,
  IsoDateTime,
  MerchantId,
  Page,
  PaginationQuery,
  ProductId,
  PublicationId,
} from "./common.js";
import type {
  PriceMode,
  ProductImage,
  ProductParameter,
} from "./product.js";

export type FeedQuery = PaginationQuery;

export interface PublicSourceAttribution {
  merchantId: MerchantId;
  productId: ProductId;
  contentId: ContentId | null;
  publicationId: PublicationId | null;
  channel: Channel | null;
  externalWorkId: string | null;
  referrer: string | null;
}

export interface FeedItem {
  publicationId: PublicationId;
  contentId: ContentId;
  productId: ProductId;
  merchantId: MerchantId;
  channel: Channel;
  externalWorkId: string;
  externalUrl: string;
  videoUrl: string;
  title: string;
  productName: string;
  merchantName: string;
  sellingPoints: string[];
  publishedAt: IsoDateTime;
}

export type FeedPage = Page<FeedItem>;

export interface StorefrontProductQuery {
  publicationId?: PublicationId;
}

export interface StorefrontProduct {
  productId: ProductId;
  merchantId: MerchantId;
  merchantName: string;
  name: string;
  summary: string;
  sellingPoints: string[];
  images: ProductImage[];
  parameters: ProductParameter[];
  priceMode: PriceMode;
  price: number | null;
  available: boolean;
  attribution: PublicSourceAttribution;
}

export interface StorefrontMerchant {
  merchantId: MerchantId;
  name: string;
  summary: string;
  primaryBusiness: string;
}

export interface StorefrontPublication {
  publicationId: PublicationId;
  merchantId: MerchantId;
  productId: ProductId;
  contentId: ContentId;
  channel: Channel;
  externalWorkId: string;
  externalUrl: string;
  publishedAt: IsoDateTime;
}
