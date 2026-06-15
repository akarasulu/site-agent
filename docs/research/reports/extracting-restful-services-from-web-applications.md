# Paper Report: Extracting RESTful Services From Web Applications

Source PDF:
[upadhyaya2012.pdf](../upadhyaya2012.pdf)

## Bottom Line

Upadhyaya, Khomh, and Zou model human web tasks as RESTful services by
recording browser-side interactions, inputs, outputs, HTTP requests, and task
relations. This is one of the most directly relevant papers for `site-agent`
because it frames a UI workflow as a stable service-like contract while
keeping low-level browser details behind the generated service.

## Technique Summary

* Treats a task as a goal-oriented sequence of resource interactions.
* Uses a browser plugin where a user marks task start and completion.
* Records client-side events, URL changes, request parameters, cookies, and
  HTTP headers while the task runs.
* Models resources with URLs, request and response headers, representations,
  transitions, and final states.
* Identifies form inputs by matching controls to nearby text labels in the DOM.
  Hierarchical proximity is the primary signal, with edit distance as a
  tie-breaker.
* Lets a user select an output region, then identifies similar DOM structures
  and maps output fragments to labels or ontology concepts.
* Infers an HTTP method for a task by preferring unsafe over safe methods and
  non-idempotent over idempotent methods when multiple resources participate.
* Detects task relations from state changes, related URL parameters,
  next-state links or forms, and subset dependencies such as login before
  checkout.

## Techniques To Reuse In `site-agent`

* Model generated Python API and MCP methods as UI tasks with inputs,
  outputs, state transitions, risk level, and evidence.
* Add event-log based workflow extraction for actions that cannot be inferred
  from static form analysis alone.
* Use label proximity plus string similarity as a baseline for input-label
  association.
* Capture cookies and headers as private runtime evidence, while continuing to
  redact secrets from public artifacts.
* Use task relation detection to build navigation paths, restore prerequisites,
  and action sequencing.
* Keep a human annotation path for ambiguous outputs. This aligns with the
  project's review policy.

## Project Fit

Adopt the task model and event-capture approach as core design inspiration for
workflow extraction and generated API synthesis.

## Caveats

* The approach is interactive and partially human guided.
* It predates modern SPA frameworks but the browser-side observation model
  still applies.
* The paper does not address risk policy, dry-run behavior, or secret
  handling, which `site-agent` must add.
