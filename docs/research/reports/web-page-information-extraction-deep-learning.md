# Paper Report: Web Page Information Extraction With Deep Learning

Source PDF:
[pakyurek2019.pdf](../pakyurek2019.pdf)

## Bottom Line

Pakyurek, Sezgin, and Kulac extract web data from screenshots using a
RetinaNet-style object detector and OCR. This is useful for `site-agent` as a
fallback strategy when DOM structure changes, selectors are unstable, or the UI
renders important information as visual content.

## Technique Summary

* Motivated by failures of static DOM-path scrapers when page structure
  changes.
* Captures page screenshots with headless Chrome through Puppeteer.
* Labels target rectangular regions in screenshots, focused on price fields in
  the paper's hotel-price use case.
* Trains an object detector based on RetinaNet, ResNet, and Feature Pyramid
  Networks.
* Uses transfer learning by updating later network layers.
* Applies data augmentation through shifting, zooming, local distortion, and
  blur.
* Evaluates object detection with mean average precision and intersection over
  union.
* Applies Tesseract OCR to detected regions and stores extracted text with
  class and reference metadata.
* Shows good results for realistic structural changes, but weak results on
  manually distorted out-of-distribution images.

## Techniques To Reuse In `site-agent`

* Add screenshot-based evidence capture to crawl snapshots for visual fallback
  and reviewer debugging.
* Consider object detection for canvas-heavy UIs, image-rendered values,
  virtualized tables, or pages where accessibility and DOM evidence are weak.
* Use OCR as a fallback evidence source, never as the sole public contract
  source.
* Use data augmentation in benchmark profiles to test drift tolerance.
* Keep visual model artifacts profile-owned because labels and object classes
  are target specific.

## Project Fit

Pilot as an advanced profile adapter option, not as a core default. It is most
valuable for visual drift recovery and hard-to-parse UI surfaces.

## Caveats

* Requires labeled screenshots and profile-specific training data.
* OCR can misread values and must be validated against UI or documentation
  evidence.
* Visual models can fail under layout changes not represented in training
  data.
* GPU training cost is high compared with DOM/accessibility extraction.
