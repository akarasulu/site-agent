# Paper Report: A Dynamic Approach For Template And Content Extraction

Source PDF:
[A-Dynamic-Approach-for-Template-and-Content-Extraction-in-Websites.pdf](../A-Dynamic-Approach-for-Template-and-Content-Extraction-in-Websites.pdf)

## Bottom Line

Cristian-Catalin and Dragan propose a lightweight dynamic scraping pipeline
for finding similar pages, estimating their shared template, and filtering
main content from noise. The paper is article-content oriented, but several
ideas transfer well to `site-agent`: grouping pages into template families,
using structure similarity as crawl evidence, removing repeated chrome, and
setting extraction thresholds at runtime instead of hardcoding them.

## Technique Summary

* Uses website link topology to find similar pages. Pages linked from the
  same menu and linking back to the start page are treated as a connected
  graph likely to share a template.
* Sorts candidate outgoing links by descending URL length to bias toward
  content pages when large sites expose several template families.
* Replaces rigid node-by-node template matching with HTML tag frequency
  arrays. The method pads missing tags, computes standard deviation per tag,
  and averages the values to score how closely pages share a template.
* Uses the median tag count across pages as a more outlier-tolerant template
  estimate.
* Filters page content with text density, hyperlink density, runtime
  thresholds, common-content removal across similar pages, and final NLP
  cleanup.
* Uses NLP sentence checks to reject noisy JavaScript-like text, including
  sentence fragments without verbs and tokens above a length threshold.
* Evaluates output with normalized Levenshtein distance against manually
  cleaned reference articles.

## Techniques To Reuse In `site-agent`

* Add page-family clustering to the crawl layer. Group pages by link topology,
  URL shape, DOM tag histograms, headings, and navigation context before
  extraction.
* Use dynamic thresholds for field and content extraction. A threshold should
  be derived from the current page or page family when possible.
* Remove repeated profile chrome by comparing common text and controls across
  pages in the same template family.
* Store template-family evidence in crawl snapshots. This can support drift
  detection when selectors change but page structure remains semantically
  stable.
* Use normalized edit distance as one fixture metric for deterministic content
  extraction outputs.

## Project Fit

Adopt the page-family and dynamic-threshold ideas as crawler heuristics. Treat
the NLP cleanup as optional evidence preprocessing, not as a public contract
decision.

## Caveats

* The method targets article extraction, not authenticated workflows, forms,
  or UI actions.
* Tag-frequency templates lose parent-child DOM relationships, so they should
  complement, not replace, DOM and accessibility extraction.
* URL-length sorting is a useful heuristic for content sites, but it should
  not be generalized to admin apps without profile-specific evidence.
