"""
Graph Service - Neo4j-based graph database for relationship-based similarity search.
Creates a knowledge graph of biodatas with relationships based on shared attributes.
"""
from typing import List, Dict, Any, Optional, Tuple
from neo4j import GraphDatabase, Driver
import logging

from backend.config import settings
from backend.models import BiodataInDB

logger = logging.getLogger(__name__)


class GraphService:
    """
    Neo4j-based graph service for biodata relationships and similarity search.
    Creates nodes for Persons and attribute nodes (Religion, Caste, Location, etc.)
    with relationships between them.
    """

    def __init__(self):
        self._driver: Optional[Driver] = None
        self._initialized = False

    def _get_driver(self) -> Optional[Driver]:
        """Get or create Neo4j driver connection."""
        if self._driver is not None:
            return self._driver

        if not settings.NEO4J_URI or not settings.NEO4J_USERNAME:
            logger.warning("Neo4j not configured. Set NEO4J_URI and credentials in .env")
            return None

        try:
            self._driver = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD)
            )
            self._driver.verify_connectivity()
            self._initialized = True
            logger.info("Connected to Neo4j successfully")
            return self._driver
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {e}")
            return None

    def close(self):
        """Close the Neo4j driver connection."""
        if self._driver:
            self._driver.close()
            self._driver = None
            self._initialized = False

    async def initialize_schema(self):
        """Create indexes and constraints for better performance."""
        driver = self._get_driver()
        if not driver:
            return False

        try:
            with driver.session(database=settings.NEO4J_DATABASE) as session:
                # Create indexes for faster lookups
                session.run("CREATE INDEX person_id IF NOT EXISTS FOR (p:Person) ON (p.biodata_id)")
                session.run("CREATE INDEX religion_name IF NOT EXISTS FOR (r:Religion) ON (r.name)")
                session.run("CREATE INDEX caste_name IF NOT EXISTS FOR (c:Caste) ON (c.name)")
                session.run("CREATE INDEX location_name IF NOT EXISTS FOR (l:Location) ON (l.name)")
                session.run("CREATE INDEX education_name IF NOT EXISTS FOR (e:Education) ON (e.name)")
                session.run("CREATE INDEX occupation_name IF NOT EXISTS FOR (o:Occupation) ON (o.name)")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize schema: {e}")
            return False

    async def add_biodata(self, biodata: BiodataInDB) -> bool:
        """
        Add a biodata to the graph database.
        Creates Person node and relationships to attribute nodes.
        """
        driver = self._get_driver()
        if not driver:
            return False

        try:
            with driver.session(database=settings.NEO4J_DATABASE) as session:
                # Create or merge Person node
                session.run("""
                    MERGE (p:Person {biodata_id: $id})
                    SET p.name = $name,
                        p.age = $age,
                        p.gender = $gender,
                        p.education = $education,
                        p.occupation = $occupation,
                        p.religion = $religion,
                        p.caste = $caste,
                        p.location = $location,
                        p.created_at = datetime()
                """,
                    id=biodata.id,
                    name=biodata.name or "Unknown",
                    age=biodata.age,
                    gender=biodata.gender.value if biodata.gender else None,
                    education=biodata.education,
                    occupation=biodata.occupation,
                    religion=biodata.religion,
                    caste=biodata.caste,
                    location=biodata.current_city or biodata.state
                )

                # Create relationships to attribute nodes
                if biodata.religion:
                    session.run("""
                        MATCH (p:Person {biodata_id: $id})
                        MERGE (r:Religion {name: $religion})
                        MERGE (p)-[:HAS_RELIGION]->(r)
                    """, id=biodata.id, religion=biodata.religion.lower().strip())

                if biodata.caste:
                    session.run("""
                        MATCH (p:Person {biodata_id: $id})
                        MERGE (c:Caste {name: $caste})
                        MERGE (p)-[:HAS_CASTE]->(c)
                    """, id=biodata.id, caste=biodata.caste.lower().strip())

                if biodata.current_city or biodata.state:
                    location = (biodata.current_city or biodata.state).lower().strip()
                    session.run("""
                        MATCH (p:Person {biodata_id: $id})
                        MERGE (l:Location {name: $location})
                        MERGE (p)-[:LIVES_IN]->(l)
                    """, id=biodata.id, location=location)

                if biodata.education:
                    session.run("""
                        MATCH (p:Person {biodata_id: $id})
                        MERGE (e:Education {name: $education})
                        MERGE (p)-[:HAS_EDUCATION]->(e)
                    """, id=biodata.id, education=biodata.education.lower().strip()[:50])

                if biodata.occupation:
                    session.run("""
                        MATCH (p:Person {biodata_id: $id})
                        MERGE (o:Occupation {name: $occupation})
                        MERGE (p)-[:WORKS_AS]->(o)
                    """, id=biodata.id, occupation=biodata.occupation.lower().strip()[:50])

                # Create SIMILAR_TO relationships with other persons sharing attributes
                session.run("""
                    MATCH (p1:Person {biodata_id: $id})
                    MATCH (p2:Person)
                    WHERE p1 <> p2
                    AND (
                        (p1)-[:HAS_RELIGION]->()<-[:HAS_RELIGION]-(p2) OR
                        (p1)-[:HAS_CASTE]->()<-[:HAS_CASTE]-(p2) OR
                        (p1)-[:LIVES_IN]->()<-[:LIVES_IN]-(p2)
                    )
                    MERGE (p1)-[s:SIMILAR_TO]-(p2)
                    SET s.updated_at = datetime()
                """, id=biodata.id)

            return True
        except Exception as e:
            logger.error(f"Failed to add biodata to graph: {e}")
            return False

    async def remove_biodata(self, biodata_id: str) -> bool:
        """Remove a biodata from the graph database."""
        driver = self._get_driver()
        if not driver:
            return False

        try:
            with driver.session(database=settings.NEO4J_DATABASE) as session:
                session.run("""
                    MATCH (p:Person {biodata_id: $id})
                    DETACH DELETE p
                """, id=biodata_id)
            return True
        except Exception as e:
            logger.error(f"Failed to remove biodata from graph: {e}")
            return False

    async def find_similar(self, biodata_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Find similar biodatas using graph traversal.
        Returns persons with shared attributes and similarity score.
        """
        driver = self._get_driver()
        if not driver:
            return []

        try:
            with driver.session(database=settings.NEO4J_DATABASE) as session:
                result = session.run("""
                    MATCH (p1:Person {biodata_id: $id})
                    MATCH (p2:Person)
                    WHERE p1 <> p2
                    OPTIONAL MATCH (p1)-[:HAS_RELIGION]->(r:Religion)<-[:HAS_RELIGION]-(p2)
                    OPTIONAL MATCH (p1)-[:HAS_CASTE]->(c:Caste)<-[:HAS_CASTE]-(p2)
                    OPTIONAL MATCH (p1)-[:LIVES_IN]->(l:Location)<-[:LIVES_IN]-(p2)
                    OPTIONAL MATCH (p1)-[:HAS_EDUCATION]->(e:Education)<-[:HAS_EDUCATION]-(p2)
                    OPTIONAL MATCH (p1)-[:WORKS_AS]->(o:Occupation)<-[:WORKS_AS]-(p2)
                    WITH p2,
                         CASE WHEN r IS NOT NULL THEN 1 ELSE 0 END AS religion_match,
                         CASE WHEN c IS NOT NULL THEN 1 ELSE 0 END AS caste_match,
                         CASE WHEN l IS NOT NULL THEN 1 ELSE 0 END AS location_match,
                         CASE WHEN e IS NOT NULL THEN 1 ELSE 0 END AS education_match,
                         CASE WHEN o IS NOT NULL THEN 1 ELSE 0 END AS occupation_match,
                         r.name AS shared_religion,
                         c.name AS shared_caste,
                         l.name AS shared_location
                    WITH p2,
                         (religion_match * 0.25 + caste_match * 0.2 + location_match * 0.2 +
                          education_match * 0.2 + occupation_match * 0.15) AS score,
                         shared_religion, shared_caste, shared_location
                    WHERE score > 0
                    RETURN p2.biodata_id AS id,
                           p2.name AS name,
                           p2.age AS age,
                           p2.gender AS gender,
                           p2.religion AS religion,
                           p2.caste AS caste,
                           p2.location AS location,
                           p2.education AS education,
                           p2.occupation AS occupation,
                           score,
                           shared_religion,
                           shared_caste,
                           shared_location
                    ORDER BY score DESC
                    LIMIT $limit
                """, id=biodata_id, limit=limit)

                return [dict(record) for record in result]
        except Exception as e:
            logger.error(f"Failed to find similar biodatas: {e}")
            return []

    async def get_graph_data(self, biodata_id: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        """
        Get graph data for visualization.
        Returns nodes and edges suitable for D3.js or similar libraries.
        """
        driver = self._get_driver()
        if not driver:
            return {"nodes": [], "edges": []}

        try:
            with driver.session(database=settings.NEO4J_DATABASE) as session:
                if biodata_id:
                    # Get subgraph centered on specific biodata
                    result = session.run("""
                        MATCH (p1:Person {biodata_id: $id})
                        OPTIONAL MATCH (p1)-[r1]->(attr)
                        OPTIONAL MATCH (p1)-[:SIMILAR_TO]-(p2:Person)
                        OPTIONAL MATCH (p2)-[r2]->(attr2)
                        WITH collect(DISTINCT p1) + collect(DISTINCT p2) AS persons,
                             collect(DISTINCT attr) + collect(DISTINCT attr2) AS attrs,
                             collect(DISTINCT {source: p1.biodata_id, target: id(attr), type: type(r1)}) +
                             collect(DISTINCT {source: p2.biodata_id, target: id(attr2), type: type(r2)}) +
                             collect(DISTINCT {source: p1.biodata_id, target: p2.biodata_id, type: 'SIMILAR_TO'}) AS rels
                        UNWIND persons AS person
                        WITH person, attrs, rels
                        RETURN collect(DISTINCT {
                            id: person.biodata_id,
                            label: person.name,
                            type: 'Person',
                            age: person.age,
                            gender: person.gender,
                            religion: person.religion,
                            caste: person.caste,
                            location: person.location
                        }) AS person_nodes,
                        attrs, rels
                        LIMIT 1
                    """, id=biodata_id)
                else:
                    # Get full graph (limited)
                    result = session.run("""
                        MATCH (p:Person)
                        OPTIONAL MATCH (p)-[:HAS_RELIGION]->(r:Religion)
                        OPTIONAL MATCH (p)-[:HAS_CASTE]->(c:Caste)
                        OPTIONAL MATCH (p)-[:LIVES_IN]->(l:Location)
                        OPTIONAL MATCH (p)-[:SIMILAR_TO]-(p2:Person)
                        WITH p, r, c, l, collect(DISTINCT p2.biodata_id) AS similar_ids
                        RETURN p.biodata_id AS id,
                               p.name AS name,
                               p.age AS age,
                               p.gender AS gender,
                               p.religion AS religion,
                               p.caste AS caste,
                               p.location AS location,
                               r.name AS religion_node,
                               c.name AS caste_node,
                               l.name AS location_node,
                               similar_ids
                        LIMIT $limit
                    """, limit=limit)

                records = list(result)

                nodes = []
                edges = []
                node_ids = set()

                for record in records:
                    rec = dict(record)
                    person_id = rec['id']

                    # Add person node
                    if person_id not in node_ids:
                        nodes.append({
                            "id": person_id,
                            "label": rec['name'] or "Unknown",
                            "type": "Person",
                            "age": rec['age'],
                            "gender": rec['gender'],
                            "religion": rec['religion'],
                            "caste": rec['caste'],
                            "location": rec['location']
                        })
                        node_ids.add(person_id)

                    # Add attribute nodes and edges
                    if rec.get('religion_node'):
                        attr_id = f"religion_{rec['religion_node']}"
                        if attr_id not in node_ids:
                            nodes.append({
                                "id": attr_id,
                                "label": rec['religion_node'].title(),
                                "type": "Religion"
                            })
                            node_ids.add(attr_id)
                        edges.append({
                            "source": person_id,
                            "target": attr_id,
                            "type": "HAS_RELIGION"
                        })

                    if rec.get('caste_node'):
                        attr_id = f"caste_{rec['caste_node']}"
                        if attr_id not in node_ids:
                            nodes.append({
                                "id": attr_id,
                                "label": rec['caste_node'].title(),
                                "type": "Caste"
                            })
                            node_ids.add(attr_id)
                        edges.append({
                            "source": person_id,
                            "target": attr_id,
                            "type": "HAS_CASTE"
                        })

                    if rec.get('location_node'):
                        attr_id = f"location_{rec['location_node']}"
                        if attr_id not in node_ids:
                            nodes.append({
                                "id": attr_id,
                                "label": rec['location_node'].title(),
                                "type": "Location"
                            })
                            node_ids.add(attr_id)
                        edges.append({
                            "source": person_id,
                            "target": attr_id,
                            "type": "LIVES_IN"
                        })

                    # Add SIMILAR_TO edges
                    for similar_id in rec.get('similar_ids', []):
                        if similar_id and similar_id in node_ids:
                            edge_key = tuple(sorted([person_id, similar_id]))
                            edges.append({
                                "source": person_id,
                                "target": similar_id,
                                "type": "SIMILAR_TO"
                            })

                return {"nodes": nodes, "edges": edges}
        except Exception as e:
            logger.error(f"Failed to get graph data: {e}")
            return {"nodes": [], "edges": []}

    async def get_stats(self) -> Dict[str, Any]:
        """Get graph statistics."""
        driver = self._get_driver()
        if not driver:
            return {"connected": False}

        try:
            with driver.session(database=settings.NEO4J_DATABASE) as session:
                result = session.run("""
                    MATCH (p:Person)
                    WITH count(p) AS persons
                    MATCH ()-[r:SIMILAR_TO]-()
                    WITH persons, count(r)/2 AS similarities
                    MATCH (r:Religion)
                    WITH persons, similarities, count(r) AS religions
                    MATCH (c:Caste)
                    WITH persons, similarities, religions, count(c) AS castes
                    MATCH (l:Location)
                    RETURN persons, similarities, religions, castes, count(l) AS locations
                """)
                record = result.single()
                if record:
                    return {
                        "connected": True,
                        "persons": record["persons"],
                        "similarities": record["similarities"],
                        "religions": record["religions"],
                        "castes": record["castes"],
                        "locations": record["locations"]
                    }
                return {"connected": True, "persons": 0, "similarities": 0}
        except Exception as e:
            logger.error(f"Failed to get graph stats: {e}")
            return {"connected": False, "error": str(e)}

    async def clear_graph(self) -> bool:
        """Clear all data from the graph database."""
        driver = self._get_driver()
        if not driver:
            return False

        try:
            with driver.session(database=settings.NEO4J_DATABASE) as session:
                session.run("MATCH (n) DETACH DELETE n")
            return True
        except Exception as e:
            logger.error(f"Failed to clear graph: {e}")
            return False


# Singleton instance
graph_service = GraphService()
