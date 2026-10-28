"""
Graph Router - Neo4j relationship graph (optional; empty results when not configured).
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.routers.biodata import get_or_404
from backend.services import db, graph_service

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("/data")
async def get_graph_data(
    biodata_id: Optional[str] = Query(None, description="Center the graph on one biodata"),
    limit: int = Query(50, ge=1, le=200, description="Max persons to return"),
):
    """Nodes and edges for visualization (`edges` use source/target ids)."""
    return await graph_service.get_graph_data(biodata_id=biodata_id, limit=limit)


@router.get("/stats")
async def get_graph_stats():
    """Neo4j connection status and node counts."""
    return await graph_service.get_stats()


@router.get("/similar/{biodata_id}")
async def get_similar(biodata_id: str, limit: int = Query(10, ge=1, le=50)):
    """Persons sharing attributes with a biodata, by graph traversal."""
    await get_or_404(biodata_id)
    return {"similar": await graph_service.find_similar(biodata_id, limit)}


@router.post("/sync")
async def sync_all():
    """Rebuild the graph from the database: approved biodatas are added, others removed."""
    if not graph_service.configured:
        raise HTTPException(status_code=400, detail="Neo4j is not configured (set NEO4J_URI/NEO4J_USERNAME)")
    await graph_service.initialize_schema()
    biodatas = await db.list_all()
    synced = 0
    for biodata in biodatas:
        if await graph_service.sync(biodata) and biodata.is_approved:
            synced += 1
    return {"total": len(biodatas), "synced": synced, "message": f"Synced {synced} approved biodatas to Neo4j"}
