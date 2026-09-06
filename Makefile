# Reproduction targets. Override the interpreter with e.g. `make PYTHON=.venv/Scripts/python.exe baseline`.
PYTHON ?= python

.PHONY: help validate selftest baseline selection fixed-k figures clean

help:
	@echo "validate   - molecular reference energies + Qiskit/PennyLane noise equivalence (fast)"
	@echo "selftest   - per-module self-tests (SLOW: the ADAPT self-tests run noisy sweeps)"
	@echo "baseline   - Result 1: 5-strategy sweep            -> results/results.csv"
	@echo "selection  - the 4 selection rules, scoped         -> results/results_novel.csv"
	@echo "fixed-k    - matched-operator-count control        -> results/results_fixed_k.csv"
	@echo "figures    - comparison tables + PNGs from the CSVs"

validate:
	$(PYTHON) molecules.py
	$(PYTHON) noise_models.py

selftest: validate
	$(PYTHON) qiskit_baselines.py
	$(PYTHON) pennylane_resource_aware_adapt.py
	$(PYTHON) verify_fix.py

baseline:
	$(PYTHON) run_experiments.py --skip-validation --out results/results.csv \
		--strategies "UCCSD" "HEA" "ADAPT-VQE(standard)" "ADAPT-VQE(standard,PL)" "ADAPT-VQE(resource-aware)"

selection:
	$(PYTHON) run_experiments.py --skip-validation --out results/results_novel.csv \
		--pl-max-operators 8 --pl-opt-maxiter 100

fixed-k:
	$(PYTHON) fixed_k_experiment.py

figures:
	$(PYTHON) analyze_results.py --csv results/results.csv --outdir results
	$(PYTHON) analyze_results.py --csv results/results_novel.csv --outdir results/novel

clean:
	rm -rf __pycache__ .pytest_cache
