# Paper Report: Learning To Crawl Deep Web

Source PDF:
[zheng2013.pdf](../zheng2013.pdf)

## Bottom Line

Zheng et al. cast deep-web crawling as a reinforcement-learning problem where
queries are actions, retrieved records are rewards, and the crawler learns from
past successes and failures. `site-agent` should not blindly query production
forms, but the reward model is valuable for read-only crawl planning:
prioritize actions that reveal new pages, fields, concepts, and transitions.

## Technique Summary

* Models the crawler as an agent and the target deep-web database as the
  environment.
* Represents state as the records already acquired.
* Represents actions as query keywords submitted through a form.
* Defines reward as the number or proportion of new records retrieved.
* Encodes actions with linguistic, statistical, and HTML features.
* Uses features such as part of speech, word length, language, term frequency,
  document frequency, residual inverse document frequency, HTML tag/attribute,
  and DOM depth.
* Estimates unexecuted action reward by comparing candidate actions with
  executed actions using a kernel/kNN-style method.
* Approximates Q-values so action selection can account for future reward, not
  only immediate gain.
* Limits candidate keywords with a Heap's-law-inspired candidate-set sizing
  strategy.
* Reports strong coverage on several real deep-web sites and compares against
  random, generic-frequency, and Zipf-style baselines.

## Techniques To Reuse In `site-agent`

* Define crawl reward around new evidence: pages, forms, fields, actions,
  validation messages, docs-linked concepts, and configuration settings.
* Use learned crawl prioritization to decide which safe interaction to try
  next when the crawler has many links, tabs, filters, or form values.
* Encode candidate actions with UI context features, not just URL or selector
  features.
* Treat failed or low-yield interactions as training evidence to avoid similar
  actions later in the same run.
* Keep the algorithm in read-only or dry-run mode unless a profile explicitly
  permits safe writes.

## Project Fit

Pilot as crawl-planning research, not as default behavior. It is strongest for
large search/filter spaces and benchmark profiles where reward can be measured
without mutating state.

## Caveats

* The paper focuses on keyword queries against deep-web databases, not web app
  workflow automation.
* The published experiments use single text boxes or single attributes.
  Multi-field forms remain future work in the paper.
* Production UI crawling needs host allowlists, risk policy, rate limits, and
  explicit safety modes beyond what the paper covers.
