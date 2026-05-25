# Interaction Flow Discovery

Website action APIs are often not represented by static forms alone. Many applications use
list-management flows where a user clicks Add, Create, New Item, or a similar trigger, then
a dynamic editor appears. The editor may be built from hidden templates, cloned controls,
suffixed IDs, modal dialogs, drawers, or inline expandable rows.

The crawler must model these flows explicitly.

## Required Behavior

- Detect safe action-entry triggers such as add, create, and new item.
- Open the flow in read-only crawl mode only when a cancel/close path is available or the
  operation has not been applied.
- Capture newly visible fields after the trigger, not only fields present in initial HTML.
- Distinguish hidden templates from visible active controls.
- Record whether field selectors are cloned or suffixed from templates.
- Extract constraints from attributes, inline help, validation text, and documentation.
- Cancel or close the flow after inspection.
- Store the observed flow as evidence for generated MCP tools.

## Safety Boundary

The crawler may open and fill candidate values in a dynamic form to learn structure and
validation constraints, but it must not click Apply, Save, Submit, Delete, Enable, Disable,
or similar state-changing controls in read-only crawl mode.

Apply-mode validation belongs in explicit live test harnesses or user-approved action
execution, not in default crawling.

## AI Role

AI should use the observed flow transcript plus retrieved documentation to infer usage
patterns:

- Which trigger opens the editor.
- Which fields are required.
- Which constraints apply.
- Whether creation and activation are separate steps.
- Whether the UI uses hidden templates, cloned rows, modal editors, or drawers.
- Which action should be exposed as a single MCP tool versus multiple staged tools.

AI guidance is advisory. Generated tools still require UI evidence, constraints, and review
metadata before exposure.
