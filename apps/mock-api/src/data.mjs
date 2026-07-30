const FIXED_TIME = "2026-07-30T04:00:00Z";

export function createSeedState() {
  const products = [
    {
      productId: "product_demo_001",
      merchantId: "merchant_demo",
      name: "便携式咖啡机",
      description: "适合差旅与小型办公室使用的便携咖啡机。",
      imageUrls: ["https://example.test/products/coffee-maker.jpg"],
      isPublic: true,
      createdAt: FIXED_TIME,
      updatedAt: FIXED_TIME,
    },
    {
      productId: "product_other_001",
      merchantId: "merchant_other",
      name: "其他商家样例商品",
      description: "用于验证商家数据隔离。",
      imageUrls: ["https://example.test/products/other.jpg"],
      isPublic: false,
      createdAt: FIXED_TIME,
      updatedAt: FIXED_TIME,
    },
  ];

  const contents = [
    {
      contentId: "content_demo_generated",
      merchantId: "merchant_demo",
      productId: "product_demo_001",
      caption: "随时随地，喝一杯现磨咖啡。",
      videoUrl: "https://example.test/content/generated.mp4",
      status: "GENERATED",
      contentVersion: 1,
      createdAt: FIXED_TIME,
      updatedAt: FIXED_TIME,
    },
    {
      contentId: "content_demo_pending",
      merchantId: "merchant_demo",
      productId: "product_demo_001",
      caption: "一键萃取，差旅也能喝到好咖啡。",
      videoUrl: "https://example.test/content/pending.mp4",
      status: "PENDING_REVIEW",
      contentVersion: 1,
      submittedAt: FIXED_TIME,
      createdAt: FIXED_TIME,
      updatedAt: FIXED_TIME,
    },
    {
      contentId: "content_demo_approved",
      merchantId: "merchant_demo",
      productId: "product_demo_001",
      caption: "便携咖啡机，让现磨咖啡随行。",
      videoUrl: "https://example.test/content/approved.mp4",
      status: "APPROVED",
      contentVersion: 1,
      submittedAt: FIXED_TIME,
      createdAt: FIXED_TIME,
      updatedAt: FIXED_TIME,
    },
    {
      contentId: "content_other_generated",
      merchantId: "merchant_other",
      productId: "product_other_001",
      caption: "其他商家的内容。",
      videoUrl: "https://example.test/content/other.mp4",
      status: "GENERATED",
      contentVersion: 1,
      createdAt: FIXED_TIME,
      updatedAt: FIXED_TIME,
    },
  ];

  const accounts = [
    {
      accountId: "account_douyin_demo",
      channel: "DOUYIN",
      displayName: "我淘淘抖音演示账号",
      available: true,
    },
    {
      accountId: "account_xhs_demo",
      channel: "XIAOHONGSHU",
      displayName: "我淘淘小红书演示账号",
      available: true,
    },
  ];

  const publications = [
    {
      publicationId: "publication_demo_success",
      merchantId: "merchant_demo",
      productId: "product_demo_001",
      contentId: "content_demo_approved",
      accountId: "account_douyin_demo",
      channel: "DOUYIN",
      status: "SUCCEEDED",
      externalWorkId: "douyin_work_demo_001",
      externalWorkUrl: "https://example.test/douyin/work/demo-001",
      createdAt: FIXED_TIME,
      updatedAt: FIXED_TIME,
    },
    {
      publicationId: "publication_demo_processing",
      merchantId: "merchant_demo",
      productId: "product_demo_001",
      contentId: "content_demo_approved",
      accountId: "account_xhs_demo",
      channel: "XIAOHONGSHU",
      status: "PUBLISHING",
      createdAt: FIXED_TIME,
      updatedAt: FIXED_TIME,
    },
    {
      publicationId: "publication_demo_failed",
      merchantId: "merchant_demo",
      productId: "product_demo_001",
      contentId: "content_demo_approved",
      accountId: "account_xhs_demo",
      channel: "XIAOHONGSHU",
      status: "FAILED",
      failureReason: "模拟渠道限流",
      createdAt: FIXED_TIME,
      updatedAt: FIXED_TIME,
    },
  ];

  const inquiries = [
    {
      inquiryId: "inquiry_demo_001",
      merchantId: "merchant_demo",
      productId: "product_demo_001",
      contentId: "content_demo_approved",
      publicationId: "publication_demo_success",
      channel: "DOUYIN",
      accountId: "account_douyin_demo",
      buyerName: "演示采购商",
      contact: "138****0000",
      message: "希望了解批量采购价格。",
      status: "NEW",
      createdAt: FIXED_TIME,
      updatedAt: FIXED_TIME,
    },
  ];

  return {
    products: new Map(products.map((item) => [item.productId, item])),
    contents: new Map(contents.map((item) => [item.contentId, item])),
    accounts: new Map(accounts.map((item) => [item.accountId, item])),
    publications: new Map(publications.map((item) => [item.publicationId, item])),
    inquiries: new Map(inquiries.map((item) => [item.inquiryId, item])),
    idempotency: new Map(),
    callbackEvents: new Map(),
    reviews: [],
    auditLog: [],
  };
}
