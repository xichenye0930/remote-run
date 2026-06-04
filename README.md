# remote-run

`remote-run` provides `rrun`, a lightweight CLI for local development
when the GPU machine is remote. It syncs the current project to a configured
remote directory with `rsync`, submits the command as a detached SSH job, and
lets you inspect status and logs later.

## Install

From a cloned checkout:

```bash
pip install -e .
```

or install it as an isolated CLI tool:

```bash
pipx install .
```

Install directly from GitHub:

```bash
pip install "git+https://github.com/xichenye0930/remote-run.git"
```

or with `pipx`:

```bash
pipx install "git+https://github.com/xichenye0930/remote-run.git"
```

Verify the install:

```bash
rrun --help
```

## Configure

Create a project-local config:

```bash
rrun init
```

Edit `.rrun.toml`:

```toml
target = "user@gpu-server"
remote_workdir = "/home/user/experiments/my-project"

# port = 22
# prelude = "source ~/miniconda3/etc/profile.d/conda.sh && conda activate train"

# Additional rsync exclude patterns beyond built-in defaults and .gitignore.
exclude = [
  "data/",
  "outputs/",
]
```

During sync, `rrun` automatically uses the project root `.gitignore` when it
exists. The `exclude` list is only for extra patterns that should not be synced
to the remote workdir.

## Use

Sync only:

```bash
rrun sync
```

Sync and submit a background remote job:

```bash
rrun -- python train.py --epochs 10
```

The command prints a job id and exits locally. The remote process keeps running
under `<remote_workdir>/.rrun/jobs/<job_id>/`.

Inspect it later:

```bash
rrun status <job_id>
rrun logs <job_id>
rrun logs <job_id> -f
```

Cancel a running remote job:

```bash
rrun cancel <job_id>
```

Cancel targets the remote process tree, so multi-process launchers such as
`accelerate` should have their worker processes stopped as well. Logs and job
metadata remain under `<remote_workdir>/.rrun/jobs/<job_id>/`.

If the job does not stop gracefully, force it:

```bash
rrun cancel <job_id> --force
```

## Requirements

The local and remote machines should both have `ssh`, `bash`, and `rsync`
available. The first version does not require a remote daemon, tmux, a database,
or a scheduler.
