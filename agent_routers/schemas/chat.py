from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# Enums
# ============================================================================

class Channel(str, Enum):
    """来源渠道标识"""
    WEB = "web"
    API = "api"
    IM = "im"
    BROWSER_EXTENSION = "browser_extension"


class MentionedItemType(str, Enum):
    """提及项类型"""
    KB = "kb"
    FILE = "file"


class KBType(str, Enum):
    """知识库类型"""
    DOCUMENT = "document"
    FAQ = "faq"


class ResponseType(str, Enum):
    """聊天响应类型"""
    AGENT_QUERY = "agent_query"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    REFERENCES = "references"
    ANSWER = "answer"
    REFLECTION = "reflection"
    SESSION_TITLE = "session_title"
    ERROR = "error"


class MessageRole(str, Enum):
    """消息角色"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


# ============================================================================
# Chat - Request Models
# ============================================================================

class MentionedItem(BaseModel):
    """@提及的知识库或文件"""
    id: str = Field(..., description="知识库或文件 ID")
    name: str = Field(..., description="显示名称")
    type: MentionedItemType = Field(..., description="类型：kb 或 file")
    kb_type: KBType | None = Field(None, description="知识库类型（仅 type=kb 时）")


class ChatImage(BaseModel):
    """聊天图片（base64 格式）"""
    data: str = Field(..., description="base64 编码的图片数据，格式：data:image/png;base64,...")


class KnowledgeChatRequest(BaseModel):
    """基于知识库的问答请求"""
    query: str = Field(..., description="查询文本")
    knowledge_base_ids: list[str] = Field(default_factory=list, description="知识库 ID 列表")
    knowledge_ids: list[str] = Field(default_factory=list, description="知识文件 ID 列表")
    agent_id: str | None = Field(None, description="自定义 Agent ID")
    summary_model_id: str | None = Field(None, description="覆盖默认的摘要模型 ID")
    mentioned_items: list[MentionedItem] = Field(default_factory=list, description="@提及的知识库和文件列表")
    disable_title: bool = Field(False, description="是否禁用自动标题生成")
    enable_memory: bool = Field(False, description="是否启用记忆功能")
    images: list[ChatImage] = Field(default_factory=list, description="附带的图片（base64 格式）")
    channel: Channel | None = Field(None, description="来源渠道标识")


class AgentChatRequest(BaseModel):
    """基于 Agent 的智能问答请求"""
    query: str = Field(..., description="查询文本")
    knowledge_base_ids: list[str] = Field(default_factory=list, description="知识库 ID 列表")
    knowledge_ids: list[str] = Field(default_factory=list, description="知识文件 ID 列表")
    agent_enabled: bool = Field(False, description="是否启用 Agent 模式")
    agent_id: str | None = Field(None, description="自定义 Agent ID")
    web_search_enabled: bool = Field(False, description="是否启用网络搜索")
    summary_model_id: str | None = Field(None, description="覆盖默认的摘要模型 ID")
    mentioned_items: list[MentionedItem] = Field(default_factory=list, description="@提及的知识库和文件列表")
    disable_title: bool = Field(False, description="是否禁用自动标题生成")
    enable_memory: bool = Field(False, description="是否启用记忆功能")
    images: list[ChatImage] = Field(default_factory=list, description="附带的图片（base64 格式）")
    channel: Channel | None = Field(None, description="来源渠道标识")


class KnowledgeSearchRequest(BaseModel):
    """基于知识库的搜索请求"""
    query: str = Field(..., description="搜索文本")
    knowledge_base_ids: list[str] = Field(default_factory=list, description="知识库 ID 列表")
    knowledge_ids: list[str] = Field(default_factory=list, description="知识文件 ID 列表")
    top_k: int = Field(5, ge=1, le=50, description="返回结果数量")


# ============================================================================
# Chat - Response Models
# ============================================================================

class KnowledgeReference(BaseModel):
    """知识库检索引用"""
    id: str = Field(..., description="引用 ID")
    content: str = Field(..., description="引用内容")
    knowledge_id: str = Field(..., description="知识文件 ID")
    chunk_index: int = Field(..., description="分块索引")
    knowledge_title: str = Field(..., description="知识标题")
    score: float = Field(..., description="匹配分数")
    match_type: int = Field(..., description="匹配类型")
    chunk_type: str = Field(..., description="分块类型")
    knowledge_filename: str = Field(..., description="知识文件名")


class ToolCallData(BaseModel):
    """工具调用数据"""
    tool_name: str = Field(..., description="工具名称")
    arguments: dict = Field(default_factory=dict, description="工具参数")


class ChatStreamEvent(BaseModel):
    """聊天流式响应事件（SSE）"""
    id: str = Field(..., description="请求/消息 ID")
    response_type: ResponseType = Field(..., description="响应类型")
    content: str = Field(default="", description="响应内容")
    done: bool = Field(False, description="是否完成")
    knowledge_references: list[KnowledgeReference] | None = Field(None, description="知识库引用列表")
    data: ToolCallData | dict | None = Field(None, description="额外数据（如工具调用信息）")


class ChatMessage(BaseModel):
    """聊天消息"""
    id: str = Field(..., description="消息 ID")
    session_id: str = Field(..., description="会话 ID")
    role: MessageRole = Field(..., description="消息角色")
    content: str = Field(..., description="消息内容")
    response_type: ResponseType | None = Field(None, description="响应类型（仅 assistant）")
    knowledge_references: list[KnowledgeReference] | None = Field(None, description="知识库引用")
    tool_calls: list[ToolCallData] | None = Field(None, description="工具调用列表")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class KnowledgeSearchResult(BaseModel):
    """知识库搜索结果"""
    id: str = Field(..., description="结果 ID")
    content: str = Field(..., description="内容片段")
    knowledge_id: str = Field(..., description="知识文件 ID")
    knowledge_title: str = Field(..., description="知识标题")
    score: float = Field(..., description="匹配分数")
    chunk_index: int = Field(..., description="分块索引")


class KnowledgeSearchResponse(BaseModel):
    """知识库搜索响应"""
    success: bool = Field(True, description="是否成功")
    data: list[KnowledgeSearchResult] = Field(default_factory=list, description="搜索结果列表")
    total: int = Field(0, description="总结果数")


# ============================================================================
# Session - Request Models
# ============================================================================

class SessionCreateRequest(BaseModel):
    """创建会话请求"""
    title: str | None = Field(None, description="会话标题")
    description: str | None = Field(None, description="会话描述")


class SessionUpdateRequest(BaseModel):
    """更新会话请求"""
    title: str | None = Field(None, description="会话标题")
    description: str | None = Field(None, description="会话描述")


class SessionBatchDeleteRequest(BaseModel):
    """批量删除会话请求"""
    ids: list[str] = Field(default_factory=list, description="要删除的会话 ID 列表")
    delete_all: bool = Field(False, description="是否删除所有会话")


class GenerateTitleRequest(BaseModel):
    """生成会话标题请求"""
    messages: list["MessageForTitle"] = Field(..., description="用作标题生成上下文的消息列表")


class MessageForTitle(BaseModel):
    """用于生成标题的消息"""
    role: MessageRole = Field(..., description="消息角色")
    content: str = Field(..., description="消息内容")


class StopGenerationRequest(BaseModel):
    """停止生成请求"""
    message_id: str = Field(..., description="要停止生成的助手消息 ID")


class ContinueStreamRequest(BaseModel):
    """继续流式响应请求"""
    message_id: str = Field(..., description="未完成的流式消息 ID")


# ============================================================================
# Session - Response Models
# ============================================================================

class Session(BaseModel):
    """会话"""
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="会话 ID")
    title: str | None = Field(None, description="会话标题")
    description: str | None = Field(None, description="会话描述")
    tenant_id: int | None = Field(None, description="租户 ID")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    deleted_at: datetime | None = Field(None, description="删除时间")


class SessionListResponse(BaseModel):
    """会话列表响应"""
    success: bool = Field(True, description="是否成功")
    data: list[Session] = Field(default_factory=list, description="会话列表")
    total: int = Field(0, description="总数")
    page: int = Field(1, description="当前页码")
    page_size: int = Field(10, description="每页数量")


class SessionDetailResponse(BaseModel):
    """会话详情响应"""
    success: bool = Field(True, description="是否成功")
    data: Session = Field(..., description="会话详情")


class SessionCreateResponse(BaseModel):
    """创建会话响应"""
    success: bool = Field(True, description="是否成功")
    data: Session = Field(..., description="创建的会话")


class SessionUpdateResponse(BaseModel):
    """更新会话响应"""
    success: bool = Field(True, description="是否成功")
    data: Session = Field(..., description="更新后的会话")


class SessionDeleteResponse(BaseModel):
    """删除会话响应"""
    success: bool = Field(True, description="是否成功")
    message: str = Field("Session deleted successfully", description="操作消息")


class SessionClearMessagesResponse(BaseModel):
    """清空会话消息响应"""
    success: bool = Field(True, description="是否成功")
    message: str = Field("Session messages cleared successfully", description="操作消息")


class GenerateTitleResponse(BaseModel):
    """生成标题响应"""
    success: bool = Field(True, description="是否成功")
    data: str = Field(..., description="生成的标题")


class StopGenerationResponse(BaseModel):
    """停止生成响应"""
    success: bool = Field(True, description="是否成功")
    message: str = Field("Generation stopped", description="操作消息")


# ============================================================================
# Pagination
# ============================================================================

class PaginationParams(BaseModel):
    """分页参数"""
    page: int = Field(1, ge=1, description="页码")
    page_size: int = Field(10, ge=1, le=100, description="每页数量")
