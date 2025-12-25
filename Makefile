.PHONY: help test build clean clean-reports clean-baselines collect serve discover markers fixtures \
        check-env setup-kubeconfig setup-reports setup-ui-reports \
        quick api ui gitops full

# Docker run base configuration
DOCKER_RUN = docker run --rm --network host
DOCKER_VOLUMES = -v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
                 -v "/workspaces/glueops:/workspaces/glueops:ro" \
                 -v "$$(pwd)/reports:/app/reports" \
                 -v "$$(pwd)/baselines:/app/baselines" \
                 -v "$$(pwd):/app"
ENV_FILE_FLAG = $(shell [ -f .env ] && echo "--env-file .env" || echo "")

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
PYTEST_COMMON_FLAGS = --screenshots=reports/screenshots \
                      --capture-screenshots=all \
                      --git-branch="$(GIT_BRANCH)" \
                      --git-commit="$(GIT_COMMIT)"

help:
	@echo "GlueOps Test Suite (Pytest)"
	@echo ""
	@echo "Quick Commands (shortcuts):"
	@echo "  make quick             - Run quick tests (<5s)"
	@echo "  make api               - Run API/K8s tests (smoke + write)"
	@echo "  make ui                - Run UI tests with retries"
	@echo "  make gitops            - Run GitOps tests with retries"
	@echo "  make full              - Run full suite with retries"
	@echo ""
	@echo "Advanced Usage (unified command):"
	@echo "  make test                                - Run all tests"
	@echo "  make test MARKER=quick                   - Run quick tests"
	@echo "  make test MARKER=gitops RERUNS=2         - Run gitops with retries"
	@echo "  make test MARKER='smoke or write'        - Run API/K8s tests"
	@echo "  make test tests/smoke/test_argocd.py     - Run specific file"
	@echo "  make test MARKER=quick tests/smoke/      - Combine marker + path"
	@echo "  make test SUITE=mytest MARKER=smoke      - Custom report name"
	@echo ""
	@echo ""
	@echo "Reports:"
	@echo "  make serve             - Collect and serve reports on http://localhost:8989"
	@echo "  make collect           - Move test reports to reports/ directory"
	@echo "  Note: All commands generate timestamped HTML and JSON reports"
	@echo ""
	@echo "Utilities:"
	@echo "  make build         - Build Docker image"
	@echo "  make clean         - Remove test artifacts and kubeconfig"
	@echo "  make clean-reports - Remove all gitignored files from reports/"
	@echo "  make clean-baselines - Remove Prometheus metrics baseline files"
	@echo "  make discover      - List all tests with descriptions"
	@echo "  make markers       - Show available pytest markers"
	@echo "  make fixtures      - Show available pytest fixtures"
	@echo ""
	@echo "Setup:"
	@echo "  1. Copy .env.example to .env"
	@echo "  2. Configure your environment variables"
	@echo "  3. Run: make quick, make api, make ui, or make full"

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

setup-reports:
	@mkdir -p reports

setup-ui-reports:
	@mkdir -p reports/screenshots

test: check-env build setup-kubeconfig setup-reports
	@echo "Running tests with SUITE=$(SUITE)$(if $(MARKER), MARKER=$(MARKER))$(if $(RERUNS), RERUNS=$(RERUNS))..."
	@TIMESTAMP=$$(date -u +%Y%m%d-%H%M%S); \
	$(DOCKER_RUN) $(DOCKER_VOLUMES) \
		$(ENV_FILE_FLAG) \
		-e KUBECONFIG=/kubeconfig \
		-e TZ=UTC \
		--entrypoint sh \
		glueops-tests -c "\
			pytest -vv \
				--environment \"$(CAPTAIN_DOMAIN)\" \
				$(if $(MARKER),-m $(MARKER)) \
				$(if $(RERUNS),--reruns $(RERUNS) --reruns-delay 5) \
				$(ARGS) \
				--json-report=reports-$(SUITE)-$${TIMESTAMP}.json --html-output=reports-$(SUITE)-$${TIMESTAMP} $(PYTEST_COMMON_FLAGS); \
			EXIT=\$$?; \
			if [ -f plus_metadata.json ] && [ -d reports-$(SUITE)-$${TIMESTAMP} ]; then \
				cp plus_metadata.json reports-$(SUITE)-$${TIMESTAMP}/; \
			fi; \
			exit \$$EXIT"; \
	echo "✅ Tests complete! Report: reports-$(SUITE)-$${TIMESTAMP}/report.html"

# Convenience aliases (shortcuts to common test patterns)
quick:
	@$(MAKE) test MARKER=quick SUITE=quick

api:
	@$(MAKE) test MARKER='smoke or write' SUITE=api

ui:
	@$(MAKE) test MARKER=ui RERUNS=2 SUITE=ui

gitops:
	@$(MAKE) test MARKER=gitops RERUNS=2 SUITE=gitops

full:
	@$(MAKE) test RERUNS=2 SUITE=full

# Cleanup
clean:
	rm -rf .pytest_cache reports/*.html reports/*.json kubeconfig

clean-reports:
	@echo "Removing all test reports and artifacts from reports/..."
	@sudo find reports -type f -not -name '.keep' -delete
	@sudo find reports -mindepth 1 -type d -empty -delete

clean-baselines:
	rm -f baselines/*.json

# Collect test reports from workspace root to reports/ directory
collect:
	@echo "Collecting test reports to reports/ directory..."
	@if ls reports-* 1> /dev/null 2>&1; then \
		sudo mv reports-* reports/ 2>/dev/null && echo "✅ Reports moved to reports/"; \
	else \
		echo "No reports to collect"; \
	fi

# Serve test reports and screenshots on port 8989
serve: collect
	@echo "Starting web server for test reports..."
	@lsof -ti:8989 | xargs kill -9 2>/dev/null || true
	@echo "Access reports at: http://localhost:8989/"
	@echo "Press Ctrl+C to stop the server"
	@cd reports && python3 -m http.server 8989

# Discovery targets
discover: build
	docker run --rm -t glueops-tests --collect-only -v --color=yes

markers: build
	docker run --rm -t glueops-tests --markers --color=yes

fixtures: build
	docker run --rm -t glueops-tests --fixtures --color=yes

# Catch-all pattern rule to allow passing test paths directly
# This allows: make test tests/smoke/test_file.py::test_name
%:
	@:
