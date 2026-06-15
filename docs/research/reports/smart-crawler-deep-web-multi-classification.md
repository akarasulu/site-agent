# Paper Report: Smart Crawler For Deep Web With Multi-Classification

Source PDF:
[khare2020.pdf](../khare2020.pdf)

## Bottom Line

Khare, Dalvi, and Kazi combine a crawler, active-link detection, HTML tag
capture, and text classification pipelines for deep-web page categorization.
The Tor and dark-web context is outside `site-agent`'s mission, but the
classifier and crawl-control pieces are relevant: classify pages during crawl,
separate active from inactive links, cap crawl depth, and save structured crawl
artifacts.

## Technique Summary

* Starts from a user-provided seed URL and crawls breadth first until a depth
  limit or link exhaustion.
* Separates active and inactive links by sending requests and checking whether
  the page is found.
* Extracts crawled text and HTML tags, then stores results in a centralized
  database.
* Builds text-classification pipelines with bag of words and TF-IDF features.
* Compares logistic regression, SVM, naive Bayes, and neural-network-assisted
  classification over nine domains.
* Reports the strongest classification accuracy with TF-IDF plus logistic
  regression and neural-network support.
* Discusses request delay, user-agent rotation, and network routing in the
  context of anonymous crawling.

## Techniques To Reuse In `site-agent`

* Add page classification during crawl to prioritize settings, forms,
  dashboards, docs, login pages, and low-value pages differently.
* Track link health as a first-class crawl artifact with status, timestamp,
  and evidence.
* Support explicit depth and scope controls in profile crawl policy.
* Save crawled HTML snippets or normalized tag summaries for later extraction
  and drift checks.
* Compare simple TF-IDF baselines against heavier AI approaches before adding
  complexity to page classification.

## Project Fit

Reference the crawl-classification and link-health pieces. Do not import the
Tor/dark-web anonymity focus into core.

## Caveats

* The paper's domain and examples include dark-web crawling, which is not a
  project goal.
* Some anti-blocking tactics are not appropriate for authenticated enterprise
  UI automation.
* Classification was evaluated on a relatively small custom dataset.
* `site-agent` must honor robots, profile scope, host allowlists, credentials,
  and operator risk policy.
