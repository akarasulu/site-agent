from site_agent.core.inventory import build_site_tree, domain_terms, synonym_hits, word_histogram
from site_agent.core.models import DomainTerm


def test_inventory_histogram_filters_stopwords_and_domain_terms():
    ontology = [
        DomainTerm(
            id="term_port_forwarding",
            canonical_name="port forwarding",
            aliases=["virtual server", "nat rule"],
            confidence=0.9,
        )
    ]
    vocabulary, synonyms = domain_terms(ontology)
    histogram = word_histogram("This page provides the function of port forwarding and virtual server configuration.", vocabulary)

    assert "the" not in histogram
    assert histogram["port"] == 1
    assert histogram["forwarding"] == 1
    assert histogram["virtual"] == 1
    assert histogram["server"] == 1
    assert synonym_hits(histogram, synonyms)["port forwarding"] == 4


def test_inventory_builds_nested_tree_from_paths():
    nodes = [
        {"path": [], "path_key": "", "domain_histogram": {"router": 1}},
        {"path": ["Internet"], "path_key": "internet", "domain_histogram": {"internet": 1}},
        {"path": ["Internet", "Security", "Port Forwarding"], "path_key": "internet/security/port-forwarding", "domain_histogram": {"port": 1}},
    ]

    tree = build_site_tree(nodes)

    internet = tree["children"][0]
    assert internet["label"] == "Internet"
    assert internet["children"][0]["label"] == "Security"
    assert internet["children"][0]["children"][0]["label"] == "Port Forwarding"
