.PHONY: help test build clean clean-reports clean-baselines allure-report allure-single-file allure-serve upload-results discover markers fixtures \
        check-env setup-kubeconfig setup-allure setup-docker-base lint typecheck ci list-tests list-files \
        quick api ui gitops gitops-deployment externalsecrets letsencrypt preview-environments full

# Docker run base configuration
DOCKER_RUN = docker run --rm -it --network host
DOCKER_VOLUMES = -v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
                 -v "/workspaces/glueops:/workspaces/glueops:ro" \
                 -v "$$(pwd)/allure-results:/app/allure-results" \
                 -v "$$(pwd)/allure-report:/app/allure-report" \
                 -v "$$(pwd)/baselines:/app/baselines" \
                 -v "$$(pwd):/app"
ENV_FILE_FLAG = $(shell [ -f .env ] && echo "--env-file .env" || echo "")
DOCKER_ENV = -e KUBECONFIG=/kubeconfig -e GIT_BRANCH="$(GIT_BRANCH)" -e GIT_COMMIT="$(GIT_COMMIT)"

# Git metadata
GIT_BRANCH = $$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'N/A')
GIT_COMMIT = $$(git rev-parse --short HEAD 2>/dev/null || echo 'N/A')
CAPTAIN_DOMAIN = $$(grep '^CAPTAIN_DOMAIN=' .env 2>/dev/null | cut -d'=' -f2 || echo 'N/A')

# Timestamp for unique report names
REPORT_TIMESTAMP = $$(date +%Y%m%d-%H%M%S)

# Test configuration variables
MARKER ?=
RERUNS ?=
SUITE ?= test

# Capture test paths/args (exclude known make targets)
ARGS ?= $(filter-out test,$(MAKECMDGOALS))

# Common pytest flags
PYTEST_COMMON_FLAGS =

help:
	@echo "GlueOps Test Suite (Pytest + Allure)"
	@echo ""
	@echo "Quick Commands (shortcuts):"
	@echo "  make quick                - Run quick tests (<5s)"
	@echo "  make api                  - Run API/K8s tests (smoke + write)"
	@echo "  make ui                   - Run UI tests with retries"
	@echo "  make gitops               - Run GitOps tests with retries"
	@echo "  make gitops-deployment    - Run GitOps deployment workflow test"
	@echo "  make letsencrypt          - Run LetsEncrypt certificate tests"
	@echo "  make preview-environments - Run preview environment PR workflow tests"
	@echo "  make full                 - Run full suite with retries"
	@echo ""
	@echo "Advanced Usage (unified command):"
	@echo "  make test                                - Run all tests"
	@echo "  make test MARKER=quick                   - Run quick tests"
	@echo "  make test MARKER=gitops RERUNS=0         - Run gitops with retries"
	@echo "  make test MARKER='smoke or write'        - Run API/K8s tests"
	@echo "  make test tests/smoke/test_argocd.py     - Run specific file"
	@echo "  make test MARKER=quick tests/smoke/      - Combine marker + path"
	@echo "  make test SUITE=mytest MARKER=smoke      - Custom suite name"
	@echo ""
	@echo ""
	@echo "Allure Reports:"
	@echo "  make allure-report      - Generate Allure HTML report from results"
	@echo "  make allure-single-file - Generate single-file HTML report (portable)"
	@echo "  make allure-serve       - Serve Allure report on http://localhost:5050"
	@echo "  make upload-results     - Upload results to Allure TestOps cloud"
	@echo "  Note: Tests generate allure-results/ data automatically"
	@echo ""
	@echo "Utilities:"
	@echo "  make build         - Build Docker image"
	@echo "  make clean         - Remove test artifacts and kubeconfig"
	@echo "  make clean-reports - Remove Allure results and reports"
	@echo "  make clean-baselines - Remove Prometheus metrics baseline files"
	@echo "  make discover      - List all tests with full descriptions"
	@echo "  make list-tests    - List all runnable test paths (copy-paste ready)"
	@echo "  make list-files    - List all test files (run entire files)"
	@echo "  make markers       - Show available pytest markers"
	@echo "  make fixtures      - Show available pytest fixtures"
	@echo "  make ci            - Run all static analysis (lint + typecheck)"
	@echo "  make typecheck     - Run mypy static type checking"
	@echo "  make lint          - Run pylint code analysis"
	@echo ""
	@echo "Setup:"
	@echo "  1. Copy .env.example to .env"
	@echo "  2. Configure your environment variables"
	@echo "  3. Run: make quick, make api, make ui, or make full"
	@echo "  4. Generate report: make allure-serve"

# Check if .env file exists and provide helpful message
check-env:
	@if [ ! -f .env ]; then \
		echo "⚠️  Warning: .env file not found"; \
		echo "   Copy .env.example to .env and configure your settings:"; \
		echo "   cp .env.example .env"; \
		echo ""; \
	fi

# Docker targets
build:
	docker build -t glueops-tests .

# Common setup targets
setup-kubeconfig:
	@cp $${KUBECONFIG:-$$HOME/.kube/config} ./kubeconfig
	@chmod 600 ./kubeconfig

setup-allure:
	@mkdir -p allure-results allure-report

setup-docker-base: check-env build setup-kubeconfig

test: setup-docker-base setup-allure
	@echo "Running tests with SUITE=$(SUITE)$(if $(MARKER), MARKER=$(MARKER))$(if $(RERUNS), RERUNS=$(RERUNS))..."
	@$(DOCKER_RUN) $(DOCKER_VOLUMES) \
		$(ENV_FILE_FLAG) \
		$(DOCKER_ENV) \
		--entrypoint bash \
		glueops-tests -ic "\
			pytest -vv \
				--color=no \
				--environment \"$(CAPTAIN_DOMAIN)\" \
				$(if $(MARKER),-m $(MARKER)) \
				$(if $(RERUNS),--reruns $(RERUNS) --reruns-delay 5) \
				$(ARGS) \
				--alluredir=/app/allure-results \
				$(PYTEST_COMMON_FLAGS)"; \
	echo "✅ Tests complete! Generate report with: make allure-serve"
	@docker exec allure-server pkill -HUP java 2>/dev/null || true

# Convenience aliases (shortcuts to common test patterns)
quick:
	@$(MAKE) test MARKER=quick SUITE=quick

api:
	@$(MAKE) test MARKER='smoke or write' SUITE=api

ui:
	@$(MAKE) test MARKER=ui RERUNS=0 SUITE=ui

gitops:
	@$(MAKE) test MARKER=gitops RERUNS=0 SUITE=gitops

gitops-deployment:
	@$(MAKE) test MARKER=gitops_deployment RERUNS=0 SUITE=gitops-deployment

externalsecrets:
	@$(MAKE) test MARKER=externalsecrets RERUNS=0 SUITE=externalsecrets

letsencrypt:
	@$(MAKE) test MARKER=letsencrypt RERUNS=0 SUITE=letsencrypt

preview-environments:
	@$(MAKE) test MARKER=preview_environments SUITE=preview-environments

full:
	@$(MAKE) test RERUNS=0 SUITE=full

# Cleanup
clean:
	rm -rf .pytest_cache allure-results allure-report kubeconfig

clean-reports:
	@echo "Removing Allure results and reports..."
	@sudo rm -rf allure-results allure-report screenshots allure-single-file
	@mkdir -p allure-results allure-report

clean-baselines:
	rm -f baselines/*.json

# Generate Allure HTML report from test results
allure-report: setup-allure
	@echo "Generating Allure HTML report..."
	@sudo chmod -R 777 allure-report
	@docker run --rm \
		-v "$$(pwd)/allure-results:/allure-results:ro" \
		-v "$$(pwd)/allure-report:/allure-report" \
		frankescobar/allure-docker-service \
		allure generate /allure-results -o /allure-report --clean
	@echo "✅ Report generated at: allure-report/index.html"
	@echo "   Open with: open allure-report/index.html (macOS) or xdg-open allure-report/index.html (Linux)"

# Generate portable single-file HTML report
allure-single-file: setup-allure
	@echo "Generating single-file Allure report..."
	@mkdir -p allure-single-file
	@sudo chmod -R 777 allure-single-file
	@docker run --rm \
		-v "$$(pwd)/allure-results:/allure-results:ro" \
		-v "$$(pwd)/allure-single-file:/allure-single-file" \
		frankescobar/allure-docker-service \
		allure generate /allure-results -o /allure-single-file --single-file --clean
	@echo "✅ Single-file report generated at: allure-single-file/index.html"
	@echo "   This file can be shared and opened directly in any browser"

# Generate and serve Allure report on http://localhost:5050
allure-serve: setup-allure
	@echo "Generating and serving Allure report..."
	@echo "📊 Allure report will be available at:"
	@echo "   http://localhost:5050/allure-docker-service/projects/default/reports/latest/index.html"
	@echo ""
	@echo "Press Ctrl+C to stop the server"
	@echo ""
	@sudo chmod -R 777 allure-results
	@docker rm -f allure-server 2>/dev/null || true
	@docker run --rm --init --name allure-server -p 5050:5050 \
		-e CHECK_RESULTS_EVERY_SECONDS=3 \
		-e KEEP_HISTORY=1 \
		-v "$$(pwd)/allure-results:/app/allure-results" \
		frankescobar/allure-docker-service || docker rm -f allure-server 2>/dev/null

# Upload results to Allure TestOps cloud
upload-results:
	@set -a && [ -f .env ] && . ./.env; set +a; \
	if [ -z "$$ALLURE_ENDPOINT" ] || [ -z "$$ALLURE_TOKEN" ] || [ -z "$$ALLURE_PROJECT_ID" ]; then \
		echo "❌ Error: Allure TestOps credentials not configured"; \
		echo "   Set ALLURE_ENDPOINT, ALLURE_TOKEN, and ALLURE_PROJECT_ID in .env"; \
		exit 1; \
	fi; \
	echo "📤 Uploading results to Allure TestOps..."; \
	LAUNCH_NAME="$${ALLURE_LAUNCH_NAME:-Test Run - $$(date +%Y-%m-%d)}"; \
	docker run --rm \
		-v "$$(pwd)/allure-results:/allure-results:ro" \
		-e ALLURE_ENDPOINT="$$ALLURE_ENDPOINT" \
		-e ALLURE_TOKEN="$$ALLURE_TOKEN" \
		-e ALLURE_PROJECT_ID="$$ALLURE_PROJECT_ID" \
		allure/allurectl:latest \
		upload /allure-results --launch-name "$$LAUNCH_NAME"; \
	echo "✅ Results uploaded to Allure TestOps!"

# Discovery targets
discover: setup-docker-base
	$(DOCKER_RUN) $(DOCKER_VOLUMES) $(ENV_FILE_FLAG) $(DOCKER_ENV) --entrypoint pytest glueops-tests --collect-only -v --color=yes

markers: setup-docker-base
	$(DOCKER_RUN) $(DOCKER_VOLUMES) $(ENV_FILE_FLAG) $(DOCKER_ENV) --entrypoint pytest glueops-tests --markers --color=yes

fixtures: setup-docker-base
	$(DOCKER_RUN) $(DOCKER_VOLUMES) $(ENV_FILE_FLAG) $(DOCKER_ENV) --entrypoint pytest glueops-tests --fixtures --color=yes

# List tests in various formats
list-tests:
	@$(MAKE) setup-docker-base
	@echo "📋 All test paths (copy-paste to run with 'make test <path>'):"
	@echo ""
	@$(DOCKER_RUN) $(DOCKER_VOLUMES) $(ENV_FILE_FLAG) $(DOCKER_ENV) --entrypoint sh glueops-tests -c "python3 list_tests.py 2>/dev/null | sed 's/^/  /'"
	@echo ""
	@echo "Usage: make test <path>"
	@echo "Example: make test tests/smoke/test_argocd.py::test_argocd_applications"

list-files:
	@$(MAKE) setup-docker-base
	@echo "📁 All test files (run entire file with 'make test <file>'):"
	@echo ""
	@$(DOCKER_RUN) $(DOCKER_VOLUMES) $(ENV_FILE_FLAG) $(DOCKER_ENV) --entrypoint sh glueops-tests -c "find tests -name 'test_*.py' -type f | sort | sed 's/^/  /'"
	@echo ""
	@echo "Usage: make test <file>"
	@echo "Example: make test tests/smoke/test_argocd.py"

# Static analysis targets
typecheck: setup-docker-base
	@echo "Running mypy type checking..."
	@$(DOCKER_RUN) $(DOCKER_VOLUMES) $(ENV_FILE_FLAG) $(DOCKER_ENV) --entrypoint sh glueops-tests -c "mypy tests/ --no-error-summary 2>&1 | head -100"

lint: setup-docker-base
	@echo "Running pylint code analysis..."
	@$(DOCKER_RUN) $(DOCKER_VOLUMES) $(ENV_FILE_FLAG) $(DOCKER_ENV) --entrypoint sh glueops-tests -c "pylint tests/ --disable=C,R,W --max-line-length=120 2>&1 | head -100"

ci: setup-docker-base  ## Run all static analysis checks (lint + typecheck)
	@echo "Running CI checks..."
	@echo "1/2 Running pylint..."
	@$(DOCKER_RUN) $(DOCKER_VOLUMES) $(ENV_FILE_FLAG) $(DOCKER_ENV) --entrypoint sh glueops-tests -c "pylint tests/ --disable=C,R,W --enable=W0404,W0611,W0102,W0106 --max-line-length=120"
	@echo "✓ Lint passed"
	@echo ""
	@echo "2/2 Running mypy..."
	@$(DOCKER_RUN) $(DOCKER_VOLUMES) $(ENV_FILE_FLAG) $(DOCKER_ENV) --entrypoint sh glueops-tests -c "mypy tests/ --warn-unused-ignores --warn-redundant-casts"
	@echo "✓ Type checks passed"
	@echo ""
	@echo "✅ All CI checks passed!"

# Catch-all pattern rule to allow passing test paths directly
# This allows: make test tests/smoke/test_file.py::test_name
%:
	@:
