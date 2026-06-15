# Paper Report: An Automatic Web Wrapper For Extracting Information

Source PDF:
[an-automatic-web-wrapper-for-extracting-information-from-web-sou.pdf](../an-automatic-web-wrapper-for-extracting-information-from-web-sou.pdf)

## Bottom Line

Papadakis, Skoutas, Raftopoulos, and Varvarigou describe a fully automated
wrapper that segments semi-structured pages without training data or
site-specific rules. Its most useful contribution for `site-agent` is the
structural segmentation pipeline: transform HTML, preserve terminal-node order,
cluster adjacent nodes by common ancestors, detect a target area, then split
periodic records into semantic tokens.

## Technique Summary

* Converts input HTML into well-formed XHTML before extraction.
* Builds a tree representation and focuses on terminal nodes such as images,
  anchors, and text.
* Preserves terminal-node order because locality is treated as evidence of
  semantic relatedness.
* Computes adjacent-node similarity by counting common ancestors in the tree.
* Performs one-dimensional hierarchical clustering over ordered terminal-node
  indexes.
* Selects a target area from the clustering hierarchy, using a cutoff where
  the largest cluster covers a meaningful portion of page content.
* Segments the target area into repeated semantic tokens by finding periodic
  local minima in adjacent-node similarity.
* Uses autocorrelation and low-pass filtering to estimate the quasi-period of
  repeated records.
* Applies outlier detection to reject segments that look structurally unlike
  valid objects.
* Emits extracted objects as XML for downstream storage or transformation.

## Techniques To Reuse In `site-agent`

* Add ordered terminal-node similarity as a fallback extractor for repeated
  settings rows, table-like lists, and card grids.
* Preserve terminal-node order in raw interaction graph artifacts. This is
  cheap evidence and useful for record-boundary detection.
* Use common-ancestor similarity to identify groups of related controls when
  labels are sparse.
* Consider periodicity signals when splitting repeated UI sections, especially
  configuration lists with repeating field clusters.
* Emit extraction diagnostics showing target-area boundaries and rejected
  outliers. This would fit the project's debug view.

## Project Fit

Reference as a structural fallback. The approach is valuable for repeated
records, but modern `site-agent` extraction should prefer rendered DOM,
accessibility, and interaction evidence first.

## Caveats

* The PDF required local OCR because its embedded fonts lacked usable Unicode
  mappings, so exact wording should be rechecked before formal citation.
* The paper predates modern JavaScript-heavy apps.
* The method assumes useful data appears in repeating structures. It is weaker
  for one-off forms, dialogs, and stateful workflows.
* It is intentionally content independent, which helps portability but limits
  domain-aware schema naming.
