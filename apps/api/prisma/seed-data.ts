import type { PrismaClient } from "@prisma/client";

const FLOWER_VIDEO =
  "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4";

export async function seedDatabase(prisma: PrismaClient): Promise<void> {
  await prisma.review.deleteMany();
  await prisma.content.deleteMany();

  await prisma.content.create({
    data: {
      contentId: "cnt_ceramic_001",
      merchantId: "mer_jiangnan_001",
      merchantName: "景德镇青屿瓷业",
      productId: "prd_tea_001",
      productTitle: "手绘青花旅行茶具",
      title: "把一座江南，收进随身茶席",
      copy:
        "一壶两杯，轻装出发。高温烧制的青花旅行茶具，釉面温润，收纳后只有掌心大小。无论办公室独饮，还是周末山野，都能随时泡一盏好茶。",
      videoUrl: FLOWER_VIDEO,
      sellingPointsJson: JSON.stringify([
        "高温烧制，釉面温润易清洁",
        "一壶两杯一体收纳，适合旅行携带",
        "手绘青花，每套纹样略有差异",
      ]),
      targetAudience: "注重生活美学的城市白领、茶文化爱好者、旅行人群",
      version: 3,
      status: "PENDING_REVIEW",
      submittedAt: new Date("2026-07-30T04:15:00.000Z"),
    },
  });

  await prisma.content.create({
    data: {
      contentId: "cnt_lamp_002",
      merchantId: "mer_guangming_002",
      merchantName: "宁波光屿家居",
      productId: "prd_lamp_002",
      productTitle: "无频闪磁吸阅读灯",
      title: "夜读不扰人，光线只停在书页上",
      copy:
        "磁吸底座让灯光跟着阅读位置移动，三档色温覆盖夜读、办公和氛围照明。轻触调光，充电后可连续使用。",
      videoUrl: FLOWER_VIDEO,
      sellingPointsJson: JSON.stringify([
        "三档色温与无级亮度调节",
        "磁吸安装，不破坏墙面",
        "低蓝光、无可视频闪",
      ]),
      targetAudience: "学生、租房青年、亲子家庭和夜间阅读人群",
      version: 1,
      status: "PENDING_REVIEW",
      submittedAt: new Date("2026-07-30T03:40:00.000Z"),
    },
  });

  await prisma.content.create({
    data: {
      contentId: "cnt_bag_003",
      merchantId: "mer_linjiang_003",
      merchantName: "泉州林匠户外",
      productId: "prd_bag_003",
      productTitle: "轻量防泼水通勤双肩包",
      title: "通勤和短途旅行，一只包就够",
      copy:
        "自重不足一瓶水，分区却足够清晰。电脑、衣物和随身小物各有位置，表层面料可应对日常小雨。",
      videoUrl: FLOWER_VIDEO,
      sellingPointsJson: JSON.stringify([
        "420 克轻量包体",
        "独立 15.6 英寸电脑仓",
        "表层防泼水面料",
      ]),
      targetAudience: "城市通勤者、大学生、周末短途旅行者",
      version: 2,
      status: "PENDING_REVIEW",
      submittedAt: new Date("2026-07-29T10:20:00.000Z"),
    },
  });

  await prisma.review.create({
    data: {
      reviewId: "rev_bag_003_v1",
      contentId: "cnt_bag_003",
      decision: "REJECTED",
      reasonCode: "MISLEADING_CLAIM",
      comment: "原文使用“绝对防水”，请改为与实际检测能力一致的“日常防泼水”。",
      reviewerId: "op_chen_001",
      reviewerName: "陈晨",
      reviewedAt: new Date("2026-07-28T08:35:00.000Z"),
      contentVersion: 1,
      previousStatus: "PENDING_REVIEW",
      nextStatus: "REJECTED",
    },
  });

  await prisma.content.create({
    data: {
      contentId: "cnt_approved_004",
      merchantId: "mer_jiangnan_001",
      merchantName: "景德镇青屿瓷业",
      productId: "prd_vase_004",
      productTitle: "影青釉小口花器",
      title: "一枝花，也值得一只好花器",
      copy: "影青釉色随光线轻微变化，小口设计让单枝花也能自然成景。",
      videoUrl: FLOWER_VIDEO,
      sellingPointsJson: JSON.stringify(["手工拉坯", "影青釉色", "适合单枝插花"]),
      targetAudience: "家居美学爱好者、花艺初学者",
      version: 1,
      status: "APPROVED",
      submittedAt: new Date("2026-07-28T02:00:00.000Z"),
    },
  });

  await prisma.review.create({
    data: {
      reviewId: "rev_approved_004_v1",
      contentId: "cnt_approved_004",
      decision: "APPROVED",
      comment: "卖点表达清晰，素材完整。",
      reviewerId: "op_chen_001",
      reviewerName: "陈晨",
      reviewedAt: new Date("2026-07-28T03:00:00.000Z"),
      contentVersion: 1,
      previousStatus: "PENDING_REVIEW",
      nextStatus: "APPROVED",
    },
  });
}

