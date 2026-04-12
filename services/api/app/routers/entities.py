from fastapi import APIRouter
from app.schemas.entity import EntitySyncRequest

router = APIRouter(prefix="/entities", tags=["entities"])

@router.get("")
def list_entities():
    raise NotImplementedError

@router.get("/{entity_id}")
def get_entity(entity_id: str):
    raise NotImplementedError

@router.post("/sync")
def sync_entities(body: EntitySyncRequest):
    raise NotImplementedError
