# Paper Report: Visually Extracting Data Records From The Deep Web

Source PDF:
[anderson2013.pdf](../anderson2013.pdf)

## Bottom Line

Anderson and Hong's rExtractor uses rendered visual blocks instead of raw DOM
or source patterns to extract repeated data records from query result pages.
This is highly relevant to `site-agent` because authenticated web apps often
have complex DOMs, repeated cards, responsive layouts, and JavaScript-driven
rendering where visual grouping is more stable than selectors.

## Technique Summary

* Builds a Visual Block Model from the rendered page using a browser layout
  engine.
* Represents each visible node as a rectangular visual block with position and
  visual properties.
* Distinguishes container blocks from basic blocks.
* Uses visual similarity, width similarity, spatial containment, and block
  content similarity.
* Starts record extraction by selecting a seed basic block likely to belong to
  a data record.
* Finds the seed with a clockwise Ulam spiral biased toward the page area
  where records commonly begin.
* Builds candidate record blocks from containers that contain the seed.
* Clusters container blocks by width and selects the cluster with maximum
  block-content similarity.
* Measures block content similarity with a multiset-style Jaccard variant over
  visually similar child blocks.
* Reports substantially higher precision and recall than the compared ViNTs
  system on the evaluated datasets.

## Techniques To Reuse In `site-agent`

* Extend Playwright extraction with rendered bounding boxes and computed style
  features for fields, labels, buttons, repeated cards, and setting rows.
* Use visual containment to associate labels, help text, fields, and actions
  when DOM proximity is misleading.
* Detect repeated setting records by clustering similarly sized visual
  containers with similar child-block signatures.
* Store visual fingerprints as private adapter evidence for drift detection.
* Build a debug overlay mode that shows visual blocks, candidate groups, and
  chosen record boundaries.

## Project Fit

Adopt visual-block extraction as a core complement to DOM and accessibility
snapshots. This directly supports robust extraction from modern JavaScript UIs.

## Caveats

* The method is designed for query-result records, not arbitrary forms.
* The seed-search assumptions are influenced by western reading order and
  common search-result layouts.
* Responsive/mobile layouts may require viewport-specific visual fingerprints.
* Visual grouping should produce evidence, not public selectors.
