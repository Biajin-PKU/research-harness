## Summary

What does this PR do? (1-3 sentences)

## Type of change

- [ ] Bug fix
- [ ] New primitive / MCP tool
- [ ] New feature (non-primitive)
- [ ] Refactor (no behavior change)
- [ ] Documentation
- [ ] CI / tooling

## Changes

- 
- 

## Testing

- [ ] Added tests for new behavior
- [ ] All existing tests pass (`python -m pytest packages/ -q`)
- [ ] Ruff lint passes (`ruff check packages/`)
- [ ] Ruff format check passes (`ruff format --check packages/`)

## If adding a new primitive

- [ ] Registered with `@register_primitive(spec)` in an `*_impls.py` file
- [ ] Imported in `primitives/__init__.py` so the registry runs on import
- [ ] `PrimitiveSpec.output_type` documents the return shape
- [ ] MCP tool auto-exposed and verified: `python -c "from research_harness.primitives.registry import list_primitives; print([p.name for p in list_primitives()])"`

## Related issues

Closes #

## Notes for reviewers

Anything the reviewer should pay special attention to.
