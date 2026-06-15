# Paper Report: Classification-Based Adaptive Web Scraper

Source PDF:
[ujwal2017.pdf](../ujwal2017.pdf)

## Bottom Line

Ujwal et al. attack selector fragility by training a text classifier for
domain attributes, then using the classifier to discover repetitive DOM
blocks and their internal attribute paths. The idea maps strongly to
`site-agent`: concept extraction should be driven by evidence and canonical
labels, while selectors remain private and replaceable.

## Technique Summary

* Trains a website or domain-specific classifier to label DOM text as
  attributes such as title, description, coupon code, expiry, tags, or
  `OTHER`.
* Uses a one-time selector-based scrape only to build training data. The
  runtime extraction algorithm is then content based.
* Cleans domain-specific tokens with regular expressions before vectorizing
  text.
* Builds an annotated DOM tree. Each node stores its parent, children, tag
  name, predicted own label, descendant label counts, and original DOM path.
* Detects candidate repeated blocks by looking for subtrees that contain all
  compulsory labels and optional labels when present.
* Groups hits by tag-name path and prunes child nodes that do not repeat at
  corresponding positions.
* Derives stable internal paths to attributes from the remaining repeated
  structures.
* Periodically validates existing paths with the classifier so structural
  changes can trigger rediscovery.
* Reports high block-extraction accuracy on both current and older archived
  versions of the evaluated pages.

## Techniques To Reuse In `site-agent`

* Treat semantic classifiers as selector repair tools. If a selector drifts,
  re-run concept classification over the new DOM and rediscover private
  adapter bindings.
* Split schema approval from binding discovery. The approved concept can stay
  stable while the DOM path or selector changes.
* Support compulsory and optional evidence labels for concepts. For example,
  a setting row might require a label and value but optionally include help
  text, validation text, or a reset action.
* Store descendant concept-label counts in `UiElement.context` or a related
  extraction artifact for debugging and drift remapping.
* Use classifier disagreement as a low-confidence mapping signal for human
  review.

## Project Fit

Adopt the content-classification plus repeated-block discovery pattern for
drift handling and adapter regeneration.

## Caveats

* The approach assumes attributes repeat at compatible internal paths across
  blocks.
* It needs labeled examples or a domain corpus. That fits profiles, not core.
* It works on text-rich blocks better than icon-only controls or canvas UIs.
* Runtime can be expensive on large pages unless tree traversal is optimized.
