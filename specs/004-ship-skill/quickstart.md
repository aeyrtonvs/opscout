# Quickstart: validate the ship skill

```sh
uv run just test tests/unit/ship tests/tools/test_skill_evals.py
echo '{"tool_name":"Bash","tool_input":{"command":"git push origin HEAD:main"},"cwd":"."}' \
  | plugins/opscout/bin/opscout hook pre-tool-use     # deny, naming main
plugins/opscout/bin/opscout ship check-branch feat/add-the-guard   # exit 0
```

Evals (each run confirmed; reports stay local):

```sh
uv run python -m tools.skill_evals --plugin plugins/opscout --case '004-*' \
  --config-dir plugins/opscout/evals/eval-config --threshold 0.9 --max-cost-usd 3 \
  --out plugins/opscout/evals/results/ship.json
```
