"""Lock 3: a botocore hook that stops any call that isn't read-only before it is sent."""

import boto3

ALLOWED_PREFIXES = ("Describe", "List", "Get")


class ReadOnlyViolation(Exception):
    """Raised before sending an AWS operation that could change something."""


def install(session: boto3.Session, extra: frozenset[str] = frozenset()) -> None:
    """Guard every client this session creates. `extra` names further allowed operations."""

    def check(model, **kwargs) -> None:
        name = model.name
        if not (name.startswith(ALLOWED_PREFIXES) or name in extra):
            raise ReadOnlyViolation(
                f"Janitor stopped {model.service_model.service_name}:{name}, "
                "which isn't read-only. Nothing was sent."
            )

    session.events.register("before-call", check)
