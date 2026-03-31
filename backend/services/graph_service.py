from backend.db.neo4j_driver import Neo4jDriver


class GraphService:
    def __init__(self):
        self.db = Neo4jDriver()

    # 🔥 Create / update concept
    def create_concept(self, name, description=""):
        name = name.strip()
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
        from_node = from_node.strip()
        to_node = to_node.strip()

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

    # 🔥 Bulk insert (clean + safe)
    def insert_from_llm(self, data):
        concepts = data.get("concepts", [])
        relationships = data.get("relationships", [])

        concepts_added = 0
        relationships_added = 0

        # Insert concepts
        for concept in concepts:
            name = concept.get("name", "").strip()
            description = concept.get("description", "").strip()

            # Clean LLM noise
            if name.lower().startswith("name:"):
                name = name.split(":", 1)[1].strip()

            if not name or len(name) < 2:
                continue

            if name.lower() in ["concept", "thing", "item"]:
                continue

            self.create_concept(name, description)
            concepts_added += 1

        # Insert relationships
        for rel in relationships:
            from_node = rel.get("from", "").strip()
            to_node = rel.get("to", "").strip()
            rel_type = rel.get("type", "RELATED")

            # Clean names
            if from_node.lower().startswith("name:"):
                from_node = from_node.split(":", 1)[1].strip()

            if to_node.lower().startswith("name:"):
                to_node = to_node.split(":", 1)[1].strip()

            if not from_node or not to_node:
                continue

            self.create_relationship(from_node, to_node, rel_type)
            relationships_added += 1

        return {
            "status": "success",
            "concepts_added": concepts_added,
            "relationships_added": relationships_added
        }

    # 🔥 FINAL SEARCH (STRICT + BEST MATCH ONLY)
    def search_concepts(self, keyword):
        # 🔹 Step 1: Clean query
        words = keyword.lower().replace("?", "").split()

        # 🔹 Step 2: Fetch all concepts
        query = """
        MATCH (c:Concept)
        RETURN c.name AS name, c.description AS description
        """
        results = self.db.run_query(query)

        if not results:
            return []

        # 🔹 Step 3: Score matches
        scored = []

        for r in results:
            name = (r.get("name") or "").lower()

            # Count matching words
            score = sum(1 for w in words if w in name)

            # Ignore weak matches (VERY IMPORTANT)
            if score > 0:
                scored.append((score, r))

        if not scored:
            return []

        # 🔥 Sort by best match
        scored.sort(reverse=True, key=lambda x: x[0])

        # 🔥 RETURN ONLY BEST MATCH (critical improvement)
        best_score = scored[0][0]
        best_results = [r for score, r in scored if score == best_score]

        return best_results[:1]