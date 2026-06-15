# Paper Report: Natural Language Driven Web API Development

Source PDF:
[dimanidis2018.pdf](../dimanidis2018.pdf)

## Bottom Line

Dimanidis, Chatzidimitriou, and Symeonidis propose Gherkin2OAS, a constrained
natural-language workflow that maps Gherkin resource files into OpenAPI
specifications. The useful takeaway for `site-agent` is that generated
automation contracts should come from a controlled, reviewable intermediate
model rather than unconstrained language generation.

## Technique Summary

* Combines Behavior Driven Development and Specification Driven Development.
* Uses Gherkin as business-readable documentation and OpenAPI as the technical
  contract.
* Organizes input into resource files. The filename contributes to the REST
  path and lets resources be processed independently.
* Maps `When` steps to requests and `Then` steps to responses.
* Maps verbs to common HTTP operations and nouns to parameters.
* Uses Gherkin data tables to express parameter examples, ranges, and models.
* Uses `Given` for roles and resource hierarchy context.
* Supports links between resources through custom OpenAPI extensions.
* Generates resource and application-state graphs for validation.
* Deliberately minimizes machine learning so output is predictable when users
  follow the rules.

## Techniques To Reuse In `site-agent`

* Create a constrained review format for approved concepts and actions before
  generating Python API, MCP, or Ansible artifacts.
* Generate state graphs from approved workflows and use them for validation,
  documentation, and restore planning.
* Treat roles, prerequisites, and resource hierarchy as first-class metadata in
  action specs.
* Prefer deterministic transformations after review. Use AI for naming and
  descriptions only when backed by evidence.
* Consider optional profile-authored scenarios as fixtures for generated API
  and MCP contract tests.

## Project Fit

Adopt the controlled-intermediate-model idea. Do not copy the REST-only mapping
directly, because `site-agent` models UI-backed operations rather than native
HTTP APIs.

## Caveats

* The method requires users to follow documentation rules.
* It generates OpenAPI 2 in the paper, while this project needs Python, MCP,
  Ansible, and adapter contracts.
* Natural language remains useful only because it is constrained and validated.
