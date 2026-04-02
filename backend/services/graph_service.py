from backend.db.neo4j_driver import Neo4jDriver


class GraphService:
    def __init__(self):
        self.db = Neo4jDriver()

    # 🔥 Create / update concept
    def create_concept(self, name, description=""):
        name = (name or "").strip()
        description = (description or "").strip()

        if not name:
            return None

        query = """
        MERGE (c:Concept {name: $name})
        SET c.description = $description
        RETURN c.name AS name, c.description AS description
        """

        return self.db.run_query(query, {
            "name": name,
            "description": description
        })

    # 🔥 Create relationship
    def create_relationship(self, from_node, to_node, rel_type="RELATED"):
        from_node = (from_node or "").strip()
        to_node = (to_node or "").strip()

        if not from_node or not to_node:
            return None

        rel_type = rel_type.upper().replace(" ", "_").replace("/", "_")

        query = f"""
        MATCH (a:Concept {{name: $from}})
        MATCH (b:Concept {{name: $to}})
        MERGE (a)-[:{rel_type}]->(b)
        """

        return self.db.run_query(query, {
            "from": from_node,
            "to": to_node
        })

    # 🔥 Get all concepts
    def get_graph(self):
        query = """
        MATCH (c:Concept)
        RETURN c.name AS name, c.description AS description
        """
        return self.db.run_query(query)

    # 🔥 NEW: Get related concepts (1-hop)
    def get_related_concepts(self, name):
        query = """
        MATCH (a:Concept {name: $name})-[r]->(b:Concept)
        RETURN type(r) AS relation, b.name AS name, b.description AS description
        LIMIT 5
        """
        return self.db.run_query(query, {"name": name})

    # 🔥 NEW: Multi-hop expansion (2-hop reasoning)
    def expand_graph(self, name):
        query = """
        MATCH (a:Concept {name: $name})-[r1]->(b:Concept)-[r2]->(c:Concept)
        RETURN 
            b.name AS intermediate,
            type(r1) AS rel1,
            c.name AS name,
            type(r2) AS rel2,
            c.description AS description
        LIMIT 5
        """
        return self.db.run_query(query, {"name": name})

    # 🔥 Bulk insert
    def insert_from_llm(self, data):
        concepts = data.get("concepts", [])
        relationships = data.get("relationships", [])

        for concept in concepts:
            name = (concept.get("name") or "").strip()
            description = (concept.get("description") or "").strip()

            if name.lower().startswith("name:"):
                name = name.split(":", 1)[1].strip()

            if not name or len(name) < 2:
                continue

            if name.lower() in ["concept", "thing", "item"]:
                continue

            self.create_concept(name, description)

        for rel in relationships:
            from_node = (rel.get("from") or "").strip()
            to_node = (rel.get("to") or "").strip()
            rel_type = (rel.get("type") or "RELATED").strip()

            if not from_node or not to_node:
                continue

            self.create_relationship(from_node, to_node, rel_type)

        return {"status": "success"}

    # 🔥 FINAL SEARCH (BEST VERSION)
    def search_concepts(self, keyword):
        if not keyword:
            return []

        stopwords = {"what", "is", "the", "a", "an", "of", "in", "on", "for", "and", "to"}
        words = [
            w.lower() for w in keyword.replace("?", "").split()
            if w.lower() not in stopwords and len(w) > 2
        ]

        if not words:
            return []

        # 🔹 Neo4j filtered search
        query = """
        MATCH (c:Concept)
        WHERE ANY(word IN $words WHERE toLower(c.name) CONTAINS word)
        RETURN c.name AS name, c.description AS description
        LIMIT 10
        """

        results = self.db.run_query(query, {"words": words})

        if not results:
            return []

        # 🔹 Scoring
        scored = []
        for r in results:
            name = (r.get("name") or "").lower()

            score = sum(1 for w in words if w in name)

            # Boost exact match
            if keyword.lower() in name:
                score += 2

            # Boost startswith match
            if any(name.startswith(w) for w in words):
                score += 1

            if score > 0:
                scored.append((score, r))

        if not scored:
            return []

        scored.sort(reverse=True, key=lambda x: x[0])

        best = scored[0][1]

        # 🔥 Add relationships automatically
        related = self.get_related_concepts(best["name"]) or []
        expanded = self.expand_graph(best["name"]) or []

        return [{
            "name": best["name"],
            "description": best.get("description", ""),
            "related": related,
            "expanded": expanded
        }]