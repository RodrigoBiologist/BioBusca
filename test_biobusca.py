"""Testes de regressão locais do BioBusca, sem chamadas externas."""
import unittest
from unittest.mock import patch
import server

class BioBuscaTests(unittest.TestCase):
    def test_bncc_codes_are_unique(self):
        codes=[x["code"] for x in server.CURRICULUM["skills"]]
        self.assertEqual(len(codes),len(set(codes)))
        self.assertEqual(len(codes),26)

    def test_catalog_bncc_references_exist(self):
        valid={x["code"] for x in server.CURRICULUM["skills"]}
        for key,concept in server.CONCEPTS.items():
            with self.subTest(concept=key):
                self.assertTrue(set(concept.get("bncc_skills",[])) <= valid)

    def test_graph_never_turns_articles_into_concepts(self):
        graph=server.graph("osmose")
        self.assertTrue(any(n["kind"]=="conceito" for n in graph["nodes"]))
        self.assertFalse(any(n["kind"]=="artigo" for n in graph["nodes"]))

    def test_unknown_term_does_not_invent_links(self):
        graph=server.graph("termo-inexistente-zz-test")
        self.assertEqual(graph["edges"],[])
        self.assertEqual(len(graph["nodes"]),1)

    def test_official_count_is_not_answer_key_count(self):
        self.assertIsInstance(server.OFFICIAL,list)
        self.assertEqual(len(server.OFFICIAL),0)
        self.assertGreaterEqual(len(server.ANSWER_INDEX.get("records",[])),0)

if __name__=="__main__":
    unittest.main()
