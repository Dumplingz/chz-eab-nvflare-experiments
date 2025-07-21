# NVFlare Experiments

This repository contains the experimental results in the paper "Running Functions on Pooled Data without Leakage: Comparing Solutions Over Scope, Trust, and Performance" for NVFlare on FashionMNIST and CIFAR datasets, along with the scripts used to run the experiments.

## Setup
This repository was tested using Python 3.11 (switched to this version using pyenv) and NVFlare 2.5.2. Install the required packages using:

```bash
pip install -r requirements.txt
```

The experiments were run in nvflare's POC mode. To prepare the directories for the experiments, run:

```bash
nvflare poc prepare -n [number of agents]
```

This will create the necessary directories for each agent. Be careful about running this command multiple times, as it will overwrite existing directories. A result of this is that it will overwrite the port numbers, which will causes issues with shutting down the agents. Make sure that the poc is fully shut down before running this command again.

To start the poc, run:

```bash
nvflare poc start
```

Then, in a separate terminal while the poc is running, the experiments may be run using:

```bash
python run_experiments.py [number of trials] [model: cifar or mnist] [dataset size]
```

To quit the poc, run:

```bash
nvflare poc stop
```

The results will appear in the `data` directory.