# Generated Automation Surfaces

## Goal

Generate three automation surfaces from the same approved, evidence-backed model:

- Python API for developers and shared execution logic.
- MCP server for agent clients.
- Ansible collection for operators and declarative workflows.

The generated model, not raw UI selectors, is the source of truth.

## Architecture

The preferred dependency direction is:

```text
approved schema/model
  -> generated Python API
      -> generated MCP server
      -> generated Ansible collection
```

The Python API should own target-specific execution details through generated private adapters. MCP tools and Ansible modules should call Python API methods where practical instead of duplicating browser automation or selector bindings.

This keeps behavior consistent across surfaces:

- dry-run and apply semantics
- confirmation checks
- risk policy enforcement
- current-value reads
- restore planning
- evidence and confidence metadata

## Python API

Generated package requirements:

- typed, selector-free public methods
- stable semantic names from canonical concepts
- docstrings with evidence summaries
- argument constraints from UI/docs/model evidence
- dry-run support for every write operation
- explicit risk metadata
- private adapter/runtime modules for selectors and browser actions
- semantic versioning independent from adapter versioning

Example generated shape:

```text
output/my-site/api/
  pyproject.toml
  my_site_client/
    __init__.py
    client.py
    models.py
    runtime.py
    adapters/
      v0_1_0.py
    evidence.json
```

Example public call shape:

```python
client.get_wan_status()
client.set_alert_email("ops@example.test", dry_run=True)
client.create_port_forward(name="demo", service_port=12121, enabled=False, dry_run=True)
```

## MCP Surface

Generated MCP tools should remain stable, readable, and evidence-backed.

When the Python API exists, MCP tools should delegate to it:

```text
tools/call -> generated MCP handler -> generated Python API -> private adapter/runtime
```

MCP should not expose raw selectors, browser locators, cookies, or profile secrets.

## Ansible Collection

Generated Ansible collection requirements:

- Ansible-style module names and option names.
- `facts` modules for read/status coverage.
- Resource-like modules for idempotent configuration updates.
- Check mode for all write-capable modules, backed by Python API dry-run.
- Idempotence only when both current-value read evidence and write/restore evidence exist.
- Low-confidence or non-idempotent actions stay review-required or documentation-only.
- Module documentation includes evidence IDs, risk level, side effects, and constraints.

Example generated shape:

```text
output/my-site/ansible/ansible_collections/site_agent/my_site/
  galaxy.yml
  plugins/
    module_utils/
      client.py
    modules/
      my_site_facts.py
      my_site_alert_email.py
  playbooks/
    backup.yml
    restore_plan.yml
```

## Evidence Rules

Generated API methods, MCP tools, and Ansible modules must all retain evidence references.

Minimum exposure rules:

- Read methods/modules/tools require UI evidence.
- Domain naming should prefer documentation evidence when available.
- Write methods/modules/tools require UI form/action evidence.
- Idempotent Ansible modules require current-value read evidence plus write evidence.
- Apply-capable operations require dry-run support, risk metadata, and confirmation policy.

## Versioning

Version these independently:

- generated Python API contract
- generated MCP contract
- generated Ansible collection contract
- private adapter bindings

Adapter-only drift should not force public API, MCP, or Ansible breaking changes when semantic identity is unchanged.

## Product Boundary

Core implements generators and shared contracts only.

Target-specific generated Python packages, MCP packages, Ansible collections, and adapters are profile outputs. They must not be committed as core behavior except as fixtures/golden artifacts for tests.
