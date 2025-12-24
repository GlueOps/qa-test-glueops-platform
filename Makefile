.PHONY: help test full verbose quick critical parallel ui build clean clean-baselines \
        local-test local-full local-verbose local-quick local-critical local-parallel local-ui \
        report-html report-json install discover markers fixtures \
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
	pytest tests/ui/ -v

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
		-e KUBECONFIG=/kubeconfig \
		glueops-tests -m smoke -v

full: build
	@echo "Copying kubeconfig to workspace..."
	@cp $${KUBECONFIG:-$$HOME/.kube/config} ./kubeconfig
	@chmod 600 ./kubeconfig
	docker run --rm --network host \
		-v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
		-v "/workspaces/glueops:/workspaces/glueops:ro" \
		-e KUBECONFIG=/kubeconfig \
		glueops-tests -m "smoke or write" -v

verbose: build
	@echo "Copying kubeconfig to workspace..."
	@cp $${KUBECONFIG:-$$HOME/.kube/config} ./kubeconfig
	@chmod 600 ./kubeconfig
	docker run --rm --network host \
		-v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
		-e KUBECONFIG=/kubeconfig \
		glueops-tests -m smoke -vv -s

quick: build
	@echo "Copying kubeconfig to workspace..."
	@cp $${KUBECONFIG:-$$HOME/.kube/config} ./kubeconfig
	@chmod 600 ./kubeconfig
	docker run --rm --network host \
		-v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
		-e KUBECONFIG=/kubeconfig \
		glueops-tests -m quick -v

critical: build
	@echo "Copying kubeconfig to workspace..."
	@cp $${KUBECONFIG:-$$HOME/.kube/config} ./kubeconfig
	@chmod 600 ./kubeconfig
	docker run --rm --network host \
		-v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
		-e KUBECONFIG=/kubeconfig \
		glueops-tests -m critical -v

parallel: build
	@echo "Copying kubeconfig to workspace..."
	@cp $${KUBECONFIG:-$$HOME/.kube/config} ./kubeconfig
	@chmod 600 ./kubeconfig
	docker run --rm --network host \
		-v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
		-e KUBECONFIG=/kubeconfig \
		glueops-tests -m smoke -n 8 -v

ui: build
	@echo "Copying kubeconfig to workspace..."
	@cp $${KUBECONFIG:-$$HOME/.kube/config} ./kubeconfig
	@chmod 600 ./kubeconfig
	docker run --rm --network host \
		-v "$$(pwd)/kubeconfig:/kubeconfig:ro" \
		-e KUBECONFIG=/kubeconfig \
		glueops-tests tests/ui/ -v

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
