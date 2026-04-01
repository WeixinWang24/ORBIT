# ORBIT development setup

## Default environment

Use the Conda environment named `Orbit` for all ORBIT development.

```bash
source /Users/visen24/anaconda3/etc/profile.d/conda.sh
conda activate Orbit
```

## Create/update environment

```bash
cd /Volumes/2TB/MAS/openclaw-core/ORBIT
conda env update -f environment.yml --prune
```

## Install editable package

```bash
pip install -e .
```

## Persistence direction

ORBIT's primary persistence direction is PostgreSQL.

The current SQLite module is a temporary bootstrap store for early bring-up and should not be treated as the long-term default architecture.
