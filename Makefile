.PHONY: help quick api ui full build clean clean-baselines results discover markers fixtures \
        check-env setup-kubeconfig setup-reports setup-ui-reports

# Docker run base configuration
DOCKER_RUN = docker run --rm --network host
DOCKER_VOLUMES = -v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
                 -v "/workspaces/glueops:/workspaces/glueops:ro" \
                 -v "$$(pwd)/reports:/app/reports" \
                 -v "$$(pwd)/baselines:/app/baselines"
DOCKER_VOLUMES_UI = -v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
                    -v "$$(pwd)/reports:/app/reports"
ENV_FILE_FLAG = $(shell [ -f .env ] && echo "--env-file .env" || echo "")

help:
	@echo "GlueOps Test Suite (Pytest)"
	@echo ""
	@echo "Test Execution:"
	@echo "  make quick         - Run quick tests (<5s) with verbose output"
	@echo "  make api           - Run API/K8s tests (smoke + write operations)"
	@echo "  make ui            - Run all UI tests (OAuth + authenticated)"
	@echo "  make full          - Run EVERYTHING (api + ui tests)"
	@echo ""
	@echo "Reports:"
	@echo "  make results       - Serve reports on http://localhost:8989"
	@echo "  Note: All commands generate HTML and JSON reports in reports/"
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

quick: check-env build setup-kubeconfig setup-reports
	$(DOCKER_RUN) $(DOCKER_VOLUMES) \
		$(ENV_FILE_FLAG) \
		-e KUBECONFIG=/kubeconfig \
		glueops-tests -m quick -vv \
		--html=reports/quick-report.html --self-contained-html \
		--json-report --json-report-file=reports/quick-report.json

api: check-env build setup-kubeconfig setup-reports
	$(DOCKER_RUN) $(DOCKER_VOLUMES) \
		$(ENV_FILE_FLAG) \
		-e KUBECONFIG=/kubeconfig \
		glueops-tests -m "smoke or write" -vv \
		--html=reports/api-report.html --self-contained-html \
		--json-report --json-report-file=reports/api-report.json

ui: check-env build setup-kubeconfig setup-ui-reports
	@echo "Running OAuth redirect tests..."
	$(DOCKER_RUN) $(DOCKER_VOLUMES_UI) \
		$(ENV_FILE_FLAG) \
		-e KUBECONFIG=/kubeconfig \
		glueops-tests -m oauth_redirect tests/ui/ -vv --reruns 2 --reruns-delay 120 \
		--html=reports/ui-oauth-report.html --self-contained-html \
		--json-report --json-report-file=reports/ui-oauth-report.json
	@echo "Running authenticated tests..."
	$(DOCKER_RUN) $(DOCKER_VOLUMES_UI) \
		$(ENV_FILE_FLAG) \
		-e KUBECONFIG=/kubeconfig \
		glueops-tests -m authenticated tests/ui/ -vv --reruns 2 --reruns-delay 120 \
		--html=reports/ui-auth-report.html --self-contained-html \
		--json-report --json-report-file=reports/ui-auth-report.json

full: check-env build setup-kubeconfig setup-reports setup-ui-reports
	@echo "Running ALL tests..."
	$(DOCKER_RUN) $(DOCKER_VOLUMES) \
		$(ENV_FILE_FLAG) \
		-e KUBECONFIG=/kubeconfig \
		glueops-tests -vv --reruns 2 --reruns-delay 120 \
		--html=reports/full-report.html --self-contained-html \
		--json-report --json-report-file=reports/full-report.json
	@echo "✅ Full test suite complete! Check reports/full-report.html for results."

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
