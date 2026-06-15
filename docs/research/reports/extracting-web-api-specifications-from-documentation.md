# Paper Report: Extracting Web API Specifications From Documentation

Source PDF:
[yang2018.pdf](../yang2018.pdf)

## Bottom Line

Yang et al. present D2Spec, a tool that crawls API documentation and extracts
base URLs, path templates, and HTTP methods. For `site-agent`, the strongest
lesson is not the REST-specific output. It is the evidence pipeline: crawl
documentation with JavaScript execution, classify likely API examples, infer
templates from repeated examples, locate nearby descriptive context, and use
spec-vs-documentation mismatches as drift evidence.

## Technique Summary

* Starts from a seed documentation page and crawls linked documentation pages.
* Uses a headless browser so JavaScript-rendered documentation is observable.
* Extracts candidate URLs from rendered documentation while ignoring links and
  script-only URLs that are less likely to be API calls.
* Classifies candidate URLs as likely API invocations using page-context and
  URL features.
* Infers the base URL from likely API-call URLs.
* Builds path templates by clustering paths, detecting parameterized segments,
  and iteratively reusing discovered parameter values.
* Locates description blocks in the DOM near path examples and extracts HTTP
  methods from those blocks.
* Evaluated on 116 APIs, reporting 87.1 percent base URL precision,
  80.3 percent path-template precision, 80.9 percent path-template recall,
  83.8 percent HTTP-method precision, and 77.2 percent HTTP-method recall.
* Compares generated specs with existing specs to find documentation/spec
  inconsistencies.

## Techniques To Reuse In `site-agent`

* Use documentation crawling and DOM context extraction for target manuals,
  admin guides, and knowledge bases.
* Infer canonical action or setting templates from repeated documentation
  examples, but gate them behind UI evidence before public exposure.
* Attach nearby documentation blocks as evidence summaries for generated MCP
  tools and Python methods.
* Add a contract-drift check that compares generated schemas against refreshed
  documentation and prior approved schemas.
* Use clustering over paths and examples for generated API/package naming,
  especially when docs include repeated command or UI path examples.

## Project Fit

Adopt the documentation extraction pattern for the Domain Intelligence Layer
and drift checks.

## Caveats

* D2Spec assumes documentation contains multiple examples and that important
  descriptions are near those examples.
* It can mis-handle multiple API versions or sparse examples.
* `site-agent` should not expose doc-derived tools unless UI evidence also
  supports them.
