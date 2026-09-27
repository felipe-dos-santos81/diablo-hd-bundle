# Makefile for the Diablo animation regeneration kit
# Pipeline: caption -> (edit characters.yaml) -> batch -> review -> batch ... -> verify
SERVICE = Diablo Animation Regen

VENV_DIR = .venv
PY = $(VENV_DIR)/bin/python

# Arguments, e.g. make batch character="monsters/zombie" variants=0 force=1
character ?=
anim ?=
sheet ?=
src ?=
dst ?=
force ?=
variants ?= 1
variant ?=
memcheck ?= 1
strength ?=
workflow ?=
packing ?=
gutter ?=
background ?=
anchor ?= 1
concurrency ?=
FORCE_ARG = $(if $(force),--force)
ARGS = $(foreach c,$(character),--character $(c)) $(foreach a,$(anim),--anim $(a)) \
       $(foreach s,$(sheet),--sheet $(s)) \
       $(if $(src),--src "$(src)") $(if $(dst),--dst "$(dst)") \
       $(if $(filter 0,$(variants)),--no-variants) $(foreach v,$(variant),--variant $(v)) $(if $(packing),--packing $(packing)) \
       $(if $(gutter),--gutter $(gutter)) $(if $(background),--background $(background)) \
       $(if $(filter 0,$(anchor)),--no-anchor)
BATCH_ARGS = $(if $(filter 0,$(memcheck)),--no-memory-check) $(if $(strength),--match-strength $(strength)) \
             $(if $(workflow),--workflow $(workflow)) $(FORCE_ARG)

.PHONY: help install server caption dry-run batch review verify preview check test clean

help: ## Print this help message
	@printf '\033[01;32m${SERVICE}\033[00;37m\n\n'
	@printf "\033[33mUsage:\033[0m\n  make [target] [arg=\"val\"...]\n\n\033[33mTargets:\033[0m\n"
	@grep -E '^[-a-zA-Z0-9_\.\/]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; \
		{printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}'

# ── Environment ──────────────────────────────────────────────────────────────

install: ## Create .venv with Pillow, PyYAML and numpy (re-running is safe)
	@if [ ! -x "$(PY)" ]; then python3 -m venv $(VENV_DIR); fi
	@$(PY) -c 'import PIL, yaml, numpy' 2>/dev/null || $(VENV_DIR)/bin/pip install -q "pillow>=10" "pyyaml>=6" "numpy>=1.26"

server: ## Start ComfyUI on :8188 from ~/ComfyUI (override COMFY_DIR)
	./run_server.sh

clean: ## Remove __pycache__ (never touches data/)
	find . -path ./.venv -prune -o -type d -name "__pycache__" -exec rm -rf {} +

# ── Pipeline ─────────────────────────────────────────────────────────────────

caption: install ## [STEP 1] Seed characters.yaml, caption its characters with vLLM (character=, concurrency=, force=1)
	./run_batch.sh caption $(ARGS) $(if $(concurrency),--concurrency $(concurrency)) $(FORCE_ARG)

dry-run: install ## [STEP 2a] Show batch's sheets and statuses, without ComfyUI (character=, anim=, sheet=, variants=0)
	./run_batch.sh batch --dry-run $(ARGS) $(BATCH_ARGS)

batch: install ## [STEP 2] Render sheets via ComfyUI into data/anims-ai; stop vLLM first (character=, anim=, sheet=, variant=, variants=0, workflow=, strength=, memcheck=0, force=1)
	./run_batch.sh batch $(ARGS) $(BATCH_ARGS)

review: install ## [STEP 3] Review done sheets with vLLM into reviews.yaml (character=, sheet=, concurrency=, force=1)
	./run_batch.sh review $(ARGS) $(if $(concurrency),--concurrency $(concurrency)) $(FORCE_ARG)

verify: install ## [STEP 4] Audit data/anims-ai against the manifest, the 2x rule, the outline and the attempts (character=, sheet=)
	./run_batch.sh verify $(ARGS)

preview: install ## Write an animated GIF per direction into data/preview/<dst name> (character=, anim=, sheet=)
	./run_batch.sh preview $(ARGS)

# ── Development ──────────────────────────────────────────────────────────────

check: install ## Byte-compile the Python modules
	@$(PY) -m py_compile *.py && echo "check ok"

test: install ## Run the unit tests (no GPU, no network)
	$(PY) -m unittest discover -s . -p 'test_*.py'
