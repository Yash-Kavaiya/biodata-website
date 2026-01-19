"""
Neo4j Service - Graph Database Integration.
Handles graph synchronization and similarity queries.
"""
from typing import Dict, List, Any, Optional
from neo4j import GraphDatabase, Driver, AsyncGraphDatabase
from backend.config import settings
from backend.models import BiodataInDB


class Neo4jService:
    """
    Service for interacting with Neo4j Graph Database.
    """

    def __init__(self):
        self.uri = settings.NEO4J_URI
        self.auth = (settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD)
        self.driver: Optional[Driver] = None

    def connect(self):
        """Initialize the Neo4j driver."""
        try:
            # Use synchronous driver for simplicity with async/await wrappers if needed
            # Or use AsyncGraphDatabase from neo4j
            # Since fastAPI is async, let's use the standard driver but run in threadpool or use async driver
            # The prompt used `from neo4j import GraphDatabase`, ensuring compatibility
            self.driver = GraphDatabase.driver(
                self.uri, 
                auth=self.auth
            )
            self.driver.verify_connectivity()
            print("Successfully connected to Neo4j")
        except Exception as e:
            print(f"Failed to connect to Neo4j: {e}")
            self.driver = None

    def close(self):
        """Close the driver connection."""
        if self.driver:
            self.driver.close()

    def sync_biodata(self, biodata: BiodataInDB):
        """
        Sync a biodata record to Neo4j.
        Creates/Merges Person node and links to attributes.
        """
        if not self.driver:
            return

        query = """
        MERGE (p:Person {id: $id})
        SET p.name = $name,
            p.age = $age,
            p.gender = $gender,
            p.file_path = $file_path

        // Link to City
        FOREACH (city IN CASE WHEN $city IS NOT NULL THEN [$city] ELSE [] END |
            MERGE (c:City {name: city})
            MERGE (p)-[:LIVES_IN]->(c)
        )

        // Link to Education
        FOREACH (edu IN CASE WHEN $education IS NOT NULL THEN [$education] ELSE [] END |
            MERGE (e:Education {name: edu})
            MERGE (p)-[:HAS_DEGREE]->(e)
        )

        // Link to Occupation
        FOREACH (occ IN CASE WHEN $occupation IS NOT NULL THEN [$occupation] ELSE [] END |
            MERGE (o:Occupation {name: occ})
            MERGE (p)-[:WORKS_AS]->(o)
        )

        // Link to Religion
        FOREACH (rel IN CASE WHEN $religion IS NOT NULL THEN [$religion] ELSE [] END |
            MERGE (r:Religion {name: rel})
            MERGE (p)-[:BELONGS_TO]->(r)
        )
        
        // Link to Caste
        FOREACH (cst IN CASE WHEN $caste IS NOT NULL THEN [$caste] ELSE [] END |
            MERGE (ct:Caste {name: cst})
            MERGE (p)-[:IS_CASTE]->(ct)
        )
        """

        with self.driver.session(database=settings.NEO4J_DATABASE) as session:
            session.run(
                query,
                id=biodata.id,
                name=biodata.name or "Unknown",
                age=biodata.age,
                gender=biodata.gender,
                file_path=biodata.file_path,
                city=biodata.current_city,
                education=biodata.education,
                occupation=biodata.occupation,
                religion=biodata.religion,
                caste=biodata.caste
            )

    def delete_biodata(self, biodata_id: str):
        """Delete a biodata node from the graph."""
        if not self.driver:
            return

        query = "MATCH (p:Person {id: $id}) DETACH DELETE p"
        
        with self.driver.session(database=settings.NEO4J_DATABASE) as session:
            session.run(query, id=biodata_id)

    def get_graph_data(self) -> Dict[str, Any]:
        """
        Get all nodes and relationships for visualization.
        Returns format compatible with Vis.js or Cytoscape.
        """
        if not self.driver:
            return {"nodes": [], "edges": []}

        query = """
        MATCH (n)-[r]->(m)
        RETURN n, r, m
        LIMIT 200
        """
        
        nodes = {}
        edges = []

        with self.driver.session(database=settings.NEO4J_DATABASE) as session:
            result = session.run(query)
            for record in result:
                n, r, m = record["n"], record["r"], record["m"]
                
                # Process source node
                n_id = n.element_id if hasattr(n, 'element_id') else str(n.id)
                n_label = list(n.labels)[0] if n.labels else "Node"
                n_props = dict(n)
                n_label_text = n_props.get("name", n_label)
                if n_label == "Person":
                    group = "person"
                else:
                    group = n_label.lower()

                if n_id not in nodes:
                    nodes[n_id] = {
                        "id": n_id,
                        "label": n_label_text,
                        "group": group,
                        "title": str(n_props)  # Tooltip
                    }

                # Process target node
                m_id = m.element_id if hasattr(m, 'element_id') else str(m.id)
                m_label = list(m.labels)[0] if m.labels else "Node"
                m_props = dict(m)
                m_label_text = m_props.get("name", m_label)
                if m_label == "Person":
                    group = "person"
                else:
                    group = m_label.lower()

                if m_id not in nodes:
                    nodes[m_id] = {
                        "id": m_id,
                        "label": m_label_text,
                        "group": group,
                        "title": str(m_props)
                    }

                # Process relationship
                edges.append({
                    "from": n_id,
                    "to": m_id,
                    "label": type(r).__name__ if hasattr(type(r), '__name__') else str(r.type),
                    "arrows": "to"
                })

        return {
            "nodes": list(nodes.values()),
            "edges": edges
        }


# Singleton instance
neo4j_service = Neo4jService()
