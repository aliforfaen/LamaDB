"""Pydantic models for the Kanban module."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


# ── Users ──────────────────────────────────────────────────

class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    type: str = 'agent'
    status: str = 'active'
    instructions: Optional[str] = None
    last_active_at: Optional[datetime] = None
    api_key_count: int = 0
    open_tasks: int = 0
    completed_tasks: int = 0
    created_at: Optional[datetime] = None


class UserCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    type: str = Field(default='agent', pattern=r'^(human|agent)$')
    instructions: Optional[str] = None


class UserUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    instructions: Optional[str] = None


class UserWithKey(UserProfile):
    api_key: str
    api_key_id: str


class UserDetail(UserProfile):
    api_key_masked: Optional[str] = None
    api_key_id: Optional[str] = None


# ── Boards ─────────────────────────────────────────────────

class KanbanBoardCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    type: str = Field(default='agentic', pattern=r'^(agentic|personal)$')
    instructions: Optional[str] = None


class KanbanBoardUpdate(BaseModel):
    name: Optional[str] = None
    instructions: Optional[str] = None


class KanbanBoard(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    type: str
    instructions: Optional[str] = None
    owner_id: Optional[str] = None
    column_count: int = 0
    task_count: int = 0
    created_at: Optional[datetime] = None


# ── Columns ────────────────────────────────────────────────

class KanbanColumnCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    status: str = Field(..., min_length=1, max_length=50)
    position: int = 0
    wip_limit: Optional[int] = None


class KanbanColumnUpdate(BaseModel):
    name: Optional[str] = None
    position: Optional[int] = None
    wip_limit: Optional[int] = None


class KanbanColumn(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    board_id: str
    name: str
    status: str
    position: int = 0
    wip_limit: Optional[int] = None
    task_count: int = 0


# ── Tasks ──────────────────────────────────────────────────

class KanbanTaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    priority: str = Field(default='medium', pattern=r'^(low|medium|high|critical)$')
    column_id: Optional[str] = None
    assignee_id: Optional[str] = None
    due_at: Optional[datetime] = None
    estimate: Optional[str] = None
    metadata: Optional[dict] = None


class KanbanTaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    due_at: Optional[datetime] = None
    assignee_id: Optional[str] = None
    estimate: Optional[str] = None
    help_wanted: Optional[bool] = None
    help_wanted_message: Optional[str] = None
    metadata: Optional[dict] = None


class KanbanTaskMove(BaseModel):
    column_id: str
    position: int = 0


class KanbanTaskClaim(BaseModel):
    pass


class KanbanTaskComplete(BaseModel):
    summary: Optional[str] = None


class KanbanTask(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    board_id: str
    column_id: str
    task_number: int
    title: str
    description: Optional[str] = None
    priority: str = 'medium'
    due_at: Optional[datetime] = None
    assignee_id: Optional[str] = None
    assignee_name: Optional[str] = None
    position: int = 0
    help_wanted: bool = False
    help_wanted_message: Optional[str] = None
    estimate: Optional[str] = None
    metadata: Optional[dict] = None
    completed_at: Optional[datetime] = None
    subtask_count: int = 0
    subtask_done: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class KanbanTaskDetail(KanbanTask):
    subtasks: list['KanbanSubtask'] = []
    comments: list['KanbanComment'] = []
    dependencies: list['KanbanTaskDependency'] = []


# ── Subtasks ───────────────────────────────────────────────

class KanbanSubtaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)


class KanbanSubtaskUpdate(BaseModel):
    title: Optional[str] = None
    completed: Optional[bool] = None


class KanbanSubtask(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    task_id: str
    title: str
    completed: bool = False
    position: int = 0
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


# ── Dependencies ───────────────────────────────────────────

class KanbanTaskDependencyCreate(BaseModel):
    depends_on_id: str


class KanbanTaskDependency(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    task_id: str
    depends_on_id: str
    depends_on_title: Optional[str] = None
    depends_on_completed: bool = False


# ── Comments ───────────────────────────────────────────────

class KanbanCommentCreate(BaseModel):
    body: str = Field(..., min_length=1)


class KanbanComment(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    task_id: str
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    body: str
    created_at: Optional[datetime] = None


# ── Agent Connect ──────────────────────────────────────────

class AgentConnect(BaseModel):
    user: UserProfile
    api_key_masked: str
    active_boards: list[KanbanBoard]
    my_open_tasks: list[KanbanTask]
    endpoints: dict


# ── Agent Log ──────────────────────────────────────────────

class KanbanAgentLog(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    task_id: Optional[str] = None
    board_id: Optional[str] = None
    action: str
    details: Optional[str] = None
    tool: Optional[str] = None
    created_at: Optional[datetime] = None
