from enum import Enum


class TaskStatus(str, Enum):
    inbox = "inbox"
    ready = "ready"
    running = "running"
    waiting = "waiting"
    needs_approval = "needs_approval"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class Priority(str, Enum):
    low = "low"
    normal = "normal"
    high = "high"
    urgent = "urgent"


class RiskClass(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class OwnerType(str, Enum):
    user = "user"
    agent = "agent"
    system = "system"


class LastDecision(str, Enum):
    none = "none"
    planned = "planned"
    acted = "acted"
    deferred = "deferred"
    asked = "asked"
    ignored = "ignored"
    escalated = "escalated"
