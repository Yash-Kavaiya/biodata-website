"""
Graph Service - optional Neo4j knowledge graph of approved biodatas.

Person nodes link to attribute nodes (Religion, Caste, Location, Education,
Occupation). Two persons sharing at least two attributes get a SIMILAR_TO edge.
Every method is a safe no-op when Neo4j is not configured or unreachable.
"""
import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from backend.config import settings
from backend.models import BiodataInDB

logger = logging.getLogger(__name__)

# How long to wait before retrying a failed connection
_RECONNECT_BACKOFF_SECONDS = 60.0

# (relationship type, node label, biodata attribute getter)
_ATTRIBUTES = [
    ("HAS_RELIGION", "Religion", lambda b: b.religion),
    ("HAS_CASTE", "Caste", lambda b: b.caste),
    ("LIVES_IN", "Location", lambda b: b.current_city or b.state),
    ("HAS_EDUCATION", "Education", lambda b: b.education),
    ("WORKS_AS", "Occupation", lambda b: b.occupation),
]
_ATTRIBUTE_RELS = "|".join(rel for rel, _, _ in _ATTRIBUTES)
_MIN_SHARED_FOR_SIMILAR = 2


def _normalize(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = " ".join(value.lower().split())[:60]
    return value or None


class GraphService:
    """Neo4j-backed relationship graph."""

    def __init__(self):
        self._driver = None
        self._last_failure: float = 0.0

    @property
    def configured(self) -> bool:
        return bool(settings.NEO4J_URI and settings.NEO4J_USERNAME)

    def _get_driver(self):
        """Get or lazily create the driver; backs off after a failed attempt."""
        if self._driver is not None:
            return self._driver
        if not self.configured:
            return None
        if time.monotonic() - self._last_failure < _RECONNECT_BACKOFF_SECONDS:
            return None
        try:
            from neo4j import GraphDatabase
            driver = GraphDatabase.driver(
                settings.NEO4J_URI, auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD)
            )
            driver.verify_connectivity()
            self._driver = driver
            logger.info("Connected to Neo4j")
        except Exception as e:
            self._last_failure = time.monotonic()
            logger.error(f"Failed to connect to Neo4j: {e}")
        return self._driver

    async def _run(self, work: Callable[[Any], Any], default: Any) -> Any:
        """Run a blocking session callback in a worker thread."""
        def task():
            driver = self._get_driver()
            if driver is None:
                return default
            with driver.session(database=settings.NEO4J_DATABASE) as session:
                return work(session)

        try:
            return await asyncio.to_thread(task)
        except Exception as e:
            logger.error(f"Neo4j operation failed: {e}")
            return default

    def close(self):
        if self._driver:
            self._driver.close()
            self._driver = None

    async def initialize_schema(self) -> bool:
        """Create a uniqueness constraint and lookup indexes."""
        def work(session):
            session.run("CREATE CONSTRAINT person_id IF NOT EXISTS FOR (p:Person) REQUIRE p.biodata_id IS UNIQUE")
            for _, label, _ in _ATTRIBUTES:
                session.run(f"CREATE INDEX {label.lower()}_name IF NOT EXISTS FOR (n:{label}) ON (n.name)")
            return True
        return await self._run(work, False)

    async def add_biodata(self, biodata: BiodataInDB) -> bool:
        """Create or refresh a Person node, its attribute links and SIMILAR_TO edges."""
        attributes = [
            {"rel": rel, "label": label, "name": _normalize(get(biodata))}
            for rel, label, get in _ATTRIBUTES
        ]

        def work(session):
            def tx_work(tx):
                tx.run(
                    """
                    MERGE (p:Person {biodata_id: $id})
                    SET p.name = $name, p.age = $age, p.gender = $gender,
                        p.religion = $religion, p.caste = $caste, p.location = $location,
                        p.education = $education, p.occupation = $occupation
                    WITH p
                    OPTIONAL MATCH (p)-[old]-()
                    WHERE type(old) IN $rel_types OR type(old) = 'SIMILAR_TO'
                    DELETE old
                    """,
                    id=biodata.id,
                    name=biodata.name or "Unknown",
                    age=biodata.age,
                    gender=biodata.gender.value if biodata.gender else None,
                    religion=biodata.religion,
                    caste=biodata.caste,
                    location=biodata.current_city or biodata.state,
                    education=biodata.education,
                    occupation=biodata.occupation,
                    rel_types=[rel for rel, _, _ in _ATTRIBUTES],
                )
                for attr in attributes:
                    if attr["name"]:
                        # Labels/types can't be parameterized; they come from our constant list
                        tx.run(
                            f"MATCH (p:Person {{biodata_id: $id}}) "
                            f"MERGE (a:{attr['label']} {{name: $name}}) "
                            f"MERGE (p)-[:{attr['rel']}]->(a)",
                            id=biodata.id, name=attr["name"],
                        )
                tx.run(
                    f"""
                    MATCH (p1:Person {{biodata_id: $id}})-[:{_ATTRIBUTE_RELS}]->(a)<-[:{_ATTRIBUTE_RELS}]-(p2:Person)
                    WHERE p1 <> p2
                    WITH p1, p2, count(DISTINCT a) AS shared
                    WHERE shared >= $min_shared
                    MERGE (p1)-[s:SIMILAR_TO]-(p2)
                    SET s.shared = shared
                    """,
                    id=biodata.id, min_shared=_MIN_SHARED_FOR_SIMILAR,
                )
            session.execute_write(tx_work)
            return True
        return await self._run(work, False)

    async def sync(self, biodata: BiodataInDB) -> bool:
        """Keep the graph in step with a record: only approved biodatas belong in it."""
        if biodata.is_approved:
            return await self.add_biodata(biodata)
        return await self.remove_biodata(biodata.id)

    async def remove_biodata(self, biodata_id: str) -> bool:
        def work(session):
            session.run("MATCH (p:Person {biodata_id: $id}) DETACH DELETE p", id=biodata_id)
            return True
        return await self._run(work, False)

    async def find_similar(self, biodata_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Persons sharing attributes with the given biodata, ranked by weighted overlap."""
        def work(session):
            result = session.run(
                f"""
                MATCH (p1:Person {{biodata_id: $id}})-[r1:{_ATTRIBUTE_RELS}]->(a)<-[r2]-(p2:Person)
                WHERE p1 <> p2 AND type(r1) = type(r2)
                WITH p2, collect(DISTINCT type(r1)) AS rels, collect(DISTINCT a.name) AS shared
                WITH p2, shared,
                     reduce(s = 0.0, r IN rels | s + CASE r
                        WHEN 'HAS_RELIGION' THEN 0.25 WHEN 'HAS_CASTE' THEN 0.2
                        WHEN 'LIVES_IN' THEN 0.2 WHEN 'HAS_EDUCATION' THEN 0.2
                        ELSE 0.15 END) AS score
                RETURN p2.biodata_id AS id, p2.name AS name, p2.age AS age, p2.gender AS gender,
                       p2.location AS location, score, shared
                ORDER BY score DESC
                LIMIT $limit
                """,
                id=biodata_id, limit=limit,
            )
            return [dict(record) for record in result]
        return await self._run(work, [])

    async def get_graph_data(self, biodata_id: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        """
        Nodes and edges for visualization. With `biodata_id`, returns that person
        and their SIMILAR_TO neighbours; otherwise up to `limit` persons.
        """
        def work(session):
            persons = session.run(
                f"""
                MATCH (p:Person)
                WHERE $id IS NULL OR p.biodata_id = $id
                   OR EXISTS {{ (p)-[:SIMILAR_TO]-(:Person {{biodata_id: $id}}) }}
                WITH p LIMIT $limit
                OPTIONAL MATCH (p)-[r:{_ATTRIBUTE_RELS}]->(a)
                RETURN p.biodata_id AS id, p.name AS name, p.age AS age, p.gender AS gender,
                       collect(CASE WHEN a IS NULL THEN NULL
                               ELSE {{rel: type(r), label: labels(a)[0], name: a.name}} END) AS attrs
                """,
                id=biodata_id, limit=limit,
            ).data()
            ids = [p["id"] for p in persons]
            similar = session.run(
                """
                MATCH (a:Person)-[s:SIMILAR_TO]-(b:Person)
                WHERE a.biodata_id IN $ids AND b.biodata_id IN $ids AND a.biodata_id < b.biodata_id
                RETURN a.biodata_id AS source, b.biodata_id AS target, s.shared AS shared
                """,
                ids=ids,
            ).data()
            return persons, similar

        result = await self._run(work, None)
        if result is None:
            return {"nodes": [], "edges": []}
        persons, similar = result

        nodes: Dict[str, Dict[str, Any]] = {}
        edges: List[Dict[str, Any]] = []
        for person in persons:
            nodes[person["id"]] = {
                "id": person["id"],
                "label": person["name"] or "Unknown",
                "type": "Person",
                "gender": person["gender"],
                "age": person["age"],
            }
            for attr in person["attrs"]:
                attr_id = f"{attr['label'].lower()}:{attr['name']}"
                nodes.setdefault(attr_id, {"id": attr_id, "label": attr["name"].title(), "type": attr["label"]})
                edges.append({"source": person["id"], "target": attr_id, "type": attr["rel"]})
        for s in similar:
            edges.append({"source": s["source"], "target": s["target"], "type": "SIMILAR_TO", "shared": s["shared"]})

        return {"nodes": list(nodes.values()), "edges": edges}

    async def get_stats(self) -> Dict[str, Any]:
        if not self.configured:
            return {"configured": False, "connected": False}

        def work(session):
            record = session.run(
                """
                RETURN COUNT { (:Person) } AS persons,
                       COUNT { ()-[:SIMILAR_TO]->() } AS similarities,
                       COUNT { (:Religion) } AS religions,
                       COUNT { (:Caste) } AS castes,
                       COUNT { (:Location) } AS locations
                """
            ).single()
            return {"configured": True, "connected": True, **dict(record)}
        return await self._run(work, {"configured": True, "connected": False})


# Singleton instance
graph_service = GraphService()
