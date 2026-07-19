"""Long-term Memory adapters and contracts for Stage 9B."""

from app.memory.errors import (
    MemoryContractError,
    MemoryDocumentStoreError,
    MemoryError,
    MemoryErrorCode,
    MemoryRepositoryError,
)
from app.memory.document_store import MemoryDocumentStore
from app.memory.models import (
    MemoryDocument,
    MemoryConflictCandidate,
    MemoryEntry,
    MemoryIndexRecord,
    MemorySaveResult,
    MemoryStatus,
    MemoryWriteContext,
    decode_memory_tags,
    encode_memory_tags,
    memory_content_hash,
    memory_relative_path,
)
from app.memory.profile import PROFILE_FILENAME, FileProfileProvider
from app.memory.repository import MemoryRepository, SqliteMemoryRepository
from app.memory.retriever import DeterministicMemoryRetriever
from app.memory.service import MemoryConflictError, MemoryService
from app.memory.tools import build_memory_tools

__all__ = (
    "FileProfileProvider",
    "DeterministicMemoryRetriever",
    "MemoryContractError",
    "MemoryConflictCandidate",
    "MemoryConflictError",
    "MemoryDocument",
    "MemoryDocumentStore",
    "MemoryEntry",
    "MemoryDocumentStoreError",
    "MemoryError",
    "MemoryErrorCode",
    "MemoryIndexRecord",
    "MemorySaveResult",
    "MemoryService",
    "MemoryRepositoryError",
    "MemoryRepository",
    "MemoryStatus",
    "MemoryWriteContext",
    "PROFILE_FILENAME",
    "SqliteMemoryRepository",
    "decode_memory_tags",
    "encode_memory_tags",
    "memory_content_hash",
    "memory_relative_path",
    "build_memory_tools",
)
