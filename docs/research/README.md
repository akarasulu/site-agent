# Research Reports

This directory contains local research papers and one concise implementation
report per paper. The reports focus on crawler, wrapper induction, visual
structure, API extraction, and documentation-mining techniques that can be
adapted into `site-agent` without making core target-specific.

## Implementation Plan

The project-level synthesis is maintained in
[Research Technique Implementation Plan](../../contracts/research-technique-implementation-plan.md).

## Paper Reports

| Report | Main thread |
| --- | --- |
| [A Dynamic Approach For Template And Content Extraction](reports/a-dynamic-approach-template-content-extraction.md) | Template/content separation and page-family signals. |
| [Automatic Web Wrapper Clustering](reports/automatic-web-wrapper-clustering.md) | Wrapper induction and repeated structure reuse. |
| [Classification-Based Adaptive Web Scraper](reports/classification-based-adaptive-web-scraper.md) | Adaptive extraction and classifier-guided scraping. |
| [Data Extraction And Preprocessing For QA Knowledge Graphs](reports/data-extraction-preprocessing-qa-knowledge-graphs.md) | Entity, unit, and constraint enrichment for ontology grounding. |
| [Extracting RESTful Services From Web Applications](reports/extracting-restful-services-from-web-applications.md) | UI-to-operation discovery and API-like contract synthesis. |
| [Extracting Web API Specifications From Documentation](reports/extracting-web-api-specifications-from-documentation.md) | Documentation mining for operation names, arguments, and constraints. |
| [Gherkin2OAS Natural Language Web API Development](reports/gherkin2oas-natural-language-web-api-development.md) | Human-readable behavior descriptions mapped to API contracts. |
| [Learning To Crawl The Deep Web](reports/learning-to-crawl-deep-web.md) | Multi-pass crawl planning and frontier prioritization. |
| [Smart Crawler Deep Web Multi-Classification](reports/smart-crawler-deep-web-multi-classification.md) | Topic-aware crawl prioritization and relevance scoring. |
| [Visually Extracting Data Records From The Deep Web](reports/visually-extracting-data-records-deep-web.md) | Visual block and record extraction from rendered pages. |
| [Web Design Scraping](reports/web-design-scraping.md) | Design/layout cues for robust extraction. |
| [Web Page Information Extraction With Deep Learning](reports/web-page-information-extraction-deep-learning.md) | Learned extraction features and confidence-aware automation. |

## Local Papers

The PDF files are retained next to the reports so future implementation passes
can re-check source context when refining the crawler. Reports are summaries
and implementation notes; they are not replacements for the papers.
