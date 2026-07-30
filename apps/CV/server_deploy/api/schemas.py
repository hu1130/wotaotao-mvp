"""Request and response schemas for the company integration API."""

from __future__ import annotations

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class EmployeeCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, description="员工姓名")


class EmployeeEnrollRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, description="员工姓名")
    photo_paths: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("photo_paths", "photoPaths", "photos"),
        description="服务端本地照片路径",
    )
    folder: str | None = Field(
        default=None,
        validation_alias=AliasChoices("folder", "photoDir"),
        description="服务端本地照片目录",
    )


class FaceEmbeddingEnrollItem(BaseModel):
    embedding: list[float] = Field(
        ..., min_length=512, max_length=512, description="512维人脸特征"
    )
    angle: str = Field(default="client", max_length=32, description="采集角度或来源")
    photo_path: str = Field(
        default="", validation_alias=AliasChoices("photo_path", "photoPath")
    )


class EmployeeEmbeddingEnrollRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, description="员工姓名")
    embeddings: list[FaceEmbeddingEnrollItem] = Field(
        ..., min_length=1, description="客户端已提取的人脸向量"
    )


class CaptureEnrollRequest(BaseModel):
    name: str = Field(..., min_length=1, description="员工姓名")
    camera_index: int | None = Field(default=None, description="摄像头索引")
    warmup_frames: int | None = Field(
        default=None, ge=0, le=60, description="拍照前预热帧数"
    )


class AttendanceRequest(BaseModel):
    name: str = Field(..., min_length=1, description="员工姓名")
    force: bool = Field(default=False, description="忽略当天签到/签退去重")


class KnowledgeIndexRequest(BaseModel):
    paths: list[str] | None = Field(default=None, description="要索引的本地知识库路径")
    reset: bool = Field(default=False, description="索引前是否清空已有知识库索引")


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="检索问题或关键词")
    top_k: int | None = Field(default=None, ge=1, le=20, description="返回片段数量")
    min_score: float | None = Field(default=None, ge=0, description="最低相关性分数")


class KnowledgeAskRequest(BaseModel):
    question: str = Field(..., min_length=1, description="要基于知识库回答的问题")
    top_k: int | None = Field(
        default=None, ge=1, le=20, description="用于回答的片段数量"
    )


class DialogChatRequest(BaseModel):
    text: str = Field(
        ..., min_length=1, max_length=1000, description="用户语音识别后的文本"
    )


class DialogSceneReplyRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    scene: str = Field(..., min_length=1, max_length=80, description="业务话术场景")
    user_text: str = Field(
        default="",
        max_length=1000,
        validation_alias=AliasChoices("user_text", "userText"),
        description="用户语音识别后的文本",
    )
    required_facts: list[str] = Field(
        default_factory=list,
        max_length=12,
        validation_alias=AliasChoices("required_facts", "requiredFacts"),
        description="必须保留的业务事实",
    )
    response_goal: str = Field(
        default="",
        max_length=300,
        validation_alias=AliasChoices("response_goal", "responseGoal"),
        description="本次话术表达目标",
    )
    constraints: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="额外回答约束",
    )
    context: list[dict] = Field(
        default_factory=list,
        max_length=12,
        description="最近对话上下文",
    )
    user_info: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("user_info", "userInfo"),
        description="当前用户信息",
    )


class VoiceTicketRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    device_id: str = Field(
        ...,
        min_length=1,
        max_length=80,
        validation_alias=AliasChoices("device_id", "deviceId"),
        description="票据绑定的前台设备 ID",
    )


class DeviceEnrollmentClaimRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    activation_code: str = Field(
        ...,
        min_length=20,
        max_length=128,
        validation_alias=AliasChoices("activation_code", "activationCode"),
    )
    installation_id: str = Field(
        ...,
        min_length=36,
        max_length=36,
        validation_alias=AliasChoices("installation_id", "installationId"),
    )
    public_key: str = Field(
        ...,
        min_length=40,
        max_length=64,
        validation_alias=AliasChoices("public_key", "publicKey"),
    )
    proof_signature: str = Field(
        ...,
        min_length=80,
        max_length=128,
        validation_alias=AliasChoices("proof_signature", "proofSignature"),
    )
    device_name: str = Field(
        default="",
        max_length=120,
        validation_alias=AliasChoices("device_name", "deviceName"),
    )
    platform_info: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("platform_info", "platformInfo"),
    )


class AvatarBootstrapRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    device_id: str = Field(
        default="",
        max_length=80,
        validation_alias=AliasChoices("device_id", "deviceId"),
    )


class AvatarBootstrapConsumeRequest(BaseModel):
    token: str = Field(..., min_length=32, max_length=256)


class TenantAdminLoginRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    tenant_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        validation_alias=AliasChoices("tenant_id", "tenantId"),
    )
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class TenantDeviceStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(active|revoked)$")


class PlatformClientCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    tenant_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        validation_alias=AliasChoices("tenant_id", "tenantId"),
    )
    tenant_name: str = Field(
        default="",
        max_length=120,
        validation_alias=AliasChoices("tenant_name", "tenantName"),
    )
    username: str = Field(default="admin", min_length=3, max_length=64)
    display_name: str = Field(
        default="企业管理员",
        max_length=120,
        validation_alias=AliasChoices("display_name", "displayName"),
    )
    device_label: str = Field(
        default="",
        max_length=120,
        validation_alias=AliasChoices("device_label", "deviceLabel"),
    )
    ttl_hours: int = Field(
        default=24,
        ge=1,
        le=24 * 30,
        validation_alias=AliasChoices("ttl_hours", "ttlHours"),
    )
    reset_existing_password: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "reset_existing_password", "resetExistingPassword"
        ),
    )


class PlatformActivationCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    label: str = Field(default="", max_length=120)
    ttl_hours: int = Field(
        default=24,
        ge=1,
        le=24 * 30,
        validation_alias=AliasChoices("ttl_hours", "ttlHours"),
    )


class PlatformConsolePasswordResetRequest(BaseModel):
    username: str = Field(default="admin", min_length=3, max_length=64)


class PlatformClientDeleteRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    confirm_tenant_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        validation_alias=AliasChoices("confirm_tenant_id", "confirmTenantId"),
    )
    disable_console_admins: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "disable_console_admins", "disableConsoleAdmins"
        ),
    )


class PlatformDeviceDeleteRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    confirm_device_id: str = Field(
        ...,
        min_length=1,
        max_length=80,
        validation_alias=AliasChoices("confirm_device_id", "confirmDeviceId"),
    )


class TenantAvatarPersonaRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    assistant_name: str = Field(
        default="",
        max_length=40,
        validation_alias=AliasChoices("assistant_name", "assistantName"),
    )
    personality: str = Field(default="", max_length=300)
    speaking_tone: str = Field(
        default="",
        max_length=300,
        validation_alias=AliasChoices("speaking_tone", "speakingTone"),
    )
    extra_instructions: str = Field(
        default="",
        max_length=600,
        validation_alias=AliasChoices("extra_instructions", "extraInstructions"),
    )
    wake_aliases: list[str] = Field(
        default_factory=list,
        max_length=8,
        validation_alias=AliasChoices("wake_aliases", "wakeAliases"),
    )


class ClientTaskCompleteRequest(BaseModel):
    ok: bool = Field(default=True, description="任务是否执行成功")
    result: dict | None = Field(default=None, description="客户端执行结果")
    error: str = Field(default="", description="失败原因")


class ClientTaskCreateRequest(BaseModel):
    action: str = Field(..., min_length=1, max_length=80, description="客户端任务动作")
    payload: dict | None = Field(default=None, description="任务载荷")
    target_device_id: str = Field(
        default="",
        validation_alias=AliasChoices("target_device_id", "targetDeviceId"),
        description="目标客户端设备 ID；为空表示任意客户端可领取",
    )
    required_capabilities: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("required_capabilities", "requiredCapabilities"),
        description="领取该任务所需的客户端能力；为空时由服务端按动作推断",
    )


class RemoteFacePayload(BaseModel):
    track_id: int
    bbox: list[int] = Field(..., min_length=4, max_length=4)
    embedding: list[float] | None = None
    det_score: float = 0.0
    kps: list[list[float]] | None = None
    gender: str | None = None
    fresh_detection: bool = True


class RemoteRecognitionFrameRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    tenant_id: str = Field(
        default="default",
        max_length=64,
        validation_alias=AliasChoices("tenant_id", "tenantId"),
        description="运行租户 ID；当前单租户客户端可省略",
    )
    device_id: str = Field(default="", description="客户端设备 ID")
    frame_width: int = Field(..., gt=0)
    frame_height: int = Field(..., gt=0)
    faces: list[RemoteFacePayload] = Field(default_factory=list)


class ApiResponse(BaseModel):
    ok: bool
    message: str | None = None
    data: dict | list | None = None
