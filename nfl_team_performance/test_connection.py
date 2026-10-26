"""Read-only SELECT 1 test. Never creates or modifies tables."""
import sys

from .db import ConfigurationError, connect, verify_connection


def test_connection():
    connection = connect()
    try:
        details = verify_connection(connection)
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone() != (1,):
                raise RuntimeError("SELECT 1 returned an unexpected result")
        return details
    finally:
        connection.close()


def main():
    try:
        details = test_connection()
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else "unavailable"
        print(f"Connection failed: {type(exc).__name__}; MySQL code {code}", file=sys.stderr)
        # Print known categories only, never arbitrary server/driver messages.
        message = str(exc).lower()
        reasons = (
            "self-signed certificate in certificate chain",
            "self-signed certificate",
            "unable to get local issuer certificate",
            "certificate has expired",
            "certificate is not yet valid",
            "hostname mismatch",
            "access denied",
        )
        for reason in reasons:
            if reason in message:
                print(f"Diagnostic: {reason}", file=sys.stderr)
                break
        return 1
    print(f"SELECT 1 passed on {details['database']}; MySQL {details['mysql_version']}")
    print("No tables created or modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
