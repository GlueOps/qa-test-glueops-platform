.PHONY: help test quick api ui gitops full build clean clean-baselines results discover markers fixtures \
        check-env setup-kubeconfig setup-reports setup-ui-reports

# Docker run base configuration
DOCKER_RUN = docker run --rm --network host
DOCKER_VOLUMES = -v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
                 -v "/workspaces/glueops:/workspaces/glueops:ro" \
                 -v "$$(pwd)/reports:/app/reports" \
                 -v "$$(pwd)/baselines:/app/baselines" \
                 -v "$$(pwd):/app"
DOCKER_VOLUMES_UI = -v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
                    -v "$$(pwd)/reports:/app/reports" \
                    -v "$$(pwd):/app"
ENV_FILE_FLAG = $(shell [ -f .env ] && echo "--env-file .env" || echo "")

# Git metadata
GIT_BRANCH = $$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'N/A')
GIT_COMMIT = $$(git rev-parse --short HEAD 2>/dev/null || echo 'N/A')

# Timestamp for unique report names
REPORT_TIMESTAMP = $$(date +%Y%m%d-%H%M%S)

# Optional arguments for test customization (captures paths after 'make test')
ARGS ?= $(filter-out test quick api ui gitops full,$(MAKECMDGOALS))

# Common pytest flags
PYTEST_COMMON_FLAGS = --screenshots=reports/screenshots \
                      --git-branch="$(GIT_BRANCH)" \
                      --git-commit="$(GIT_COMMIT)"

# Report files function (usage: $(call REPORT_FILES,name))
define REPORT_FILES
--json-report=reports/$(1)-$(REPORT_TIMESTAMP).json --html-output=reports/$(1)-$(REPORT_TIMESTAMP)
endef

# Post-test metadata copy
define COPY_METADATA
	@if [ -f plus_metadata.json ]; then cp plus_metadata.json reports/; fi
endef

help:
	@echo "GlueOps Test Suite (Pytest)"
	@echo ""
	@echo "Test Execution:"
	@echo "  make test ARGS=<path>  - Run any specific test(s)"
	@echo "                           Example: make test ARGS=tests/smoke/test_argocd.py::test_argocd_applications"
	@echo "  make quick             - Run quick tests (<5s) with verbose output"
	@echo "  make api               - Run API/K8s tests (smoke + write operations)"
	@echo "  make ui                - Run all UI tests (OAuth + authenticated)"
	@echo "  make gitops            - Run GitOps integration tests"
	@echo "  make full              - Run EVERYTHING (api + ui + gitops tests)"
	@echo ""
	@echo "  Add ARGS to narrow tests: make quick ARGS=tests/smoke/test_argocd.py"
	@echo ""
	@echo "Reports:"
	@echo "  make results           - Serve reports on http://localhost:8989"
	@echo "  Note: All commands generate timestamped HTML and JSON reports in reports/"
	@echo ""
	@echo "Utilities:"
	@echo "  make build         - Build Docker image"
	@echo "  make clean         - Remove test artifacts and kubeconfig"
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
	$(DOCKER_RUN) $(DOCKER_VOLUMES) \
		$(ENV_FILE_FLAG) \
		-e KUBECONFIG=/kubeconfig \
		glueops-tests -vv $(ARGS) \
		$(call REPORT_FILES,test) $(PYTEST_COMMON_FLAGS)
	$(COPY_METADATA)

quick: check-env build setup-kubeconfig setup-reports
	$(DOCKER_RUN) $(DOCKER_VOLUMES) \
		$(ENV_FILE_FLAG) \
		-e KUBECONFIG=/kubeconfig \
		glueops-tests -m quick -vv $(ARGS) \
		$(call REPORT_FILES,quick) $(PYTEST_COMMON_FLAGS)
	$(COPY_METADATA)

api: check-env build setup-kubeconfig setup-reports
	$(DOCKER_RUN) $(DOCKER_VOLUMES) \
		$(ENV_FILE_FLAG) \
		-e KUBECONFIG=/kubeconfig \
		glueops-tests -m "smoke or write" -vv $(ARGS) \
		$(call REPORT_FILES,api) $(PYTEST_COMMON_FLAGS)
	$(COPY_METADATA)

ui: check-env build setup-kubeconfig setup-ui-reports
	@echo "Running OAuth redirect tests..."
	$(DOCKER_RUN) $(DOCKER_VOLUMES_UI) \
		$(ENV_FILE_FLAG) \
		-e KUBECONFIG=/kubeconfig \
		glueops-tests -m oauth_redirect tests/ui/ -vv --reruns 2 --reruns-delay 5 $(ARGS) \
		$(call REPORT_FILES,ui-oauth) $(PYTEST_COMMON_FLAGS)
	$(COPY_METADATA)
	@echo "Running authenticated tests..."
	$(DOCKER_RUN) $(DOCKER_VOLUMES_UI) \
		$(ENV_FILE_FLAG) \
		-e KUBECONFIG=/kubeconfig \
		glueops-tests -m authenticated tests/ui/ -vv --reruns 2 --reruns-delay 5 $(ARGS) \
		$(call REPORT_FILES,ui-auth) $(PYTEST_COMMON_FLAGS)
	$(COPY_METADATA)

gitops: check-env build setup-kubeconfig setup-reports
	@echo "Running GitOps integration tests..."
	$(DOCKER_RUN) $(DOCKER_VOLUMES) \
		$(ENV_FILE_FLAG) \
		-e KUBECONFIG=/kubeconfig \
		glueops-tests -m gitops -vv --reruns 2 --reruns-delay 5 $(ARGS) \
		$(call REPORT_FILES,gitops) $(PYTEST_COMMON_FLAGS)
	$(COPY_METADATA)

full: check-env build setup-kubeconfig setup-reports setup-ui-reports
	@echo "Running ALL tests..."
	$(DOCKER_RUN) $(DOCKER_VOLUMES) \
		$(ENV_FILE_FLAG) \
		-e KUBECONFIG=/kubeconfig \
		glueops-tests -vv --reruns 2 --reruns-delay 5 $(ARGS) \
		$(call REPORT_FILES,full) $(PYTEST_COMMON_FLAGS)
	$(COPY_METADATA)
	@echo "✅ Full test suite complete! Check reports/ for timestamped results."

# Cleanup
clean:
	rm -rf .pytest_cache reports/*.html reports/*.json kubeconfig

clean-baselines:
	rm -f baselines/*.json

# Serve test reports and screenshots on port 8989
results:
	@echo "Starting web server for test reports..."
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
