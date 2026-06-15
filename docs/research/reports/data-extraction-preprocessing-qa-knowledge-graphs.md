# Paper Report: Data Extraction And Preprocessing For QA Knowledge Graphs

Source PDF:
[Data-Extraction-and-Preprocessing-for-Automated-Question-Answering-Based-on-Knowledge-Graphs.pdf](../Data-Extraction-and-Preprocessing-for-Automated-Question-Answering-Based-on-Knowledge-Graphs.pdf)

## Bottom Line

Romanov, Volchek, and Mouromtsev focus on preparing support messages for a
question-answering knowledge graph. The paper is not about crawling web UIs,
but it offers useful patterns for `site-agent`'s domain intelligence layer:
clean noisy text, extract domain questions, enrich a graph with entities,
topics, and semantic similarity, then use embeddings to improve retrieval.

## Technique Summary

* Decodes and normalizes support emails from MIME and base64 into UTF-8 text.
* Removes HTML and CSS markup before language processing.
* Separates message signatures from message bodies with line-level binary
  classification.
* Combines regular expressions, line length, keyword features, stopword
  removal, normalization, and bag-of-words features.
* Compares classifiers and reports the best signature detection result with
  SVM at F1 0.9763 on the paper's dataset.
* Extracts questions using punctuation, universal dependencies, noun-verb
  evidence, and pronominal adverbs.
* Enriches a knowledge graph with named entities, topics, metadata, and
  semantically similar questions.
* Uses thesaurus-backed sentence similarity and TransE-style graph embeddings
  to improve downstream QA accuracy.

## Techniques To Reuse In `site-agent`

* Use document-cleaning stages before ontology extraction: decode, strip
  markup, remove boilerplate, and preserve provenance.
* Add support for grouping similar labels, help text, validation messages, and
  documentation snippets into concept-neighborhood evidence.
* Use named entities, topics, units, and constraints as ontology enrichment
  fields, not just free-text notes.
* Use semantic similarity to reduce review workload by clustering related
  low-confidence mappings.
* Record every enrichment step as evidence so AI-derived terms do not become
  unsupported public contracts.

## Project Fit

Adopt as a domain-ingestion reference. It supports the project's evidence-first
ontology and review queue, especially for documentation-heavy profiles.

## Caveats

* The experiments are Russian-language and support-email focused.
* Graph embeddings help retrieval, but they should not be treated as proof of
  a UI concept.
* Thresholds for semantic similarity are empirical and must be profile tested.
