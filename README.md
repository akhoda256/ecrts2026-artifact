# Artifact Evaluation Guide

## Overview

This artifact contains two evaluation parts.

1. **Hardware validation test**: runs a hardware profiling experiment and plots measured frequency, temperature, and power.
2. **Simulation-based evaluation**: reproduces the simulation experiments used in the paper. This part has three steps:
   - generate task sets,
   - generate acceptance-ratio results,
   - run the dynamic boost-cancellation simulation and extract the remaining experimental results.

All scripts are executed using:

```bash
bash script_name.sh
```

This avoids requiring execute permission on the shell files.

---

# Part 1: Hardware Validation Test

## 1. Purpose

The hardware validation test checks that the platform can expose the execution modes assumed by the paper: nominal execution, boosted execution, and idle behavior. The profiling script collects measurements such as CPU frequency, temperature, and power. The plotting script then generates figures from the collected log file.

The expected workflow is:

```bash
bash exp2.sh
bash run_plot_docker.sh
```

The first script performs profiling. The second script runs the plotting step inside Docker and saves the generated figures in the shared folder.

## 2. Required Packages

The profiling step requires the following Linux tools:

- `stress-ng`: generates CPU workload.
- `lm-sensors`: provides the `sensors` command for temperature readings.
- `docker.io`: runs the plotting script in an isolated Python environment.

Install them using:

```bash
sudo apt update
sudo apt install -y stress-ng lm-sensors docker.io
```

After installing `lm-sensors`, detect available hardware sensors:

```bash
sudo sensors-detect
```

Then check that sensor readings are available:

```bash
sensors
```

If temperature values are printed, the sensor setup is working.

## 3. Checking Docker

Check that Docker is available:

```bash
docker --version
```

Then check whether Docker can be run without `sudo`:

```bash
docker ps
```

If this command fails with a permission error, it is acceptable to use `sudo docker`. The provided helper scripts automatically fall back to `sudo docker` when needed.

## 4. Running the Profiling Script

Run:

```bash
bash exp2.sh
```

The script may ask for the administrator password because some system-level commands require elevated privileges.

A typical execution starts as follows:

```bash
bash exp2.sh
[sudo] password for behnam:
Iteration 1 / 10
```

The profiling script generates a CSV log file, typically:

```bash
log.csv
```

The plotting step expects this file to be available as `log.csv`.

## 5. Running the Plotting Script

After profiling, run:

```bash
bash run_plot_docker.sh
```

This script runs the Python plotting script inside Docker. It uses the profiling log and generates the following figures:

```bash
real-frequency.png
real-temperature.png
real-power.png
```

The output files are saved in:

```bash
shared/
```

Check the result using:

```bash
ls shared/
```

A successful run should show files similar to:

```bash
log.csv  plot.py  real-frequency.png  real-power.png  real-temperature.png
```

## 6. Common Problems

### Missing `stress-ng`

If the following error appears:

```bash
taskset: failed to execute stress-ng: No such file or directory
```

install `stress-ng`:

```bash
sudo apt install -y stress-ng
```

### Missing `sensors`

If the following error appears:

```bash
sensors: command not found
```

install `lm-sensors`:

```bash
sudo apt install -y lm-sensors
sudo sensors-detect
sensors
```

### Docker permission error

If Docker prints:

```bash
permission denied while trying to connect to the docker API at unix:///var/run/docker.sock
```

then the user does not currently have permission to access Docker directly. The helper scripts use `sudo docker` automatically in this case.

## 7. Complete Commands for Part 1

```bash
sudo apt update
sudo apt install -y stress-ng lm-sensors docker.io
sudo sensors-detect
sensors
bash exp2.sh
bash run_plot_docker.sh
ls shared/
```

---

# Part 2: Simulation-Based Evaluation

## 8. Purpose

The second part reproduces the simulation-based evaluation from the paper. It uses synthetic implicit-deadline periodic task sets and evaluates Boosted-FP under Rate Monotonic Scheduling.

This part has three steps:

1. **Task-set generation** using `run_part2_generate.sh`.
2. **Acceptance-ratio evaluation** using `run_part2_acceptance.sh`.
3. **Dynamic simulation and result extraction** using `run_part2_dynamic.sh`.

All Python commands are executed inside Docker. The host machine only needs Docker.

## 9. Experimental Setup and Configurable Parameters

The simulation uses task-set sizes:

```bash
n = 3, 4, 5, 6, 7, 8
```

Target utilization ranges from 70% to 100% in steps of 5%:

```bash
0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00
```

The task-set generation step creates task sets for all of these utilization levels. The acceptance-ratio experiment also uses all of these utilization levels.

The dynamic simulation step uses only the three largest utilization levels:

```bash
0.90, 0.95, 1.00
```

For each pair `(n, U)`, the artifact generates 200 task sets. Periods are sampled from the range `[10, 200]`.

The boost speed is:

```bash
sB = 1.5
```

For the acceptance-ratio experiment, the evaluated boost-budget fractions are:

```bash
0.05, 0.10, 0.20, 0.30
```

These values are set as variables in the corresponding shell scripts. Evaluators who want to change the experiment size or parameters can edit the variables at the beginning of each script instead of modifying the Docker command manually.

## 9.1 Task-Set Generation Variables

The task-set generation script is:

```bash
run_part2_generate.sh
```

It uses the following variables:

```bash
OUT_DIR="tasksets"
IMAGE_NAME="python:3.11-slim"
N_VALUES="3 4 5 6 7 8"
M=200
UMIN=70
UMAX=100
USTEP=5
TMIN=10
TMAX=200
SEED=1
```

These correspond to the following `p21.py generate` arguments:

```bash
--n       number of tasks
--m       task sets per utilization level
--umin    minimum utilization percentage
--umax    maximum utilization percentage
--ustep   utilization step percentage
--tmin    minimum period
--tmax    maximum period
--seed    random seed
```

The `p21.py` defaults for `generate` are:

```bash
--umin 85
--umax 100
--ustep 5
--tmin 10
--tmax 200
--seed 1
```

However, this artifact script sets:

```bash
UMIN=70
M=200
```

to match the paper setup. The arguments `--out`, `--n`, and `--m` are required by the command.

To reduce the number of generated task sets, change:

```bash
M=200
```

For example:

```bash
M=50
```

To change the task-set sizes, edit:

```bash
N_VALUES="3 4 5 6 7 8"
```

For example, to generate only 3-task and 8-task cases:

```bash
N_VALUES="3 8"
```

## 9.2 Acceptance-Ratio Variables

The acceptance-ratio script is:

```bash
run_part2_acceptance.sh
```

It uses the following variables:

```bash
TASKSET_DIR="tasksets"
OUT_DIR="acceptance"
IMAGE_NAME="python:3.11-slim"
N_VALUES="3 4 5 6 7 8"
SB="1.5"
BOOST_UPS="0.05,0.10,0.20,0.30"
```

These correspond to the following `p21.py diff` arguments:

```bash
--infile      input task-set file
--sb          boost speed
--boost-ups   comma-separated boost-budget fractions
--out-png     output figure
```

The `p21.py` defaults for `diff` are:

```bash
--sb 1.5
--boost-ups 0.05,0.10,0.20,0.30
--out-png acceptance_ratio_diff.png
```

The argument `--infile` is required.

To change the boost speed, edit:

```bash
SB="1.5"
```

To change the evaluated boost budgets, edit:

```bash
BOOST_UPS="0.05,0.10,0.20,0.30"
```

For example:

```bash
BOOST_UPS="0.10,0.30"
```

To reduce execution time, edit:

```bash
N_VALUES="3 4 5 6 7 8"
```

For example:

```bash
N_VALUES="3 8"
```

This runs the acceptance-ratio experiment only for the 3-task and 8-task cases.

## 9.3 Dynamic-Simulation Variables

The dynamic simulation script is:

```bash
run_part2_dynamic.sh
```

It uses the following variables:

```bash
TASKSET_DIR="tasksets"
OUT_DIR="dynamic_results"
IMAGE_NAME="python:3.11-slim"
N_VALUES="3 4 5 6 7 8"
SB="1.5"
L_RUNS="10"
SEED="1"
FMIN="1.3"
FMAX="29.11"
```

These correspond to the following `p21.py run` arguments:

```bash
--infile    input task-set file
--sb        boost speed
--L         number of simulated hyperperiods per selected task set
--seed      random seed
--fmin      minimum execution-time scaling factor
--fmax      maximum execution-time scaling factor
```

The `p21.py` defaults for `run` are:

```bash
--sb 1.5
--L 10
--seed 1
--fmin 1.3
--fmax 29.11
```

The argument `--infile` is required.

To reduce simulation time, change:

```bash
L_RUNS="10"
```

For example:

```bash
L_RUNS="3"
```

To run fewer task-set sizes, edit:

```bash
N_VALUES="3 4 5 6 7 8"
```

For example:

```bash
N_VALUES="3 8"
```

The dynamic simulation always uses only the three largest utilization levels from the input task-set file:

```bash
0.90, 0.95, 1.00
```

## 10. Step 1: Generate Task Sets

Run:

```bash
bash run_part2_generate.sh
```

This script starts Docker once and generates all task-set files for task counts from 3 to 8. The generated files are stored in:

```bash
tasksets/
```

Expected files:

```bash
tasksets/
├── tasksets3.jsonl
├── tasksets4.jsonl
├── tasksets5.jsonl
├── tasksets6.jsonl
├── tasksets7.jsonl
└── tasksets8.jsonl
```

Check the generated files using:

```bash
ls tasksets/
```

To inspect one generated task set:

```bash
head -n 1 tasksets/tasksets3.jsonl
```

Each line is a JSON record containing:

- `id`: task-set identifier,
- `U_target`: target utilization,
- `tasks`: list of tasks,
- `T`: task period,
- `C`: task execution time.

## 11. Step 2: Generate Acceptance-Ratio Results

After generating task sets, run:

```bash
bash run_part2_acceptance.sh
```

This script runs the `diff` command of `p21.py` for each task-set size. The command compares RMS against Boosted-FP under different boost-budget bounds.

The script uses commands of the following form inside Docker:

```bash
python /src/p21.py diff \
  --infile /tasksets/tasksets3.jsonl \
  --sb 1.5 \
  --boost-ups 0.05,0.10,0.20,0.30 \
  --out-png /acceptance/acceptance3.png
```

The output figures are stored in:

```bash
acceptance/
```

Expected files:

```bash
acceptance/
├── acceptance3.png
├── acceptance4.png
├── acceptance5.png
├── acceptance6.png
├── acceptance7.png
└── acceptance8.png
```

These figures correspond to the acceptance-ratio results in the experimental evaluation.

The acceptance-ratio step uses all generated utilization levels:

```bash
0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00
```

## 12. Step 3: Run Dynamic Simulation and Extract Remaining Results

After the acceptance-ratio experiment, run:

```bash
bash run_part2_dynamic.sh
```

This script runs the `run` command of `p21.py` for each task-set size. It evaluates dynamic boost cancellation and produces the data used for the remaining experimental results.

The script uses commands of the following form inside Docker:

```bash
python /src/p21.py run \
  --infile /tasksets/tasksets3.jsonl \
  --sb 1.5 \
  --L 10 \
  --seed 1
```

The helper script also specifies output filenames so that each task-set size has its own figures and JSON result file.

The output files are stored in:

```bash
dynamic_results/
```

Expected files include:

```bash
dynamic_results/
├── dynamic_n3_boost_time.png
├── dynamic_n3_boost_utilization.png
├── dynamic_n3_net_energy.png
├── dynamic_n3_global_freq_improvement.png
├── dynamic_n3_data.json
├── dynamic_n4_boost_time.png
├── dynamic_n4_boost_utilization.png
├── dynamic_n4_net_energy.png
├── dynamic_n4_global_freq_improvement.png
├── dynamic_n4_data.json
...
└── dynamic_n8_data.json
```

Although the generated task-set files contain utilization levels from `0.70` to `1.00`, the dynamic simulation step processes only the three largest utilization levels:

```bash
0.90, 0.95, 1.00
```

The dynamic simulation outputs are used to extract the last two groups of experimental results.

### 12.1 Dynamic Boost-Cancellation Results

These include:

- boosted-time percentage,
- boost utilization,
- net normalized energy per slot.

### 12.2 Dynamic Energy-Efficiency Results

These include:

- energy improvement over the global frequency-scaling baseline.

The JSON files contain the numerical data, while the PNG files contain the generated plots.

## 13. Reducing Execution Time

The full simulation can take time because it evaluates multiple task-set sizes and many generated task sets. To reduce execution time during artifact review, the evaluator may run only a subset of task-set sizes.

For task-set generation, edit:

```bash
run_part2_generate.sh
```

and change:

```bash
N_VALUES="3 4 5 6 7 8"
```

For example:

```bash
N_VALUES="3 8"
```

For the acceptance-ratio step, edit:

```bash
run_part2_acceptance.sh
```

and change:

```bash
N_VALUES="3 4 5 6 7 8"
```

For example:

```bash
N_VALUES="3 8"
```

For the dynamic simulation step, edit:

```bash
run_part2_dynamic.sh
```

and change:

```bash
N_VALUES="3 4 5 6 7 8"
```

For example:

```bash
N_VALUES="3 8"
```

This reduces execution time while preserving the same workflow. A full reproduction should run all task sizes from 3 to 8.

## 14. Complete Commands for Part 2

```bash
sudo apt update
sudo apt install -y docker.io
bash run_part2_generate.sh
bash run_part2_acceptance.sh
bash run_part2_dynamic.sh
ls tasksets/
ls acceptance/
ls dynamic_results/
```

## 15. Expected Final Directory Structure

After completing Part 2, the following folders should exist:

```bash
tasksets/
acceptance/
dynamic_results/
```

The folder `tasksets/` contains generated task sets. The folder `acceptance/` contains acceptance-ratio figures. The folder `dynamic_results/` contains dynamic simulation figures and JSON data files.

---

# Summary of Artifact Workflow

The complete artifact workflow is:

```bash
# Part 1: hardware validation
bash exp2.sh
bash run_plot_docker.sh

# Part 2: simulation evaluation
bash run_part2_generate.sh
bash run_part2_acceptance.sh
bash run_part2_dynamic.sh
```

The hardware validation results are saved in:

```bash
shared/
```

The simulation results are saved in:

```bash
tasksets/
acceptance/
dynamic_results/
```