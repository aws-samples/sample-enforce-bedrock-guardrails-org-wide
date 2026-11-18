.PHONY: help install test lint synth nag deploy destroy bench trace failures chart verify enforce-set enforce-get enforce-delete clean all

PY := .venv/bin/python
PIP := .venv/bin/pip

help:
	@echo "Targets:"
	@echo "  install     create venv and install Python deps"
	@echo "  test        run python and CDK tests"
	@echo "  lint        type-check CDK + run python compileall"
	@echo "  synth       cdk synth (no AWS calls, runs cdk-nag)"
	@echo "  nag         alias for synth; fails on unsuppressed cdk-nag findings"
	@echo "  deploy      cdk deploy --all (requires AWS credentials)"
	@echo "  destroy     cdk destroy --all"
	@echo "  bench       run scripts/run_benchmark.py"
	@echo "  trace       run scripts/capture_trace.py"
	@echo "  failures    run scripts/reproduce_failure_modes.py"
	@echo "  chart       generate latency PNG from latest results CSV"
	@echo "  verify      run scripts/verify_deployment.py (release gate)"
	@echo "  enforce-set    set account-level enforced guardrail (Layer 3)"
	@echo "  enforce-get    show account-level enforced guardrail (Layer 3)"
	@echo "  enforce-delete remove account-level enforced guardrail (Layer 3)"
	@echo "  all         install + lint + test + synth"

.venv:
	python3 -m venv .venv  # requires Python >= 3.12
	$(PIP) install --upgrade pip
	$(PIP) install --require-hashes -r requirements-dev.lock

install: .venv

test: .venv
	$(PY) -m pytest -q
	cd cdk && npm test --silent

lint: .venv
	$(PY) -m compileall -q scripts tests
	cd cdk && npm run lint --silent

synth:
	cd cdk && npx cdk synth --quiet

# cdk-nag (CSR-012) runs automatically as part of every `cdk synth` — see
# cdk/bin/app.ts. This target is just an explicit, discoverable alias for
# reviewers; it fails with the same non-zero exit code as `make synth` if
# any unsuppressed AwsSolutions-* finding is present.
nag: synth
	@echo "cdk-nag: no unsuppressed findings (see cdk/bin/app.ts for wiring)"

deploy:
	cd cdk && npx cdk deploy --all --require-approval never

destroy:
	cd cdk && npx cdk destroy --all --force

bench: .venv
	$(PY) scripts/run_benchmark.py

trace: .venv
	$(PY) scripts/capture_trace.py

failures: .venv
	$(PY) scripts/reproduce_failure_modes.py

chart: .venv
	$(PY) scripts/generate_chart.py

verify: .venv
	$(PY) scripts/verify_deployment.py

enforce-set: .venv
	$(PY) scripts/set_account_enforcement.py

enforce-get: .venv
	$(PY) scripts/get_account_enforcement.py

enforce-delete: .venv
	$(PY) scripts/delete_account_enforcement.py < /dev/tty

clean:
	rm -rf .venv cdk/cdk.out cdk/node_modules results/*.csv results/*.json results/*.log results/*.png
	find . -name __pycache__ -type d -exec rm -rf {} +

all: install lint test synth
