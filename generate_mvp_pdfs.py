from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Sequence

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(ROOT, "output", "pdf")

PAGE_W, PAGE_H = A4
MARGIN_X = 18 * mm
MARGIN_TOP = 21 * mm
MARGIN_BOTTOM = 18 * mm

NAVY = colors.HexColor("#0F172A")
BLUE = colors.HexColor("#2563EB")
BLUE_DARK = colors.HexColor("#1D4ED8")
BLUE_LIGHT = colors.HexColor("#EFF6FF")
SLATE = colors.HexColor("#475569")
SLATE_LIGHT = colors.HexColor("#E2E8F0")
GRAY_LIGHT = colors.HexColor("#F8FAFC")
GREEN = colors.HexColor("#0F766E")
GREEN_LIGHT = colors.HexColor("#ECFDF5")
AMBER = colors.HexColor("#B45309")
AMBER_LIGHT = colors.HexColor("#FFFBEB")
RED = colors.HexColor("#B91C1C")
WHITE = colors.white


def register_fonts() -> None:
    regular = r"C:\Windows\Fonts\Deng.ttf"
    bold = r"C:\Windows\Fonts\Dengb.ttf"
    pdfmetrics.registerFont(TTFont("Deng", regular))
    pdfmetrics.registerFont(TTFont("Deng-Bold", bold))
    pdfmetrics.registerFontFamily(
        "Deng", normal="Deng", bold="Deng-Bold", italic="Deng", boldItalic="Deng-Bold"
    )


register_fonts()

STYLES = getSampleStyleSheet()
STYLES.add(
    ParagraphStyle(
        name="DocTitleCN",
        fontName="Deng-Bold",
        fontSize=22,
        leading=30,
        textColor=NAVY,
        spaceAfter=5 * mm,
    )
)
STYLES.add(
    ParagraphStyle(
        name="DocSubtitleCN",
        fontName="Deng",
        fontSize=10.5,
        leading=17,
        textColor=SLATE,
        spaceAfter=5 * mm,
    )
)
STYLES.add(
    ParagraphStyle(
        name="H1CN",
        fontName="Deng-Bold",
        fontSize=15,
        leading=21,
        textColor=NAVY,
        spaceBefore=5 * mm,
        spaceAfter=2.5 * mm,
        keepWithNext=True,
    )
)
STYLES.add(
    ParagraphStyle(
        name="H2CN",
        fontName="Deng-Bold",
        fontSize=11.5,
        leading=17,
        textColor=BLUE_DARK,
        spaceBefore=3.5 * mm,
        spaceAfter=1.8 * mm,
        keepWithNext=True,
    )
)
STYLES.add(
    ParagraphStyle(
        name="BodyCN",
        fontName="Deng",
        fontSize=9.2,
        leading=15,
        textColor=NAVY,
        spaceAfter=1.8 * mm,
        wordWrap="CJK",
    )
)
STYLES.add(
    ParagraphStyle(
        name="SmallCN",
        fontName="Deng",
        fontSize=8,
        leading=12,
        textColor=SLATE,
        wordWrap="CJK",
    )
)
STYLES.add(
    ParagraphStyle(
        name="BulletCN",
        fontName="Deng",
        fontSize=9.1,
        leading=14.5,
        textColor=NAVY,
        leftIndent=5 * mm,
        firstLineIndent=-3 * mm,
        bulletIndent=1.2 * mm,
        spaceAfter=1.2 * mm,
        wordWrap="CJK",
    )
)
STYLES.add(
    ParagraphStyle(
        name="CalloutCN",
        fontName="Deng-Bold",
        fontSize=10.3,
        leading=16,
        textColor=BLUE_DARK,
        wordWrap="CJK",
    )
)
STYLES.add(
    ParagraphStyle(
        name="CodeCN",
        fontName="Deng",
        fontSize=7.9,
        leading=12,
        textColor=NAVY,
        backColor=GRAY_LIGHT,
        borderColor=SLATE_LIGHT,
        borderWidth=0.5,
        borderPadding=6,
        leftIndent=2 * mm,
        rightIndent=2 * mm,
        spaceBefore=1.5 * mm,
        spaceAfter=2.5 * mm,
        wordWrap="CJK",
    )
)
STYLES.add(
    ParagraphStyle(
        name="TableHeadCN",
        fontName="Deng-Bold",
        fontSize=8.1,
        leading=11.5,
        textColor=WHITE,
        alignment=TA_LEFT,
        wordWrap="CJK",
    )
)
STYLES.add(
    ParagraphStyle(
        name="TableCellCN",
        fontName="Deng",
        fontSize=7.9,
        leading=11.5,
        textColor=NAVY,
        wordWrap="CJK",
    )
)
STYLES.add(
    ParagraphStyle(
        name="CoverLabelCN",
        fontName="Deng-Bold",
        fontSize=8.5,
        leading=12,
        textColor=BLUE_DARK,
        alignment=TA_CENTER,
    )
)


@dataclass(frozen=True)
class DocSpec:
    filename: str
    code: str
    title: str
    subtitle: str
    summary: str
    owner: str
    content: Sequence[tuple]


class NumberedDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str, title: str, code: str):
        super().__init__(
            filename,
            pagesize=A4,
            leftMargin=MARGIN_X,
            rightMargin=MARGIN_X,
            topMargin=MARGIN_TOP,
            bottomMargin=MARGIN_BOTTOM,
            title=title,
            author="我淘淘项目组",
            subject="我淘淘最小MVP需求文档",
        )
        self.doc_title = title
        self.doc_code = code
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="normal",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates(PageTemplate(id="content", frames=[frame], onPage=self._page))

    def _page(self, canvas, doc) -> None:
        canvas.saveState()
        canvas.setStrokeColor(SLATE_LIGHT)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN_X, PAGE_H - 12.5 * mm, PAGE_W - MARGIN_X, PAGE_H - 12.5 * mm)
        canvas.setFont("Deng", 7.5)
        canvas.setFillColor(SLATE)
        canvas.drawString(MARGIN_X, PAGE_H - 9.4 * mm, f"{self.doc_code}  我淘淘最小MVP")
        title = self.doc_title
        if len(title) > 24:
            title = title[:24] + "…"
        canvas.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 9.4 * mm, title)
        canvas.line(MARGIN_X, 12 * mm, PAGE_W - MARGIN_X, 12 * mm)
        canvas.drawString(MARGIN_X, 8.5 * mm, "内部研发协作文档 · V1.0 · 2026-07-30")
        canvas.drawRightString(PAGE_W - MARGIN_X, 8.5 * mm, f"第 {doc.page} 页")
        canvas.restoreState()


def p(text: str, style: str = "BodyCN") -> Paragraph:
    return Paragraph(text, STYLES[style])


def bullets(items: Iterable[str]) -> list:
    return [Paragraph(f"• {item}", STYLES["BulletCN"]) for item in items]


def code(text: str) -> Paragraph:
    return Paragraph(text.replace("\n", "<br/>"), STYLES["CodeCN"])


def callout(text: str, tone: str = "blue") -> Table:
    if tone == "green":
        bg, border, fg = GREEN_LIGHT, GREEN, GREEN
    elif tone == "amber":
        bg, border, fg = AMBER_LIGHT, AMBER, AMBER
    else:
        bg, border, fg = BLUE_LIGHT, BLUE, BLUE_DARK
    cell_style = ParagraphStyle(
        f"callout-{tone}",
        parent=STYLES["CalloutCN"],
        textColor=fg,
    )
    table = Table([[Paragraph(text, cell_style)]], colWidths=[PAGE_W - 2 * MARGIN_X])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("BOX", (0, 0), (-1, -1), 0.8, border),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def make_table(
    rows: Sequence[Sequence[str]],
    widths: Sequence[float] | None = None,
    header: bool = True,
) -> Table:
    usable = PAGE_W - 2 * MARGIN_X
    if widths is None:
        widths = [usable / len(rows[0])] * len(rows[0])
    else:
        widths = [usable * x for x in widths]
    formatted = []
    for row_index, row in enumerate(rows):
        style = "TableHeadCN" if header and row_index == 0 else "TableCellCN"
        formatted.append([Paragraph(str(cell), STYLES[style]) for cell in row])
    table = Table(formatted, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.45, SLATE_LIGHT),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        commands += [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ]
        if len(rows) > 1:
            commands.append(("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, GRAY_LIGHT]))
    else:
        commands.append(("ROWBACKGROUNDS", (0, 0), (-1, -1), [WHITE, GRAY_LIGHT]))
    table.setStyle(TableStyle(commands))
    return table


def title_block(spec: DocSpec) -> list:
    label = Table(
        [[Paragraph(spec.code, STYLES["CoverLabelCN"])]],
        colWidths=[32 * mm],
        rowHeights=[8 * mm],
    )
    label.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BLUE_LIGHT),
                ("BOX", (0, 0), (-1, -1), 0.6, BLUE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    meta = make_table(
        [
            ["文档版本", "V1.0", "模块负责人", spec.owner],
            ["文档日期", "2026-07-30", "文档状态", "可下发开发"],
        ],
        widths=[0.13, 0.19, 0.15, 0.53],
        header=False,
    )
    return [
        label,
        Spacer(1, 5 * mm),
        p(spec.title, "DocTitleCN"),
        p(spec.subtitle, "DocSubtitleCN"),
        callout(spec.summary),
        Spacer(1, 4 * mm),
        meta,
        Spacer(1, 4 * mm),
    ]


def render_content(content: Sequence[tuple]) -> list:
    story: list = []
    for item in content:
        kind = item[0]
        if kind == "h1":
            story.append(p(item[1], "H1CN"))
        elif kind == "h2":
            story.append(p(item[1], "H2CN"))
        elif kind == "p":
            story.append(p(item[1]))
        elif kind == "small":
            story.append(p(item[1], "SmallCN"))
        elif kind == "bullets":
            story.extend(bullets(item[1]))
        elif kind == "table":
            widths = item[2] if len(item) > 2 else None
            story.append(make_table(item[1], widths=widths))
            story.append(Spacer(1, 2 * mm))
        elif kind == "code":
            story.append(code(item[1]))
        elif kind == "callout":
            tone = item[2] if len(item) > 2 else "blue"
            story.append(callout(item[1], tone))
            story.append(Spacer(1, 2 * mm))
        elif kind == "pagebreak":
            story.append(PageBreak())
        elif kind == "space":
            story.append(Spacer(1, item[1] * mm))
        elif kind == "keep":
            story.append(KeepTogether(render_content(item[1])))
        else:
            raise ValueError(f"Unknown content item: {kind}")
    return story


COMMON_DEFINITIONS = [
    ["对象", "标识字段", "说明"],
    ["商家", "merchantId", "商品、内容、发布和询盘的业务归属主体。"],
    ["商品", "productId", "AI内容生成和买家浏览的核心业务资料。"],
    ["内容", "contentId", "文案、视频及版本信息的统一对象。"],
    ["授权账号", "accountId", "已有发布系统中的授权账号引用；不在MVP保存账号密码或令牌。"],
    ["发布记录", "publicationId", "一次内容向一个渠道账号发布的唯一记录。"],
    ["询盘", "inquiryId", "买家提交的采购或联系意向，必须保存完整来源链路。"],
]

DOCS: list[DocSpec] = [
    DocSpec(
        filename="00_我淘淘最小MVP_整体研发要求.pdf",
        code="MVP-00",
        title="我淘淘最小MVP整体研发要求",
        subtitle="面向技术负责人、产品负责人和各模块开发者的统一范围、架构、接口与验收基线",
        summary="本阶段只完成“商品资料 → AI内容 → 运营审核 → 抖音/小红书自动发布 → 商品浏览 → 可追踪询盘”闭环。所有开发工作必须服务于这一条链路。",
        owner="技术负责人 / 产品负责人",
        content=[
            ("h1", "1. 项目目标"),
            (
                "p",
                "当前目标不是交付完整的全球智能商务平台，而是交付一套可以真实演示、可以接入现有自动发布能力、后续能够持续迭代的最小MVP。",
            ),
            (
                "callout",
                "成功定义：至少一个真实商家录入商品，生成并审核一条内容，通过现有能力发布到抖音或小红书，系统收到作品结果，买家提交询盘，商家能够看到完整来源。",
                "green",
            ),
            ("h2", "1.1 核心业务流程"),
            (
                "code",
                "商家录入商品\n→ AI生成视频和文案\n→ 商家确认并提交审核\n→ 运营审核\n→ 选择已授权账号\n→ 调用现有抖音/小红书发布能力\n→ 回传作品ID、链接和状态\n→ 买家查看商品并提交询盘\n→ 商家查看询盘来源",
            ),
            ("h2", "1.2 本阶段验证的问题"),
            (
                "bullets",
                [
                    "商家是否能够顺利完成从商品资料到内容发布的操作。",
                    "已有抖音、小红书发布能力能否稳定接入我淘淘业务流程。",
                    "外部内容是否能把用户带到商品页面并形成有效询盘。",
                    "每条询盘是否能够追溯到商家、商品、内容、渠道和发布账号。",
                ],
            ),
            ("h1", "2. 项目范围"),
            ("h2", "2.1 必须完成"),
            (
                "table",
                [
                    ["范围", "必须具备的能力", "完成结果"],
                    ["商家与商品", "商家身份、商品新增/编辑/详情、图片资料", "得到可供AI读取的productId"],
                    ["AI内容", "基于商品生成文案和视频、预览、修改、提交审核", "得到contentId及可播放素材"],
                    ["运营审核", "待审核列表、通过、驳回、审核记录", "只有APPROVED内容可发布"],
                    ["自动发布", "账号查询、渠道选择、发布、回调、状态、人工重试", "保存作品ID、作品链接和结果"],
                    ["买家浏览", "视频商品流、商品详情、企业基本信息", "买家能从内容进入商品页"],
                    ["询盘追踪", "询盘提交、商家列表、状态更新、来源字段", "形成可追溯获客闭环"],
                ],
                [0.15, 0.53, 0.32],
            ),
            ("h2", "2.2 明确不做"),
            (
                "table",
                [
                    ["暂不实施", "原因"],
                    ["购物车、在线支付、退款、物流", "第一阶段通过询盘验证商业价值，避免同时建设完整交易系统。"],
                    ["四档套餐、冻结收益、提现", "收费和收益规则尚未进入本次MVP闭环。"],
                    ["七类收益、推广返佣、消费券", "需要独立的财务模型、风控和法律审查。"],
                    ["自动账号匹配和复杂调度", "先人工选账号，积累真实任务数据后再设计匹配规则。"],
                    ["智能体市场与国际化", "与当前获客闭环没有直接依赖。"],
                ],
                [0.34, 0.66],
            ),
            (
                "callout",
                "任何人不得以“以后可能需要”为理由，在本阶段自行增加订单、钱包、收益、分销、微服务或复杂配置中心。",
                "amber",
            ),
            ("h1", "3. 用户角色与权限"),
            (
                "table",
                [
                    ["角色", "主要操作", "权限边界"],
                    ["商家", "管理自己的商品和内容，查看发布记录和询盘", "不能访问其他商家数据；不能读取授权账号秘密信息"],
                    ["运营人员", "审核内容，选择账号并发起发布，处理失败任务", "所有审核和发布操作必须留痕"],
                    ["买家", "浏览公开内容和商品，提交询盘", "无需访问商家后台、账号授权或内部审核信息"],
                ],
                [0.16, 0.42, 0.42],
            ),
            ("h1", "4. 技术结构"),
            (
                "p",
                "MVP采用一个前端应用、一个模块化单体后端和一个主数据库。现有抖音、小红书发布系统作为外部能力，通过统一发布适配层接入。当前不拆微服务。",
            ),
            (
                "code",
                "apps/web  → 一个前端，按角色展示页面\napps/api  → 模块化单体；包含identity、product、content、review、publishing、storefront、inquiry\npackages/contracts  → OpenAPI、共享类型和状态枚举",
            ),
            ("h2", "4.1 模块依赖"),
            (
                "code",
                "公共契约\n  └─ 商品\n      └─ AI内容\n          └─ 审核\n              └─ 自动发布\n                  └─ 买家浏览\n                      └─ 询盘\n                          └─ 集成验收",
            ),
            (
                "p",
                "业务有先后，但代码可以并行开发。前端和下游模块必须依赖packages/contracts中的接口定义，并使用模拟服务等待真实上游完成。",
            ),
            ("h1", "5. 统一数据对象"),
            ("table", COMMON_DEFINITIONS, [0.19, 0.21, 0.60]),
            ("h2", "5.1 状态枚举"),
            (
                "table",
                [
                    ["对象", "允许状态", "主要流转"],
                    ["内容", "DRAFT、GENERATED、PENDING_REVIEW、APPROVED、REJECTED", "生成 → 提交审核 → 通过或驳回"],
                    ["发布", "QUEUED、PUBLISHING、SUCCEEDED、FAILED", "创建 → 发布中 → 成功或失败"],
                    ["询盘", "NEW、CONTACTED、QUOTED、WON、LOST", "新询盘 → 跟进 → 成交或关闭"],
                ],
                [0.16, 0.46, 0.38],
            ),
            (
                "callout",
                "共享对象、状态名称和字段一旦由技术负责人确认，模块开发者不得自行添加近义状态或改变字段含义。",
            ),
            ("h1", "6. 统一接口要求"),
            (
                "bullets",
                [
                    "所有业务对象使用不可复用的唯一ID，禁止用名称作为关联键。",
                    "所有接口返回统一的成功结构和错误结构；错误必须包含稳定errorCode。",
                    "时间统一存储为UTC，接口使用ISO 8601格式，前端按用户时区展示。",
                    "创建发布任务必须携带idempotencyKey，重复请求不得产生重复发布。",
                    "分页接口统一使用page、pageSize，并返回total。",
                    "外部回调必须校验签名或其他可信来源凭据，并保存原始回调摘要。",
                    "商家接口必须按merchantId做数据隔离；授权令牌、密码和Cookie不得返回前端。",
                ],
            ),
            ("h2", "6.1 最小接口清单"),
            (
                "code",
                "POST /products\nGET  /products/{id}\nPOST /contents/generate\nPUT  /contents/{id}\nPOST /contents/{id}/submit-review\nGET  /reviews/pending\nPOST /reviews/{id}/approve\nPOST /reviews/{id}/reject\nGET  /authorized-accounts\nPOST /publications\nPOST /publications/callback\nPOST /publications/{id}/retry\nGET  /feed\nGET  /storefront/products/{id}\nPOST /inquiries\nGET  /merchant/inquiries\nPATCH /inquiries/{id}/status",
            ),
            ("h1", "7. 开发任务和交付顺序"),
            (
                "table",
                [
                    ["任务", "负责人交付", "前置依赖", "验收出口"],
                    ["T0 公共契约", "OpenAPI、类型、状态、模拟数据", "无", "所有模块可基于契约开发"],
                    ["T1 商品", "商品页面、API、表结构", "T0", "生成productId"],
                    ["T2 AI内容", "生成、预览、修改、提交审核", "T0/T1", "生成contentId"],
                    ["T3 审核", "审核队列、结果和记录", "T0/T2", "得到APPROVED内容"],
                    ["T4 发布", "账号、发布、回调、重试", "T0/T3/现有发布接口", "保存外部作品结果"],
                    ["T5 买家浏览", "内容流与商品详情", "T0/T1/T4", "公开内容可浏览"],
                    ["T6 询盘", "提交、列表、状态、归因", "T0/T1/T4", "来源链路完整"],
                    ["T7 集成验收", "端到端联调和发布检查", "T1-T6", "完整闭环通过"],
                ],
                [0.15, 0.35, 0.21, 0.29],
            ),
            ("h1", "8. 通用完成定义"),
            (
                "bullets",
                [
                    "代码已进入约定分支或合并请求，且没有修改无关模块。",
                    "数据库变更有可重复执行的迁移文件，禁止手工改库后不留记录。",
                    "接口符合公共契约；若必须变更，已说明影响并取得技术负责人确认。",
                    "正常路径、权限错误、参数错误和关键异常路径均有测试。",
                    "模块负责人提供启动方式、测试账号、测试步骤和已知限制。",
                    "页面具备加载中、空状态、成功状态和失败状态。",
                    "日志不记录授权令牌、密码、手机号等不必要敏感信息。",
                ],
            ),
            ("h1", "9. MVP最终验收"),
            (
                "table",
                [
                    ["编号", "验收场景", "通过标准"],
                    ["E2E-01", "商品到内容", "真实商家创建商品并生成可播放内容。"],
                    ["E2E-02", "审核门禁", "未通过内容无法创建发布任务。"],
                    ["E2E-03", "真实发布", "至少一个渠道返回成功、作品ID和作品链接。"],
                    ["E2E-04", "发布失败", "失败原因可见，可人工重试且不重复发布。"],
                    ["E2E-05", "公开浏览", "成功作品关联的商品页面可正常访问。"],
                    ["E2E-06", "询盘归因", "询盘保存商家、商品、内容、发布、渠道和账号来源。"],
                    ["E2E-07", "权限隔离", "商家不能访问其他商家数据或授权账号敏感信息。"],
                ],
                [0.14, 0.27, 0.59],
            ),
            ("h1", "10. 团队协作要求"),
            (
                "bullets",
                [
                    "技术负责人先发布公共契约，再分发模块任务。",
                    "每个开发者只处理任务卡范围；发现新需求时先提交问题，不直接扩展。",
                    "公共字段和接口变更必须说明调用方、数据库和前端影响。",
                    "联调问题使用可复现请求、返回、日志编号和环境信息描述。",
                    "每日汇报只回答：完成内容、可联调接口、测试方式、阻塞问题、契约变更、验收状态。",
                ],
            ),
            (
                "small",
                "编制依据：我淘淘全球智能商务平台PRD V0.1、三份业务闭环原型图，以及项目方确认已具备抖音和小红书自动发布能力。现有发布接口的具体字段、鉴权和回调规则仍以实际接口资料为准。",
            ),
        ],
    ),
    DocSpec(
        filename="01_公共契约与基础能力模块_研发要求.pdf",
        code="MVP-01",
        title="公共契约与基础能力模块研发要求",
        subtitle="为所有业务模块提供统一类型、接口规则、角色权限、模拟服务和开发基线",
        summary="本模块先于其他模块交付。它不承载具体业务页面，但决定所有模块如何交换数据、表达状态和处理错误。",
        owner="技术负责人 / 基础开发",
        content=[
            ("h1", "1. 模块目标"),
            (
                "bullets",
                [
                    "冻结MVP共享对象、状态枚举和API字段。",
                    "提供前后端共同使用的OpenAPI或等价契约。",
                    "提供商家、运营人员、买家三种角色的最小权限模型。",
                    "提供模拟数据和模拟接口，使业务模块能够并行开发。",
                ],
            ),
            ("h2", "1.1 负责与不负责"),
            (
                "table",
                [
                    ["负责", "不负责"],
                    ["共享类型、ID、时间、分页、错误结构", "商品、内容、审核、发布和询盘的业务实现"],
                    ["角色识别和接口权限门禁", "完整用户中心、组织架构和复杂RBAC"],
                    ["开发环境配置、API文档、模拟服务", "生产级统一配置中心或微服务治理"],
                    ["审计字段规范和敏感信息规范", "收益、订单、支付和提现安全体系"],
                ],
                [0.50, 0.50],
            ),
            ("h1", "2. 共享对象与标识"),
            ("table", COMMON_DEFINITIONS, [0.19, 0.21, 0.60]),
            (
                "bullets",
                [
                    "所有ID由后端生成并保持全局唯一。",
                    "接口中的ID使用字符串表达，前端不得对ID进行数值计算。",
                    "任何来源追踪都使用ID关联，不使用名称、标题或URL作为唯一关系。",
                    "所有表至少包含createdAt、updatedAt；需要审计的操作增加createdBy、updatedBy。",
                ],
            ),
            ("h1", "3. 共享状态"),
            (
                "table",
                [
                    ["类型", "枚举"],
                    ["ContentStatus", "DRAFT / GENERATED / PENDING_REVIEW / APPROVED / REJECTED"],
                    ["PublicationStatus", "QUEUED / PUBLISHING / SUCCEEDED / FAILED"],
                    ["InquiryStatus", "NEW / CONTACTED / QUOTED / WON / LOST"],
                    ["Channel", "DOUYIN / XIAOHONGSHU"],
                    ["Role", "MERCHANT / OPERATOR / BUYER"],
                ],
                [0.28, 0.72],
            ),
            (
                "callout",
                "状态必须由后端校验流转。前端隐藏按钮不能替代后端权限和状态门禁。",
                "amber",
            ),
            ("h1", "4. API统一规范"),
            ("h2", "4.1 成功和失败结构"),
            (
                "code",
                "成功：\n{\n  \"data\": { ... },\n  \"requestId\": \"req_xxx\"\n}\n\n失败：\n{\n  \"errorCode\": \"CONTENT_NOT_APPROVED\",\n  \"message\": \"内容尚未审核通过\",\n  \"requestId\": \"req_xxx\",\n  \"details\": { ... }\n}",
            ),
            ("h2", "4.2 约定"),
            (
                "bullets",
                [
                    "HTTP状态码表达通用结果，errorCode表达稳定业务错误。",
                    "请求和响应字段统一使用camelCase。",
                    "时间使用ISO 8601 UTC格式，例如2026-07-30T04:00:00Z。",
                    "分页使用page、pageSize，响应返回items、page、pageSize、total。",
                    "创建类接口支持请求追踪；发布创建接口必须支持幂等键。",
                    "接口文档必须包含请求示例、成功示例、错误码和权限要求。",
                ],
            ),
            ("h1", "5. 角色和权限"),
            (
                "table",
                [
                    ["资源", "商家", "运营人员", "买家"],
                    ["商品", "管理自己的商品", "按运营需要只读", "查看公开商品"],
                    ["内容", "管理自己的草稿与查看结果", "查看待审核内容", "仅查看公开内容"],
                    ["审核", "提交和查看结果", "通过或驳回", "无权限"],
                    ["发布", "查看自己的发布记录", "创建、重试和查看", "仅使用公开作品链接"],
                    ["询盘", "查看并更新自己的询盘", "按运营需要只读", "创建自己的询盘"],
                    ["授权凭证", "无权限", "仅发布服务内部使用", "无权限"],
                ],
                [0.20, 0.27, 0.29, 0.24],
            ),
            ("h1", "6. 安全和审计基线"),
            (
                "bullets",
                [
                    "请求上下文必须明确当前角色和merchantId，商家数据查询默认附加merchantId条件。",
                    "不向前端返回账号密码、Cookie、OAuth令牌或现有发布系统的内部凭证。",
                    "运营审核、发布发起、人工重试和询盘状态修改均记录操作者、时间和前后状态。",
                    "日志中的手机号等联系信息按最小必要原则处理，不输出完整授权信息。",
                    "外部回调校验来源，并保存requestId或回调事件ID用于问题追踪。",
                ],
            ),
            ("h1", "7. 模拟服务要求"),
            (
                "bullets",
                [
                    "为商品、内容、审核、账号、发布、公开商品和询盘提供稳定模拟数据。",
                    "模拟接口字段必须与正式契约一致，不得使用一套仅供页面展示的临时字段。",
                    "发布模拟至少覆盖成功、处理中、失败、重复请求四种场景。",
                    "模拟数据使用固定ID，便于各模块进行端到端联调。",
                ],
            ),
            ("h1", "8. 交付物"),
            (
                "table",
                [
                    ["交付物", "要求"],
                    ["OpenAPI文件", "包含MVP全部接口、schema、权限和错误示例。"],
                    ["共享类型", "前端和后端可生成或引用，禁止重复手写近似类型。"],
                    ["模拟服务", "业务模块可独立启动并切换成功/失败场景。"],
                    ["状态说明", "列明允许流转和禁止流转。"],
                    ["权限矩阵", "接口级说明每种角色可执行的操作。"],
                    ["开发说明", "启动命令、环境变量示例和接口地址。"],
                ],
                [0.28, 0.72],
            ),
            ("h1", "9. 验收标准"),
            (
                "bullets",
                [
                    "所有业务模块能够仅根据契约开始开发，共享状态和字段不存在歧义或同义重复。",
                    "模拟接口能够支持完整MVP演示路径；越权访问返回明确错误，商家不能访问其他商家数据。",
                    "发布幂等键、回调事件标识和公共契约变更流程均已定义并明确负责人。",
                ],
            ),
        ],
    ),
    DocSpec(
        filename="02_商品模块_研发要求.pdf",
        code="MVP-02",
        title="商品模块研发要求",
        subtitle="为AI内容生成、公开商品页和询盘归因提供可信商品资料",
        summary="商品模块只负责商家自己的商品资料。它不建设库存、购物车、订单、支付、物流或复杂类目系统。",
        owner="商品模块开发",
        content=[
            ("h1", "1. 模块目标与边界"),
            (
                "p",
                "商家可以创建、编辑、查看和停用商品；AI内容模块可通过productId读取商品资料；买家端只读取允许公开展示的商品字段。",
            ),
            (
                "table",
                [
                    ["必须完成", "明确不做"],
                    ["商品列表、新增、编辑、详情、停用", "库存、SKU矩阵、购物车、订单"],
                    ["商品图片上传与排序", "支付、发货、物流、售后"],
                    ["商品卖点、参数、询价方式", "复杂类目树、促销和优惠券"],
                    ["商家数据隔离和公开字段输出", "供应链、采购需求和跨境配置"],
                ],
                [0.50, 0.50],
            ),
            ("h1", "2. 数据模型"),
            (
                "table",
                [
                    ["字段", "类型/要求", "说明"],
                    ["productId", "string，后端生成", "商品唯一标识"],
                    ["merchantId", "string，必填", "所属商家，不允许前端任意指定"],
                    ["name", "string，必填", "商品名称"],
                    ["summary", "string", "商品简介"],
                    ["sellingPoints", "string[]", "核心卖点，供AI生成使用"],
                    ["images", "object[]", "图片URL、排序和基本元数据"],
                    ["parameters", "key-value[]", "商品参数"],
                    ["priceMode", "FIXED / INQUIRY", "固定展示价格或询价"],
                    ["price", "decimal，可选", "priceMode为FIXED时填写"],
                    ["status", "DRAFT / ACTIVE / INACTIVE", "商品状态"],
                    ["createdAt / updatedAt", "UTC时间", "审计字段"],
                ],
                [0.24, 0.26, 0.50],
            ),
            ("h1", "3. 页面和交互"),
            (
                "bullets",
                [
                    "商品列表：名称、主图、状态、更新时间，并提供新增和编辑入口。",
                    "新增/编辑：名称、图片、简介、卖点、参数、价格方式；必填项即时提示。",
                    "商品详情：展示完整资料及关联内容入口。",
                    "空状态：提示商家先创建商品，再进入AI内容生成。",
                    "保存成功后明确返回productId，并允许直接创建AI内容。",
                ],
            ),
            ("h1", "4. 接口"),
            (
                "code",
                "POST   /products\nGET    /products?page=1&pageSize=20\nGET    /products/{productId}\nPUT    /products/{productId}\nPOST   /products/{productId}/activate\nPOST   /products/{productId}/deactivate\nPOST   /uploads/product-images",
            ),
            ("h2", "4.1 核心规则"),
            (
                "bullets",
                [
                    "merchantId从登录上下文取得，不接受商家在请求体中切换归属。",
                    "商品名称和至少一个卖点为创建AI内容的最低资料要求。",
                    "停用商品不删除历史内容、发布记录和询盘。",
                    "已经被内容引用的商品不得物理删除。",
                    "公开商品接口不得返回内部备注和商家后台字段。",
                ],
            ),
            ("h1", "5. 异常和边界"),
            (
                "table",
                [
                    ["场景", "期望处理"],
                    ["必填字段缺失", "返回PRODUCT_VALIDATION_FAILED及字段级错误。"],
                    ["访问其他商家商品", "返回无权限，不泄露商品是否存在。"],
                    ["图片上传失败", "保留已填写表单并允许单独重试。"],
                    ["停用商品再次生成内容", "阻止生成并提示先恢复商品。"],
                    ["商品被历史内容引用", "允许编辑，但历史发布记录保持原始关联。"],
                ],
                [0.34, 0.66],
            ),
            ("h1", "6. 验收标准"),
            (
                "bullets",
                [
                    "商家能够创建商品并取得productId。",
                    "商家能够查看和编辑自己的商品，不能访问其他商家商品。",
                    "商品图片、卖点和参数能够被AI内容模块读取。",
                    "停用商品不能创建新内容，但历史数据仍可查询。",
                    "页面包含加载、空、成功和失败状态。",
                    "接口、迁移文件和最小测试均已提交。",
                ],
            ),
        ],
    ),
    DocSpec(
        filename="03_AI内容模块_研发要求.pdf",
        code="MVP-03",
        title="AI内容模块研发要求",
        subtitle="基于商品资料生成、预览、修改并提交可审核的营销内容",
        summary="本模块把productId转化为contentId及文案、视频素材。它不负责审核决定、账号选择和第三方发布。",
        owner="AI内容模块开发",
        content=[
            ("h1", "1. 模块目标与范围"),
            (
                "table",
                [
                    ["负责", "不负责"],
                    ["选择商品并读取商品资料", "商品资料维护"],
                    ["填写目标客户、卖点、风格和时长", "完整营销投放策略"],
                    ["调用现有或选定的AI生成能力", "训练自有基础模型"],
                    ["预览、修改、保存、版本记录", "运营审核和第三方发布"],
                    ["提交审核并更新状态", "授权账号和任务收益"],
                ],
                [0.50, 0.50],
            ),
            ("h1", "2. 核心流程"),
            (
                "code",
                "选择productId\n→ 读取商品名称、图片和卖点\n→ 填写目标客户、补充卖点、风格、时长\n→ 创建生成任务\n→ 返回处理中状态\n→ 生成文案和视频\n→ 商家预览与修改\n→ 保存为GENERATED\n→ 提交审核为PENDING_REVIEW",
            ),
            ("h1", "3. 数据模型"),
            (
                "table",
                [
                    ["字段", "要求", "说明"],
                    ["contentId", "string", "内容唯一标识"],
                    ["merchantId", "string", "所属商家"],
                    ["productId", "string", "来源商品"],
                    ["title", "string", "内容标题"],
                    ["copy", "text", "发布文案或口播文案"],
                    ["videoUrl", "URL", "可播放视频素材"],
                    ["targetAudience", "string", "目标客户"],
                    ["style", "string/enum", "内容风格"],
                    ["duration", "integer", "目标时长，单位秒"],
                    ["status", "ContentStatus", "内容状态"],
                    ["generationRequestId", "string", "AI生成任务追踪ID"],
                    ["version", "integer", "修改版本号"],
                ],
                [0.26, 0.24, 0.50],
            ),
            ("h1", "4. 状态与规则"),
            (
                "table",
                [
                    ["当前状态", "允许操作", "目标状态"],
                    ["DRAFT", "补充参数、发起生成", "GENERATED或保持DRAFT"],
                    ["GENERATED", "预览、修改、再次生成、提交审核", "PENDING_REVIEW"],
                    ["PENDING_REVIEW", "查看", "由审核模块处理"],
                    ["APPROVED", "查看、进入发布", "状态不由本模块修改"],
                    ["REJECTED", "根据原因修改并重新提交", "PENDING_REVIEW"],
                ],
                [0.22, 0.46, 0.32],
            ),
            (
                "callout",
                "生成任务可能耗时，接口应返回任务标识并支持查询状态；不要让一个HTTP请求无限等待。",
                "amber",
            ),
            ("h1", "5. 页面要求"),
            (
                "bullets",
                [
                    "创建向导：选择商品、目标客户、卖点、风格和时长。",
                    "生成中：显示明确进度状态，可离开后返回查看。",
                    "内容编辑：文案可修改，视频可预览，显示当前版本。",
                    "失败状态：展示可理解的失败原因和重新生成入口。",
                    "提交审核：二次确认内容和关联商品，成功后进入只读等待状态。",
                ],
            ),
            ("h1", "6. 接口"),
            (
                "code",
                "POST /contents/generate\nGET  /contents/{contentId}\nGET  /contents/{contentId}/generation-status\nPUT  /contents/{contentId}\nPOST /contents/{contentId}/regenerate\nPOST /contents/{contentId}/submit-review",
            ),
            ("h2", "6.1 生成请求示例"),
            (
                "code",
                "{\n  \"productId\": \"prd_001\",\n  \"targetAudience\": \"餐饮渠道采购负责人\",\n  \"sellingPoints\": [\"源头工厂\", \"支持定制\"],\n  \"style\": \"PROFESSIONAL\",\n  \"duration\": 30\n}",
            ),
            ("h1", "7. 异常处理"),
            (
                "table",
                [
                    ["场景", "处理"],
                    ["商品不存在或不属于当前商家", "拒绝生成，不泄露其他商家信息。"],
                    ["商品资料不足", "返回缺失字段，提示先完善商品。"],
                    ["AI服务超时", "任务标记失败，保留输入并允许重试。"],
                    ["视频素材不可播放", "不得进入提交审核，提示重新生成或替换。"],
                    ["重复点击生成", "使用请求标识避免短时间创建重复任务。"],
                    ["审核中尝试修改", "拒绝修改，要求等待结果或由运营退回。"],
                ],
                [0.34, 0.66],
            ),
            ("h1", "8. 验收标准"),
            (
                "bullets",
                [
                    "能够通过productId生成并保存文案和可播放视频。",
                    "生成中、成功和失败状态清晰可查询。",
                    "商家能够修改文案并保存版本。",
                    "提交审核后状态正确变为PENDING_REVIEW。",
                    "其他商家不能访问或修改该内容。",
                    "生成失败可以重试，且不丢失原始输入。",
                ],
            ),
        ],
    ),
    DocSpec(
        filename="04_内容审核模块_研发要求.pdf",
        code="MVP-04",
        title="内容审核模块研发要求",
        subtitle="建立发布前的人工审核门禁、驳回反馈和操作审计",
        summary="本模块只决定内容是否允许发布。未通过审核的内容在后端必须被发布模块拒绝。",
        owner="审核模块开发",
        content=[
            ("h1", "1. 模块目标"),
            (
                "bullets",
                [
                    "运营人员查看所有待审核内容及关联商品。",
                    "对内容执行通过或驳回，并提供明确原因。",
                    "保存审核人、审核时间、前后状态和备注。",
                    "向发布模块提供可信的APPROVED状态。",
                ],
            ),
            ("h2", "1.1 不在范围"),
            (
                "bullets",
                [
                    "自动合规模型和完整风控系统。",
                    "商品资质、广告资质和版权的完整法务流程。",
                    "第三方发布、账号匹配和发布失败处理。",
                    "收益、处罚、申诉和黑名单。",
                ],
            ),
            ("h1", "2. 审核流程"),
            (
                "code",
                "PENDING_REVIEW\n  ├─ 运营通过 → APPROVED → 可创建发布任务\n  └─ 运营驳回 → REJECTED → 商家修改后重新提交",
            ),
            ("h1", "3. 页面要求"),
            (
                "table",
                [
                    ["页面", "内容"],
                    ["待审核列表", "商家、商品、标题、提交时间、当前状态；支持按时间和商家筛选。"],
                    ["审核详情", "视频预览、文案、商品卖点、目标客户、版本和历史审核结果。"],
                    ["通过操作", "确认通过，写入审核记录。"],
                    ["驳回操作", "必须选择或填写原因，原因对商家可见。"],
                ],
                [0.24, 0.76],
            ),
            ("h1", "4. 数据与接口"),
            (
                "table",
                [
                    ["字段", "说明"],
                    ["reviewId", "审核记录唯一ID"],
                    ["contentId", "被审核内容"],
                    ["decision", "APPROVED或REJECTED"],
                    ["reasonCode", "结构化驳回原因，可选"],
                    ["comment", "运营备注；驳回时必填"],
                    ["reviewerId", "审核人员"],
                    ["reviewedAt", "审核时间"],
                    ["contentVersion", "本次审核对应的内容版本"],
                ],
                [0.29, 0.71],
            ),
            (
                "code",
                "GET  /reviews/pending?page=1&pageSize=20\nGET  /reviews/{contentId}\nPOST /reviews/{contentId}/approve\nPOST /reviews/{contentId}/reject\nGET  /contents/{contentId}/review-history",
            ),
            ("h1", "5. 业务规则"),
            (
                "bullets",
                [
                    "只有PENDING_REVIEW状态允许审核。",
                    "驳回必须填写原因；通过可以填写内部备注。",
                    "审核结果关联明确的contentVersion，内容修改后必须重新审核。",
                    "同一内容被两名运营同时打开时，后提交者收到状态已变化提示。",
                    "审核记录只追加，不覆盖历史记录。",
                    "发布模块必须自行再次检查APPROVED，不能只依赖前端按钮。",
                ],
            ),
            ("h1", "6. 验收标准"),
            (
                "bullets",
                [
                    "运营人员能看到待审核队列和完整内容预览。",
                    "通过后内容状态为APPROVED，驳回后为REJECTED。",
                    "驳回原因对商家可见，商家修改后能够重新提交。",
                    "同一版本不会被重复审核产生冲突结果。",
                    "审核历史包含操作者、时间、版本和结果。",
                    "非运营角色无法调用审核接口。",
                ],
            ),
        ],
    ),
    DocSpec(
        filename="05_抖音小红书自动发布模块_研发要求.pdf",
        code="MVP-05",
        title="抖音 / 小红书自动发布模块研发要求",
        subtitle="复用现有官方授权与发布能力，统一账号查询、任务创建、结果回调和失败处理",
        summary="本模块不重建抖音或小红书发布系统，只为我淘淘MVP提供统一适配层。实际鉴权、请求字段和回调签名以现有接口资料为准。",
        owner="自动发布模块开发",
        content=[
            ("h1", "1. 模块目标与边界"),
            (
                "table",
                [
                    ["负责", "不负责"],
                    ["查询可用授权账号的脱敏信息", "重新实现第三方账号授权系统"],
                    ["接收审核通过的contentId并创建发布任务", "AI生成和内容审核"],
                    ["调用现有抖音/小红书发布能力", "绕过第三方平台规则或风控"],
                    ["接收回调、保存作品ID、链接和状态", "自动账号匹配算法"],
                    ["失败原因、人工重试、操作审计", "OPC收益、钱包、提现和结算"],
                ],
                [0.50, 0.50],
            ),
            ("h1", "2. 接入结构"),
            (
                "code",
                "我淘淘业务API\n  └─ PublishingService\n      ├─ DouyinPublisher       → 现有抖音发布能力\n      └─ XiaohongshuPublisher  → 现有小红书发布能力\n\n统一输出：publicationId、status、externalWorkId、externalUrl、errorCode",
            ),
            (
                "callout",
                "开发开始前必须取得现有发布能力的接口文档、鉴权方式、账号查询、请求示例、回调字段、错误码、频率限制和测试环境。若资料无法提供，不得自行改为模拟发布，必须由项目方确认。",
                "amber",
            ),
            ("h1", "3. 核心流程"),
            (
                "code",
                "运营选择APPROVED内容\n→ 查询可用授权账号\n→ 选择渠道与账号\n→ 创建publicationId和幂等键\n→ 状态QUEUED\n→ 调用现有发布接口\n→ 状态PUBLISHING\n→ 接收回调\n   ├─ 成功：SUCCEEDED + 作品ID + 链接\n   └─ 失败：FAILED + 错误码 + 原因\n→ 运营查看或人工重试",
            ),
            ("h1", "4. 数据模型"),
            (
                "table",
                [
                    ["字段", "要求", "说明"],
                    ["publicationId", "string", "我淘淘发布记录ID"],
                    ["merchantId", "string", "所属商家"],
                    ["contentId", "string", "审核通过的内容"],
                    ["productId", "string", "冗余保存用于归因查询"],
                    ["channel", "DOUYIN / XIAOHONGSHU", "发布渠道"],
                    ["accountId", "string", "现有系统授权账号引用"],
                    ["idempotencyKey", "string，唯一", "避免重复发布"],
                    ["status", "PublicationStatus", "发布状态"],
                    ["externalTaskId", "string", "现有发布系统任务ID"],
                    ["externalWorkId", "string", "第三方作品ID"],
                    ["externalUrl", "URL", "第三方作品链接"],
                    ["errorCode / errorMessage", "string", "失败信息"],
                    ["requestedBy", "operatorId", "发起运营人员"],
                    ["publishedAt", "UTC时间", "实际发布时间"],
                ],
                [0.25, 0.25, 0.50],
            ),
            ("h1", "5. 接口"),
            (
                "code",
                "GET  /authorized-accounts?channel=DOUYIN\nPOST /publications\nGET  /publications/{publicationId}\nGET  /publications?page=1&pageSize=20\nPOST /publications/{publicationId}/retry\nPOST /publications/callback",
            ),
            ("h2", "5.1 创建请求"),
            (
                "code",
                "{\n  \"contentId\": \"cnt_001\",\n  \"accountId\": \"acc_001\",\n  \"channel\": \"DOUYIN\",\n  \"idempotencyKey\": \"publish-cnt001-acc001-v1\"\n}",
            ),
            ("h2", "5.2 统一结果"),
            (
                "code",
                "{\n  \"publicationId\": \"pub_001\",\n  \"status\": \"SUCCEEDED\",\n  \"externalWorkId\": \"work_123\",\n  \"externalUrl\": \"https://...\",\n  \"errorCode\": null,\n  \"errorMessage\": null\n}",
            ),
            ("h1", "6. 状态机和幂等"),
            (
                "table",
                [
                    ["状态", "进入条件", "允许后续操作"],
                    ["QUEUED", "发布记录已创建", "交给发布执行器"],
                    ["PUBLISHING", "现有发布系统已接受任务", "等待回调或状态查询"],
                    ["SUCCEEDED", "得到可信成功结果", "公开展示、记录作品链接"],
                    ["FAILED", "接口拒绝、超时终止或回调失败", "查看原因、人工重试"],
                ],
                [0.18, 0.45, 0.37],
            ),
            (
                "bullets",
                [
                    "相同idempotencyKey重复提交必须返回同一publicationId或明确重复结果。",
                    "网络超时不能直接视为失败，应先查询现有系统任务状态。",
                    "成功状态原则上不可由普通重试操作覆盖。",
                    "人工重试创建新的执行尝试记录，但保留原publicationId或明确父子关系。",
                    "回调重复到达时不得重复更新业务结果或触发重复后续动作。",
                ],
            ),
            ("h1", "7. 安全要求"),
            (
                "bullets",
                [
                    "商家只看到渠道、脱敏账号标签、发布状态和作品结果。",
                    "第三方授权令牌、密码、Cookie和内部鉴权信息只存在于现有发布系统或安全服务端。",
                    "回调必须校验签名、事件ID或可信网络来源。",
                    "发布发起、账号选择、重试和状态修正必须记录操作者。",
                    "日志不得输出完整令牌和不必要的个人账号信息。",
                ],
            ),
            ("h1", "8. 错误和重试"),
            (
                "table",
                [
                    ["错误类型", "处理"],
                    ["CONTENT_NOT_APPROVED", "立即拒绝，不调用发布系统。"],
                    ["ACCOUNT_NOT_AVAILABLE", "提示重新选择账号。"],
                    ["RATE_LIMITED", "保存限制信息，按现有接口规则等待或人工处理。"],
                    ["EXTERNAL_TIMEOUT", "先查询任务状态，未知时保持处理中并告警。"],
                    ["CONTENT_REJECTED_BY_CHANNEL", "记录第三方原因，返回运营处理。"],
                    ["CALLBACK_INVALID", "拒绝回调并记录安全日志。"],
                ],
                [0.34, 0.66],
            ),
            ("h1", "9. 验收标准"),
            (
                "bullets",
                [
                    "能够查询抖音和小红书可用授权账号的脱敏信息。",
                    "未审核内容创建发布任务时被后端拒绝。",
                    "至少一个真实测试账号完成发布并保存作品ID和链接。",
                    "发布失败能够保存稳定错误码和可读原因。",
                    "相同幂等键不会产生重复作品。",
                    "重复回调不会重复处理。",
                    "人工重试有独立执行记录并可审计。",
                    "商家无法获得任何账号授权凭证。",
                ],
            ),
        ],
    ),
    DocSpec(
        filename="06_买家浏览与商品落地页模块_研发要求.pdf",
        code="MVP-06",
        title="买家浏览与商品落地页模块研发要求",
        subtitle="承接外部作品流量，展示商品信息并引导买家提交询盘",
        summary="本模块是获客承接页，不是完整电商商城。只展示成功发布的公开内容和商品，并保留来源参数。",
        owner="买家端模块开发",
        content=[
            ("h1", "1. 模块目标与边界"),
            (
                "table",
                [
                    ["必须完成", "明确不做"],
                    ["公开短视频商品流", "个性化推荐算法"],
                    ["商品详情和企业基本信息", "完整企业认证系统"],
                    ["询价入口和来源参数传递", "购物车、支付、物流和售后"],
                    ["公开页面加载、空状态和错误状态", "点赞、评论、社交关系和消费券"],
                ],
                [0.50, 0.50],
            ),
            ("h1", "2. 页面"),
            (
                "table",
                [
                    ["页面", "主要内容", "主要动作"],
                    ["视频商品流", "视频、商品名称、卖点、商家名称", "进入商品详情"],
                    ["商品详情", "视频、图片、参数、卖点、价格/询价方式、商家信息", "立即询价"],
                    ["企业摘要", "企业名称、简介、主营方向", "查看关联商品或询价"],
                    ["结果状态", "内容不存在、商品停用、链接失效", "返回列表或联系客服"],
                ],
                [0.20, 0.53, 0.27],
            ),
            ("h1", "3. 展示规则"),
            (
                "bullets",
                [
                    "内容只有在PublicationStatus为SUCCEEDED时才能进入公开展示。",
                    "公开页面展示商品当前公开资料，但保留publicationId用于归因。",
                    "商品停用后不再出现在新列表中；历史外部链接显示友好不可用状态。",
                    "不向公开接口返回商家内部备注、审核记录、账号详情或运营信息。",
                    "页面必须适配移动端，优先保证从抖音或小红书跳转后的阅读和询价体验。",
                ],
            ),
            ("h1", "4. 来源追踪"),
            (
                "p",
                "进入公开页面时应保存或传递以下来源字段，提交询盘时一并写入。无法取得某字段时保留为空，但不能用名称代替ID。",
            ),
            (
                "p",
                "<b>来源字段：</b>merchantId、productId、contentId、publicationId、channel、accountId、externalWorkId，以及可选的referrer。",
            ),
            ("h1", "5. 接口"),
            (
                "code",
                "GET /feed?page=1&pageSize=20\nGET /storefront/products/{productId}?publicationId=pub_001\nGET /storefront/merchants/{merchantId}\nGET /storefront/publications/{publicationId}",
            ),
            ("h1", "6. 性能和体验"),
            (
                "bullets",
                [
                    "首屏优先加载标题、主图和关键操作，视频允许后续加载。",
                    "视频加载失败时显示封面和重试，不阻止查看商品详情。",
                    "移动端询价按钮保持明显可见，但不得遮挡主要信息。",
                    "页面包含骨架加载、空列表、内容不可用和网络错误状态。",
                    "公开链接具备稳定可分享URL，不依赖登录态才能打开。",
                ],
            ),
            ("h1", "7. 验收标准"),
            (
                "bullets",
                [
                    "只展示发布成功的内容。",
                    "视频与正确的商家和商品关联。",
                    "移动端能够完成浏览、进入详情和点击询价。",
                    "从外部链接进入时保留publicationId和渠道信息。",
                    "停用商品和无效链接显示明确状态，不暴露内部错误。",
                    "不返回授权账号敏感信息和运营内部字段。",
                ],
            ),
        ],
    ),
    DocSpec(
        filename="07_询盘与来源追踪模块_研发要求.pdf",
        code="MVP-07",
        title="询盘与来源追踪模块研发要求",
        subtitle="把买家的采购意向转化为商家可跟进、可归因的业务线索",
        summary="询盘是本次MVP的转化终点。每条询盘必须能够追溯到商家、商品、内容、发布记录、渠道和账号。",
        owner="询盘模块开发",
        content=[
            ("h1", "1. 模块目标与边界"),
            (
                "table",
                [
                    ["负责", "不负责"],
                    ["买家提交姓名、联系方式和需求", "即时聊天和完整CRM"],
                    ["商家查看自己的询盘", "报价单、合同和订单"],
                    ["询盘状态更新和操作记录", "支付、退款和售后"],
                    ["完整来源字段和基本防滥用", "复杂营销归因模型"],
                ],
                [0.50, 0.50],
            ),
            ("h1", "2. 数据模型"),
            (
                "table",
                [
                    ["字段", "要求", "说明"],
                    ["inquiryId", "string", "询盘唯一ID"],
                    ["merchantId", "必填", "线索所属商家"],
                    ["productId", "必填", "询问的商品"],
                    ["contentId", "可选但应尽量保存", "来源内容"],
                    ["publicationId", "可选但外部导流时必填", "来源发布记录"],
                    ["channel / accountId", "来源字段", "发布渠道和账号引用"],
                    ["buyerName", "必填", "买家姓名或称呼"],
                    ["contact", "必填", "手机号、微信或其他联系方式"],
                    ["quantity", "可选", "采购数量"],
                    ["message", "必填", "采购或咨询需求"],
                    ["status", "InquiryStatus", "跟进状态"],
                    ["createdAt / updatedAt", "UTC时间", "审计字段"],
                ],
                [0.27, 0.25, 0.48],
            ),
            ("h1", "3. 状态流转"),
            (
                "code",
                "NEW\n  ├─ 联系买家 → CONTACTED\n  │   ├─ 提交报价 → QUOTED\n  │   │   ├─ 成交 → WON\n  │   │   └─ 未成交 → LOST\n  │   └─ 无效或拒绝 → LOST\n  └─ 暂未处理 → 保持NEW",
            ),
            (
                "bullets",
                [
                    "状态只能由所属商家或具备运营权限的人员修改。",
                    "每次修改记录前后状态、操作者、时间和备注。",
                    "WON和LOST是MVP终态；如需重新打开，应由后续版本单独设计。",
                ],
            ),
            ("h1", "4. 页面"),
            (
                "table",
                [
                    ["页面", "内容"],
                    ["询盘表单", "姓名、联系方式、数量、需求；展示关联商品。"],
                    ["提交结果", "提交成功编号和后续联系提示。"],
                    ["商家询盘列表", "买家、商品、来源渠道、时间、状态。"],
                    ["询盘详情", "完整需求、来源链路、状态记录和更新操作。"],
                ],
                [0.25, 0.75],
            ),
            ("h1", "5. 接口"),
            (
                "code",
                "POST  /inquiries\nGET   /merchant/inquiries?page=1&pageSize=20&status=NEW\nGET   /merchant/inquiries/{inquiryId}\nPATCH /inquiries/{inquiryId}/status",
            ),
            ("h2", "5.1 创建请求示例"),
            (
                "code",
                "{\"productId\":\"prd_001\", \"publicationId\":\"pub_001\", \"buyerName\":\"张先生\",<br/>\"contact\":\"138****0000\", \"quantity\":\"500件\", \"message\":\"需要定制包装，请联系报价\"}",
            ),
            ("h1", "6. 隐私与防滥用"),
            (
                "bullets",
                [
                    "联系方式只向所属商家和必要运营人员展示。",
                    "公开提交接口增加最小限流、重复提交识别和基础输入校验。",
                    "日志避免输出完整联系方式；页面展示按角色决定是否脱敏。",
                    "来源字段由服务端根据publicationId补全，不能完全信任前端提交。",
                    "询盘不允许物理删除，错误或无效询盘使用LOST及原因标记。",
                ],
            ),
            ("h1", "7. 验收标准"),
            (
                "bullets",
                [
                    "买家能够在商品详情页提交询盘；商家只能看到自己的询盘，并能更新状态和查看状态历史。",
                    "外部导流询盘能追溯到publicationId、contentId、productId、channel和accountId；服务端能校验并补全来源。",
                    "重复提交、非法联系方式和越权访问均有明确处理。",
                ],
            ),
        ],
    ),
    DocSpec(
        filename="08_端到端集成与验收模块_研发要求.pdf",
        code="MVP-08",
        title="端到端集成与验收模块研发要求",
        subtitle="统一测试数据、联调顺序、异常场景、发布检查和演示脚本",
        summary="本模块不增加业务功能，负责证明T1至T6能够组成一个可运行、可演示、可追踪的真实闭环。",
        owner="集成负责人 / 测试负责人",
        content=[
            ("h1", "1. 模块目标"),
            (
                "bullets",
                [
                    "建立固定测试商家、商品、内容、授权账号和买家数据。",
                    "按依赖顺序完成接口联调和状态流转验证。",
                    "验证至少一个渠道的真实自动发布。",
                    "验证失败、重试、重复请求和权限隔离。",
                    "形成可重复执行的演示脚本和上线检查表。",
                ],
            ),
            ("h1", "2. 集成范围"),
            (
                "table",
                [
                    ["链路", "必须验证"],
                    ["商品 → 内容", "商品资料正确进入AI生成，contentId关联productId。"],
                    ["内容 → 审核", "提交后进入待审核，版本和状态正确。"],
                    ["审核 → 发布", "只有APPROVED内容能创建任务。"],
                    ["发布 → 公开页面", "成功后保存作品结果并允许公开浏览。"],
                    ["公开页面 → 询盘", "来源参数完整传递并由服务端校验。"],
                    ["询盘 → 商家", "商家看到自己的询盘和完整来源链路。"],
                ],
                [0.30, 0.70],
            ),
            ("h1", "3. 固定测试数据"),
            (
                "table",
                [
                    ["对象", "建议固定数据"],
                    ["商家A", "正常商家，用于完整成功路径。"],
                    ["商家B", "用于权限隔离，不能查看商家A数据。"],
                    ["商品A1", "资料完整，可生成内容。"],
                    ["商品A2", "资料不完整，用于校验失败。"],
                    ["内容A1", "审核通过，用于真实发布。"],
                    ["内容A2", "审核驳回，用于发布门禁。"],
                    ["账号D1 / X1", "抖音和小红书测试授权账号。"],
                    ["买家B1", "用于提交真实测试询盘。"],
                ],
                [0.30, 0.70],
            ),
            ("h1", "4. 联调顺序"),
            (
                "code",
                "阶段1：公共契约 + 商品 + AI内容\n阶段2：审核门禁\n阶段3：发布适配与真实测试账号\n阶段4：公开页面与来源参数\n阶段5：询盘与商家查看\n阶段6：完整端到端回归\n阶段7：失败路径、权限和重复请求",
            ),
            ("h1", "5. 关键测试场景"),
            (
                "table",
                [
                    ["编号", "场景", "预期"],
                    ["IT-01", "完整成功路径", "商品、内容、审核、发布、公开页、询盘全部成功。"],
                    ["IT-02", "资料不足生成", "返回缺失字段，不创建无效内容。"],
                    ["IT-03", "未审核内容发布", "后端拒绝且不调用外部发布服务。"],
                    ["IT-04", "发布接口超时", "先查询状态，不直接创建重复任务。"],
                    ["IT-05", "重复幂等键", "返回同一任务或明确重复，不产生第二个作品。"],
                    ["IT-06", "重复回调", "只处理一次，不重复触发公开动作。"],
                    ["IT-07", "发布失败重试", "保留原失败记录，新尝试可追踪。"],
                    ["IT-08", "商家越权", "商家B不能读取商家A商品、内容和询盘。"],
                    ["IT-09", "来源篡改", "服务端根据publicationId校验并纠正来源。"],
                    ["IT-10", "账号秘密信息", "所有商家和公开接口均不返回凭证。"],
                ],
                [0.13, 0.30, 0.57],
            ),
            ("h1", "6. 发布前检查"),
            (
                "bullets",
                [
                    "所有数据库迁移可以从空库执行成功。",
                    "生产配置不包含测试账号和模拟回调地址。",
                    "外部接口密钥通过安全配置提供，不进入代码仓库。",
                    "回调公网地址、签名校验和重放保护已验证。",
                    "关键日志包含requestId、contentId和publicationId，但不包含令牌。",
                    "错误页面和空状态已验证，移动端公开页面已检查。",
                    "至少执行一次真实渠道发布和一次真实询盘。",
                    "存在明确回滚方式，关闭发布入口不会影响历史数据查询。",
                ],
            ),
            ("h1", "7. 演示脚本"),
            (
                "code",
                "1. 以商家A进入工作台，新建商品A1。\n2. 选择商品A1生成视频和文案，修改后提交审核。\n3. 切换运营角色，查看内容并审核通过。\n4. 选择抖音或小红书测试账号，创建发布任务。\n5. 查看发布状态变为成功，并打开作品链接。\n6. 打开我淘淘商品落地页，提交买家询盘。\n7. 返回商家工作台，查看新询盘及完整来源。\n8. 补充演示一次未审核发布被拒绝或发布失败重试。",
            ),
            ("h1", "8. 最终验收输出"),
            (
                "table",
                [
                    ["交付物", "内容"],
                    ["测试报告", "全部E2E和异常场景结果、证据和遗留问题。"],
                    ["接口版本", "最终OpenAPI版本和变更记录。"],
                    ["演示数据", "可重复使用的测试商家、商品和账号说明。"],
                    ["运行手册", "启动、配置、回调、测试和常见问题。"],
                    ["已知限制", "当前渠道限制、失败场景和人工处理方法。"],
                    ["上线检查表", "配置、安全、迁移、回滚和真实验证结果。"],
                ],
                [0.28, 0.72],
            ),
            ("h1", "9. 完成标准"),
            (
                "callout",
                "只有当完整成功路径、至少一个真实发布、询盘来源追踪、发布失败处理和商家权限隔离全部通过，MVP才算完成。",
                "green",
            ),
        ],
    ),
]


def build_pdf(spec: DocSpec) -> str:
    output_path = os.path.join(OUTPUT_DIR, spec.filename)
    doc = NumberedDocTemplate(output_path, spec.title, spec.code)
    story = title_block(spec)
    story.extend(render_content(spec.content))
    doc.build(story)
    return output_path


def main() -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for spec in DOCS:
        path = build_pdf(spec)
        print(path)


if __name__ == "__main__":
    main()
