# MyComp Bot contributor notes

MyComp Bot controls local files and processes. Keep all new behaviour deny-by-default:

- never widen allowed filesystem roots or command policies implicitly;
- do not add MCP tool names without an explicit compatibility decision;
- never version OAuth state, tokens, logs, databases, virtualenvs, or app builds;
- run `python -m unittest discover -s tests -v` and `scripts/package-app.sh` for relevant changes.

The Python engine binds to loopback. Cloudflare and the two legacy LaunchAgents mentioned
in the README are external configuration and are never managed by this repository.
