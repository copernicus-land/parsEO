# AGENTS

These instructions apply to the entire repository.

## Code style
- Target Python 3.9+ features.
- Use [ruff](https://docs.astral.sh/ruff/) to lint and format code. Run `ruff check .` before committing and address reported issues.
- Keep one import per line and sort imports alphabetically.

## Testing
- Run `pytest` to ensure all tests pass.
- When possible, run `ruff check .` and `pytest` before sending changes.

## Development workflow
- Use the `develop` branch as the base for changes.

**New/all schemas shall follow the tempplate in 'examples/schema_skeleton/' striclty.** 

References are: 
CLMS STAC: https://github.com/copernicus-land/clms-stac
