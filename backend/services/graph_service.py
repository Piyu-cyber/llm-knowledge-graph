from backend.db.neo4j_driver import Neo4jDriver


class GraphService:
    def __init__(self):
        self.db = Neo4jDriver()

    def create_concept(self, name, description=""):
        query = """
        MERGE (c:Concept {name: $name})
        SET c.description = $description
        RETURN c
        """
        return self.db.run_query(query, {
            "name": name,
            "description": description
        })

    def get_graph(self):
        query = """
        MATCH (n) RETURN n
        """
        return self.db.run_query(query)

    def insert_from_llm(self, data):
        concepts = data.get("concepts", [])
        relationships = data.get("relationships", [])

        # ✅ Insert concepts WITH description 🔥
        for concept in concepts:
            name = concept.get("name")
            description = concept.get("description", "")

            if not name:
                continue

            self.db.run_query(
                """
                MERGE (c:Concept {name: $name})
                SET c.description = $description
                """,
                {
                    "name": name,
                    "description": description
                }
            )

        # ✅ Insert relationships (DYNAMIC TYPE)
        for rel in relationships:
            from_node = rel.get("from")
            to_node = rel.get("to")
            rel_type = rel.get("type", "RELATED")

            if not from_node or not to_node:
                continue

            rel_type = rel_type.upper().replace(" ", "_").replace("/", "_")

            query = f"""
            MATCH (a:Concept {{name: $from}}),
                  (b:Concept {{name: $to}})
            MERGE (a)-[:{rel_type}]->(b)
            """

            self.db.run_query(
                query,
                {
                    "from": from_node,
                    "to": to_node
                }
            )

        return {
            "status": "success",
            "concepts_added": len(concepts),
            "relationships_added": len(relationships)
        }

    # ✅ SEARCH WITH DESCRIPTION (CRITICAL FIX 🔥)
    def search_concepts(self, keyword):
        query = """
        MATCH (c:Concept)
        WHERE toLower(c.name) CONTAINS toLower($keyword)
        RETURN c.name AS name, c.description AS description
        LIMIT 10
        """
        return self.db.run_query(query, {"keyword": keyword})