.PHONY: help test build clean clean-reports clean-baselines report discover markers fixtures \
        check-env setup-kubeconfig setup-allure setup-docker-base lint typecheck ci list-tests list-files

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

# Capture all args for pytest passthrough (everything except 'test')
# Usage: make test PYTEST_ARGS="-m quick tests/smoke/"
#        make test PYTEST_ARGS="-m observability"
#        make test PYTEST_ARGS="--update-baseline=all tests/smoke/"
# For passing args directly: make test tests/path (no flags starting with -)
PYTEST_ARGS ?=
# If PYTEST_ARGS not set via variable, try to capture from MAKECMDGOALS
ifeq ($(PYTEST_ARGS),)
PYTEST_ARGS = $(filter-out test,$(MAKECMDGOALS))
endif
PYTEST_FLAGS ?=
ALL_PYTEST_ARGS = $(PYTEST_FLAGS) $(PYTEST_ARGS)

help:
	@echo "GlueOps Test Suite (Pytest + Allure)"
	@echo ""
	@echo "Test Commands:"
	@echo "  make test                                               - Run all tests"
	@echo "  make test PYTEST_ARGS='-m <MARKER-NAME-HERE>'           - Run test by marker name"
	@echo "  make test PYTEST_ARGS='--update-baseline=all -m ui'     - Update baselines and run UI tests"
	@echo "  make test PYTEST_ARGS='tests/smoke/test_argocd.py'      - Run specific file"
	@echo "  make test PYTEST_ARGS='-m quick tests/smoke/'           - Combine marker + path"
	@echo ""
	@echo "Advanced: Override with PYTEST_FLAGS variable if needed:"
	@echo "  make test PYTEST_FLAGS='--reruns 0' PYTEST_ARGS='-m ui'"
	@echo ""
	@echo "Reports:"
	@echo "  make report        - Generate single-file HTML report (portable)"
	@echo ""
	@echo "Utilities:"
	@echo "  make build         - Build Docker image"
	@echo "  make clean         - Remove test artifacts and kubeconfig"
	@echo "  make clean-reports - Remove Allure results and reports"
	@echo "  make clean-baselines - Remove baseline files (Prometheus + screenshots)"
	@echo "  make list-tests    - List all runnable test paths (copy-paste ready)"
	@echo "  make list-files    - List all test files (run entire files)"
	@echo "  make ci            - Run all static analysis (lint + typecheck)"
	@echo ""
	@echo "Setup:"
	@echo "  1. Copy .env.example to .env"
	@echo "  2. Configure your environment variables"
	@echo "  3. Run: make test PYTEST_ARGS='-m quick'"
	@echo "  4. Generate report: make report"

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
	@echo "Running tests$(if $(ALL_PYTEST_ARGS), with args: $(ALL_PYTEST_ARGS))..."
	$(DOCKER_RUN) $(DOCKER_VOLUMES) \
		$(ENV_FILE_FLAG) \
		$(DOCKER_ENV) \
		--entrypoint pytest \
		glueops-tests \
		-vv \
		--color=no \
		--environment "$(CAPTAIN_DOMAIN)" \
		--alluredir=/app/allure-results \
		$(ALL_PYTEST_ARGS)
	@echo "✅ Tests complete! Generate report with: make report"
	@docker exec allure-server pkill -HUP java 2>/dev/null || true

# Cleanup
clean:
	rm -rf .pytest_cache allure-results allure-report kubeconfig

clean-reports:
	@echo "Removing Allure results and reports..."
	@sudo rm -rf allure-results allure-report screenshots allure-single-file
	@mkdir -p allure-results allure-report

clean-baselines:
	rm -f baselines/*.json baselines/**/*.png

# Generate portable single-file HTML report, upload to Slack, and cleanup
report: setup-allure
	@if [ -z "$$(ls -A allure-results/*.json 2>/dev/null)" ]; then \
		echo "❌ No test results found in allure-results/. Run 'make test' first."; \
		exit 1; \
	fi
	$(eval REPORT_TS := $(shell date +%Y%m%d-%H%M%S))
	@echo "Generating single-file HTML report..."
	@mkdir -p allure-single-file
	@sudo chmod -R 777 allure-single-file
	@docker run --rm \
		-v "$$(pwd)/allure-results:/allure-results:ro" \
		-v "$$(pwd)/allure-single-file:/allure-single-file" \
		frankescobar/allure-docker-service@sha256:4154286c02096d42cc56d65e6bb786d9710da9aa4f0e6e8a29af0ca909b0faf0 \
		allure generate /allure-results -o /allure-single-file --single-file --clean
	@mv allure-single-file/index.html allure-single-file/report-$(REPORT_TS).html
	@echo "✅ Report generated: allure-single-file/report-$(REPORT_TS).html"
	@echo "Uploading to Slack..."
	@docker run --rm \
		-v "$$(pwd)/allure-single-file:/allure-single-file:ro" \
		-v "$$(pwd)/send-to-slack.sh:/send-to-slack.sh:ro" \
		$(ENV_FILE_FLAG) \
		dwdraju/alpine-curl-jq@sha256:eb00b3d4864c03814885a1c15ed1f5b2b569ca102ad4d02c27d582affb4fd6b1 \
		/bin/sh /send-to-slack.sh /allure-single-file/report-$(REPORT_TS).html \
		&& rm -f allure-single-file/report-$(REPORT_TS).html \
		&& echo "✅ Uploaded to Slack and cleaned up report"
	@$(MAKE) clean-reports

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

# Visual regression testing targets
.PHONY: visual-tests update-baselines

visual-tests: setup-docker-base  ## Run visual regression tests
	@docker compose run --rm test pytest -m visual -v

update-baselines: setup-docker-base  ## Update all visual regression baselines
	@docker compose run --rm test pytest -m visual --update-baseline=all -v

# Catch-all pattern rule to allow passing test paths directly
# This allows: make test tests/smoke/test_file.py::test_name
%:
	@:
