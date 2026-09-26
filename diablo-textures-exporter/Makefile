# Makefile for dtx — Diablo + Hellfire graphics exporter
# Targets follow the pipeline:
#   install → 1 refdata → 2 extract → test
SERVICE = dtx

# Variables
UV = uv
DVX_REPO = https://github.com/diasurgical/devilutionx
DVX_COMMIT = 8bef7bce51641b8faa1f56f4119e5b6ee6ec6f3f
game ?= $(HOME)/diablo1-hellfire-gog
out ?= out
dvx ?= $(HOME)/.cache/dtx/devilutionx
community ?= $(HOME)/.cache/dtx/diablo-listfile.txt

.PHONY: help install clean devilutionx refdata extract test test-game

# ── Environment ──────────────────────────────────────────────────────────────

help: ## Print this help message
	@printf '\033[01;32m${SERVICE} — Diablo + Hellfire graphics exporter\033[00;37m\n\n'
	@printf "\033[33mUsage:\033[0m\n  make [target] [arg=\"val\"...]\n\n\033[33mTargets:\033[0m\n"
	@grep -E '^[-a-zA-Z0-9_\.\/]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; \
		{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install StormLib (Homebrew) and the Python environment (uv)
	@brew list stormlib >/dev/null 2>&1 || brew install stormlib
	@$(UV) sync
	@echo "Environment setup complete."

clean: ## Remove the venv, caches and exported output
	rm -rf .venv .pytest_cache "$(out)"
	find . -type d -name "__pycache__" -exec rm -rf {} +
	@echo "Cleanup complete."

# ── Stage 1 · Reference data ─────────────────────────────────────────────────

devilutionx: ## Clone DevilutionX at the pinned commit (usage: make devilutionx [dvx=path])
	@if [ ! -d "$(dvx)" ]; then git clone --filter=blob:none $(DVX_REPO) "$(dvx)"; fi
	@git -C "$(dvx)" checkout -q $(DVX_COMMIT)

refdata: install devilutionx ## [STEP 1] Regenerate listfile and width tables (usage: make refdata [community=listfile.txt])
	$(UV) run dtx refdata build --devilutionx "$(dvx)" --game "$(game)" $(if $(wildcard $(community)),--community "$(community)")

# ── Stage 2 · Export ─────────────────────────────────────────────────────────

extract: install ## [STEP 2] Export and verify all graphics (usage: make extract [game=dir] [out=dir] [only=tileset,layout] [force=1] [jobs=8])
	$(UV) run dtx extract --game "$(game)" --out "$(out)" --verify $(if $(only),--only "$(only)") $(if $(force),--force) $(if $(jobs),--jobs "$(jobs)")

# ── Development ──────────────────────────────────────────────────────────────

test: install ## Run the unit tests (no game data needed)
	$(UV) run pytest -q

test-game: install ## Run all tests, including those that read the game archives (usage: make test-game [game=dir])
	DTX_GAME_DIR="$(game)" $(UV) run pytest -q
