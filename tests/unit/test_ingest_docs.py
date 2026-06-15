import textwrap

from site_agent.core.ai.backends import NoopAiBackend
from site_agent.core.ingest.docs import extract_document_clues, ingest_documents
from site_agent.core.profiles import init_profile


def test_extract_document_clues_finds_constraints_units_and_operations():
    clues = extract_document_clues(
        """
        Create a rule and apply it.
        Valid range: 1-65535 seconds.
        Allowed values: TCP, UDP.
        Default: disabled.
        This field is required and read-only after creation.
        """
    )

    assert "range: 1-65535" in clues["constraints"]
    assert "allowed values: TCP, UDP" in clues["constraints"]
    assert "default: disabled" in clues["constraints"]
    assert "required" in clues["constraints"]
    assert "read only" in clues["constraints"]
    assert "operation: create" in clues["constraints"]
    assert "operation: apply" in clues["constraints"]
    assert "seconds" in clues["units"]


def test_ingest_documents_attaches_section_clues_to_heading_terms(tmp_path):
    profile = init_profile(tmp_path, "demo", "https://example.com")
    docs_dir = tmp_path / "profiles" / "demo" / "docs"
    (docs_dir / "manual.md").write_text(
        textwrap.dedent(
            """
        # Port Forwarding Rule

        Add or update a forwarding rule.
        Valid range: 1 to 65535.
        Options: TCP, UDP.
        Default: disabled.

        # Wireless Power

        Range: 1-30 dBm.
        """,
        ),
        encoding="utf-8",
    )

    terms, evidence = ingest_documents(tmp_path, profile, NoopAiBackend())
    by_name = {term.canonical_name: term for term in terms}

    forwarding = by_name["port forwarding rule"]
    assert forwarding.sources == [evidence[0].id]
    assert "range: 1-65535" in forwarding.constraints
    assert "allowed values: TCP, UDP" in forwarding.constraints
    assert "operation: add" in forwarding.constraints
    assert "operation: update" in forwarding.constraints
    assert by_name["wireless power"].units == ["dbm"]
