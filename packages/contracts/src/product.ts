import type {
  IsoDateTime,
  MerchantId,
  Page,
  PaginationQuery,
  ProductId,
} from "./common.js";

export const PRODUCT_STATUSES = ["DRAFT", "ACTIVE", "INACTIVE"] as const;
export type ProductStatus = (typeof PRODUCT_STATUSES)[number];

export const PRICE_MODES = ["FIXED", "INQUIRY"] as const;
export type PriceMode = (typeof PRICE_MODES)[number];

export const PRODUCT_STATUS_TRANSITIONS = {
  DRAFT: ["ACTIVE", "INACTIVE"],
  ACTIVE: ["INACTIVE"],
  INACTIVE: ["ACTIVE"],
} as const satisfies Record<ProductStatus, readonly ProductStatus[]>;

export interface ProductImage {
  url: string;
  sortOrder: number;
  altText: string | null;
}

export interface ProductParameter {
  key: string;
  value: string;
}

export interface Product {
  productId: ProductId;
  merchantId: MerchantId;
  name: string;
  summary: string;
  sellingPoints: string[];
  images: ProductImage[];
  parameters: ProductParameter[];
  priceMode: PriceMode;
  price: number | null;
  status: ProductStatus;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export interface ProductSummary {
  productId: ProductId;
  merchantId: MerchantId;
  name: string;
  primaryImageUrl: string | null;
  sellingPoints: string[];
  priceMode: PriceMode;
  price: number | null;
  status: ProductStatus;
  updatedAt: IsoDateTime;
}

export interface CreateProductInput {
  name: string;
  summary?: string;
  sellingPoints: string[];
  images?: ProductImage[];
  parameters?: ProductParameter[];
  priceMode: PriceMode;
  price?: number | null;
}

export type UpdateProductInput = Partial<CreateProductInput>;

export interface ProductListQuery extends PaginationQuery {
  status?: ProductStatus;
}

export type ProductPage = Page<ProductSummary>;

export interface ProductImageUploadResult {
  url: string;
  contentType: string;
  size: number;
}
