.PHONY: help test full verbose quick critical parallel ui build clean clean-baselines \
        local-test local-full local-verbose local-quick local-critical local-parallel local-ui \
        report-html report-json install discover markers fixtures results \
        local-discover local-markers local-fixtures

help:
	@echo "GlueOps Test Suite (Pytest)"
	@echo ""
	@echo "Docker execution (default):"
	@echo "  make test          - Run smoke tests in Docker"
	@echo "  make full          - Run full tests (smoke + write operations)"
	@echo "  make verbose       - Run with verbose output"
	@echo "  make quick         - Run only quick tests (<5s)"
	@echo "  make critical      - Run only critical tests"
	@echo "  make parallel      - Run tests in parallel (8 workers)"
	@echo "  make ui            - Run UI tests (Selenium/Playwright)"
	@echo "  make build         - Build Docker image"
	@echo ""
	@echo "Local execution (requires: make local-install):"
	@echo "  make local-test    - Run smoke tests locally"
	@echo "  make local-full    - Run full tests locally"
	@echo "  make local-verbose - Run with verbose output locally"
	@echo "  make local-quick   - Run quick tests locally"
	@echo "  make local-critical - Run critical tests locally"
	@echo "  make local-parallel - Run tests in parallel locally"
	@echo "  make local-ui      - Run UI tests locally"
	@echo ""
	@echo "Reports:"
	@echo "  make report-html   - Generate HTML test report"
	@echo "  make report-json   - Generate JSON test report"
	@echo "  make results       - Serve reports on http://localhost:8989"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean         - Remove test artifacts and kubeconfig"
	@echo "  make clean-baselines - Remove Prometheus metrics baseline files"
	@echo "  make local-install - Install Python dependencies locally"
	@echo ""
	@echo "Test Discovery (Docker):"
	@echo "  make discover      - List all tests with descriptions"
	@echo "  make markers       - Show available markers"
	@echo "  make fixtures      - Show available fixtures"
	@echo ""
	@echo "Test Discovery (Local):"
	@echo "  make local-discover - List all tests with descriptions locally"
	@echo "  make local-markers  - Show available markers locally"
	@echo "  make local-fixtures - Show available fixtures locally"

# Local execution targets
local-install:
	pip install -r requirements.txt

local-test:
	pytest -m smoke -v

local-full:
	pytest -m "smoke or write" -v

local-verbose:
	pytest -m smoke -vv -s

local-quick:
	pytest -m quick -v

local-critical:
	pytest -m critical -v

local-parallel:
	pytest -m smoke -n 8 -v

local-ui:
	@echo "Running OAuth redirect tests first (no auth)..."
	pytest -m oauth_redirect tests/ui/ -v
	@echo "Running authenticated tests (requires credentials)..."
	pytest -m authenticated tests/ui/ -v

local-ui-oauth:
	pytest -m oauth_redirect tests/ui/ -v

local-ui-auth:
	pytest -m authenticated tests/ui/ -v

# Local discovery targets
local-discover:
	pytest --collect-only -v --color=yes

local-markers:
	pytest --markers --color=yes

local-fixtures:
	pytest --fixtures --color=yes

# Docker targets (default)
build:
	docker build -t glueops-tests .

test: build
	@echo "Copying kubeconfig to workspace..."
	@cp $${KUBECONFIG:-$$HOME/.kube/config} ./kubeconfig
	@chmod 600 ./kubeconfig
	docker run --rm --network host \
		-v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
		-v "/workspaces/glueops:/workspaces/glueops:ro" \
		-e KUBECONFIG=/kubeconfig \
		-e CAPTAIN_DOMAIN="$${CAPTAIN_DOMAIN}" \
		glueops-tests -m smoke -v

full: build
	@echo "Copying kubeconfig to workspace..."
	@cp $${KUBECONFIG:-$$HOME/.kube/config} ./kubeconfig
	@chmod 600 ./kubeconfig
	docker run --rm --network host \
		-v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
		-v "/workspaces/glueops:/workspaces/glueops:ro" \
		-e KUBECONFIG=/kubeconfig \
		-e CAPTAIN_DOMAIN="$${CAPTAIN_DOMAIN}" \
		glueops-tests -m "smoke or write" -v

verbose: build
	@echo "Copying kubeconfig to workspace..."
	@cp $${KUBECONFIG:-$$HOME/.kube/config} ./kubeconfig
	@chmod 600 ./kubeconfig
	docker run --rm --network host \
		-v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
		-v "/workspaces/glueops:/workspaces/glueops:ro" \
		-e KUBECONFIG=/kubeconfig \
		-e CAPTAIN_DOMAIN="$${CAPTAIN_DOMAIN}" \
		glueops-tests -m smoke -vv -s

quick: build
	@echo "Copying kubeconfig to workspace..."
	@cp $${KUBECONFIG:-$$HOME/.kube/config} ./kubeconfig
	@chmod 600 ./kubeconfig
	docker run --rm --network host \
		-v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
		-v "/workspaces/glueops:/workspaces/glueops:ro" \
		-e KUBECONFIG=/kubeconfig \
		-e CAPTAIN_DOMAIN="$${CAPTAIN_DOMAIN}" \
		glueops-tests -m quick -v

critical: build
	@echo "Copying kubeconfig to workspace..."
	@cp $${KUBECONFIG:-$$HOME/.kube/config} ./kubeconfig
	@chmod 600 ./kubeconfig
	docker run --rm --network host \
		-v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
		-v "/workspaces/glueops:/workspaces/glueops:ro" \
		-e KUBECONFIG=/kubeconfig \
		-e CAPTAIN_DOMAIN="$${CAPTAIN_DOMAIN}" \
		glueops-tests -m critical -v

parallel: build
	@echo "Copying kubeconfig to workspace..."
	@cp $${KUBECONFIG:-$$HOME/.kube/config} ./kubeconfig
	@chmod 600 ./kubeconfig
	docker run --rm --network host \
		-v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
		-v "/workspaces/glueops:/workspaces/glueops:ro" \
		-e KUBECONFIG=/kubeconfig \
		-e CAPTAIN_DOMAIN="$${CAPTAIN_DOMAIN}" \
		glueops-tests -m smoke -n 8 -v

ui: build
	@echo "Copying kubeconfig to workspace..."
	@cp $${KUBECONFIG:-$$HOME/.kube/config} ./kubeconfig
	@chmod 600 ./kubeconfig
	@mkdir -p reports/screenshots
	@echo "Running OAuth redirect tests first (no auth)..."
	docker run --rm --network host \
		-v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
		-v "$$(pwd)/reports:/app/reports" \
		-e KUBECONFIG=/kubeconfig \
		glueops-tests -m oauth_redirect tests/ui/ -v \
		--html=reports/ui-oauth-report.html --self-contained-html
	@echo "Running authenticated tests (requires credentials)..."
	docker run --rm --network host \
		-v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
		-v "$$(pwd)/reports:/app/reports" \
		-e KUBECONFIG=/kubeconfig \
		-e GITHUB_USERNAME="$${GITHUB_USERNAME}" \
		-e GITHUB_PASSWORD="$${GITHUB_PASSWORD}" \
		-e GITHUB_OTP_SECRET="$${GITHUB_OTP_SECRET}" \
		-e USE_BROWSERBASE="$${USE_BROWSERBASE}" \
		glueops-tests -m authenticated tests/ui/ -v \
		--html=reports/ui-auth-report.html --self-contained-html

ui-oauth: build
	@echo "Copying kubeconfig to workspace..."
	@cp $${KUBECONFIG:-$$HOME/.kube/config} ./kubeconfig
	@chmod 600 ./kubeconfig
	@mkdir -p reports/screenshots
	docker run --rm --network host \
		-v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
		-v "$$(pwd)/reports:/app/reports" \
		-e KUBECONFIG=/kubeconfig \
		-e USE_BROWSERBASE="$${USE_BROWSERBASE}" \
		glueops-tests -m oauth_redirect tests/ui/ -v \
		--html=reports/ui-oauth-report.html --self-contained-html

ui-auth: build
	@echo "Copying kubeconfig to workspace..."
	@cp $${KUBECONFIG:-$$HOME/.kube/config} ./kubeconfig
	@chmod 600 ./kubeconfig
	@mkdir -p reports/screenshots
	docker run --rm --network host \
		-v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
		-v "$$(pwd)/reports:/app/reports" \
		-e KUBECONFIG=/kubeconfig \
		-e CAPTAIN_DOMAIN="$${CAPTAIN_DOMAIN}" \
		-e GITHUB_USERNAME="$${GITHUB_USERNAME}" \
		-e GITHUB_PASSWORD="$${GITHUB_PASSWORD}" \
		-e GITHUB_OTP_SECRET="$${GITHUB_OTP_SECRET}" \
		-e USE_BROWSERBASE="$${USE_BROWSERBASE}" \
		glueops-tests -m authenticated tests/ui/ -v \
		--html=reports/ui-auth-report.html --self-contained-html

# Reports
report-html: build
	@cp $${KUBECONFIG:-$$HOME/.kube/config} ./kubeconfig
	@chmod 600 ./kubeconfig
	docker run --rm --network host \
		-v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
		-v "$$(pwd)/reports:/app/reports" \
		-e KUBECONFIG=/kubeconfig \
		glueops-tests -m smoke --html=reports/report.html --self-contained-html

report-json: build
	@cp $${KUBECONFIG:-$$HOME/.kube/config} ./kubeconfig
	@chmod 600 ./kubeconfig
	docker run --rm --network host \
		-v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
		-v "$$(pwd)/reports:/app/reports" \
		-e KUBECONFIG=/kubeconfig \
		glueops-tests -m smoke --json-report --json-report-file=reports/report.json

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

# Discovery targets (Docker)
discover: build
	docker run --rm -t \
		glueops-tests --collect-only -v --color=yes

markers: build
	docker run --rm -t \
		glueops-tests --markers --color=yes

fixtures: build
	docker run --rm -t \
		glueops-tests --fixtures --color=yes
