"""Job outcomes as exceptions, mapped to the exit codes in docs/SLOWBOARD.md §8.6."""

EXIT_OK, EXIT_UNCHANGED, EXIT_TRANSIENT, EXIT_NEEDS_CONFIG, EXIT_CONTRACT = 0, 3, 4, 5, 64


class JobExit(Exception):
    code = 1


class Unchanged(JobExit):
    """Upstream data is the same as last run: keep the previous feeds, extend valid_until."""
    code = EXIT_UNCHANGED


class Transient(JobExit):
    """A fetch failed or timed out: the hub backs off (or waits for the network)."""
    code = EXIT_TRANSIENT


class NeedsConfig(JobExit):
    """A secret, setting or sign-in is missing or rejected: no retry until something changes."""
    code = EXIT_NEEDS_CONFIG


class ContractError(JobExit):
    """The app broke the contract (bad output, bad environment, network use in fixture mode)."""
    code = EXIT_CONTRACT
