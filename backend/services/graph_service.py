from backend.db.neo4j_driver import Neo4jDriver


class GraphService:
    def __init__(self):
        self.db = Neo4jDriver()

    # 🔥 Utility: normalize names
    def _clean(self, name):
        if not name:
            return ""
        return name.strip().lower().replace("-", "").replace("_", " ")

    # 🔥 Create / update concept
    def create_concept(self, name, description=""):
        name = self._clean(name)
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
        from_node = self._clean(from_node)
        to_node = self._clean(to_node)

        if not from_node or not to_node:
            return None

        rel_type = rel_type.upper().replace(" ", "_").replace("/", "_")

        print(f"🔗 Creating relationship: {from_node} -> {to_node}")

        query = f"""
        MERGE (a:Concept {{name: $from}})
        MERGE (b:Concept {{name: $to}})
        MERGE (a)-[:{rel_type}]->(b)
        """

        return self.db.run_query(query, {
            "from": from_node,
            "to": to_node
        })

    # 🔥 NEW: AUTO LINK FUNCTION (FIXED)
    def auto_link_similar(self, concepts):
        try:
            names = [
                self._clean(c.get("name"))
                for c in concepts
                if c.get("name")
            ]

            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    a = names[i]
                    b = names[j]

                    if not a or not b:
                        continue

                    # 🔥 Rule 1: abbreviation match (FOG case)
                    if "(" in a and ")" in a:
                        abbr = a.split("(")[-1].replace(")", "").strip()
                        if abbr and abbr in b:
                            self.create_relationship(a, b, "ABBREVIATION")

                    if "(" in b and ")" in b:
                        abbr = b.split("(")[-1].replace(")", "").strip()
                        if abbr and abbr in a:
                            self.create_relationship(b, a, "ABBREVIATION")

                    # 🔥 Rule 2: word overlap
                    common = set(a.split()) & set(b.split())
                    if len(common) >= 2:
                        self.create_relationship(a, b, "RELATED")

                    # 🔥 Rule 3: substring match
                    if a != b and len(set(a.split()) & set(b.split())) >= 2:
                        self.create_relationship(a, b, "RELATED")

        except Exception as e:
            print(f"⚠️ Auto-link internal error: {str(e)}")

    # 🔥 Get all concepts
    def get_graph(self):
        query = """
        MATCH (c:Concept)
        RETURN c.name AS name, c.description AS description
        """
        return self.db.run_query(query)

    # 🔥 Get related concepts
    def get_related_concepts(self, name):
        name = self._clean(name)

        query = """
        MATCH (a:Concept {name: $name})-[r]->(b:Concept)
        RETURN type(r) AS relation, b.name AS name, b.description AS description
        LIMIT 5
        """
        return self.db.run_query(query, {"name": name})

    # 🔥 Multi-hop expansion
    def expand_graph(self, name):
        name = self._clean(name)

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

        # Insert concepts
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

        # Insert relationships
        for rel in relationships:
            from_node = (rel.get("from") or "").strip()
            to_node = (rel.get("to") or "").strip()
            rel_type = (rel.get("type") or "RELATED").strip()

            if from_node.lower().startswith("name:"):
                from_node = from_node.split(":", 1)[1].strip()

            if to_node.lower().startswith("name:"):
                to_node = to_node.split(":", 1)[1].strip()

            if not from_node or not to_node:
                continue

            self.create_relationship(from_node, to_node, rel_type)

        # 🔥 AUTO LINK ADDED HERE
        self.auto_link_similar(concepts)

        return {"status": "success"}

    # 🔥 Search
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

        query = """
        MATCH (c:Concept)
        WHERE ANY(word IN $words WHERE toLower(c.name) CONTAINS word)
        RETURN c.name AS name, c.description AS description
        LIMIT 10
        """

        results = self.db.run_query(query, {"words": words})

        if not results:
            return []

        scored = []
        for r in results:
            name = (r.get("name") or "").lower()

            score = sum(1 for w in words if w in name)

            if keyword.lower() in name:
                score += 2

            if score > 0:
                scored.append((score, r))

        if not scored:
            return []

        scored.sort(reverse=True, key=lambda x: x[0])
        best = scored[0][1]

        related = self.get_related_concepts(best["name"]) or []
        expanded = self.expand_graph(best["name"]) or []

        return [{
            "name": best["name"],
            "description": best.get("description", ""),
            "related": related,
            "expanded": expanded
        }]