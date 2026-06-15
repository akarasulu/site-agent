# Paper Report: Web Design Scraping

Source PDF:
[namoun2020.pdf](../namoun2020.pdf)

## Bottom Line

Namoun et al. define "web design scraping" as extracting and modeling visual
properties of web interfaces, not just page content. The paper is conceptual,
but it usefully broadens `site-agent`'s extraction target: the crawler should
understand layout, visual hierarchy, interaction affordances, responsiveness,
and usability signals as evidence for mapping and drift detection.

## Technique Summary

* Distinguishes content scraping from design scraping.
* Defines design scraping as extracting visual properties of website elements
  to understand and model web design.
* Identifies the render tree from DOM and CSSOM as a source of visual
  properties and text content.
* Points to image processing for features that are hard to infer from DOM and
  CSS alone, such as symmetry, complexity, and perceived visual balance.
* Connects AI and machine learning with feature engineering, model selection,
  training, and adaptive recommendation.
* Suggests CNNs for image-like UI features and RNNs for textual DOM analysis.
* Frames HCI guidelines as a knowledge base for predicting usability issues
  and suggesting design improvements.
* Proposes research areas: understand design meaning, infer design flaws,
  suggest improvements, and intelligently refactor web designs.

## Techniques To Reuse In `site-agent`

* Capture design-level context as extraction evidence: visual hierarchy,
  grouping, responsive breakpoints, tabs, cards, menus, and affordances.
* Include viewport-specific observations in crawl snapshots, especially for
  generated adapters that may run on different viewport sizes.
* Use HCI-style heuristics to flag extraction uncertainty, such as ambiguous
  labels, hidden controls, or inconsistent grouping.
* Treat design drift as more than selector drift. A layout change can alter
  meaning, action risk, or restore readiness.
* Use visual design evidence to improve human review screens for mappings.

## Project Fit

Reference as conceptual support for a richer UI evidence model. It is not an
implementation recipe, but it reinforces the need for visual and responsive UI
signals.

## Caveats

* The paper does not provide a concrete end-to-end extraction algorithm.
* Many proposed research directions require labeled design-quality data.
* `site-agent` should avoid generating design recommendations unless they
  support extraction, mapping, or drift evidence.
