"""Environment-only MySQL credentials; restricted to the approved database."""
from dataclasses import dataclass, field
import os
import ssl

APPROVED_DATABASE = "KmayII$NFL_Team_Performance"


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    port: int
    user: str
    database: str
    password: str = field(repr=False)
    ca_file: str | None = None

    def validate(self):
        if self.database != APPROVED_DATABASE:
            raise ConfigurationError(f"Only {APPROVED_DATABASE} is allowed.")
        if not self.password:
            raise ConfigurationError("Set NFL_DB_PASSWORD securely in the process environment.")
        if not self.host or not self.user or not 1 <= self.port <= 65535:
            raise ConfigurationError("Invalid database host, username, or port.")

    @classmethod
    def from_environment(cls):
        try:
            port = int(os.environ.get("NFL_DB_PORT", "3306"))
        except ValueError:
            raise ConfigurationError("NFL_DB_PORT must be an integer.") from None
        settings = cls(
            host=os.environ.get("NFL_DB_HOST", "KmayII.mysql.pythonanywhere-services.com"),
            port=port,
            user=os.environ.get("NFL_DB_USER", "KmayII"),
            database=os.environ.get("NFL_DB_NAME", APPROVED_DATABASE),
            password=os.environ.get("NFL_DB_PASSWORD", ""),
            ca_file=os.environ.get("NFL_DB_SSL_CA") or None,
        )
        settings.validate()
        return settings


def connect(settings=None):
    settings = settings or DatabaseSettings.from_environment()
    settings.validate()
    import pymysql
    return pymysql.connect(
        host=settings.host, port=settings.port, user=settings.user,
        password=settings.password, database=settings.database,
        charset="utf8mb4", autocommit=False,
        connect_timeout=10, read_timeout=30, write_timeout=30,
        ssl=create_tls_context(settings.ca_file),
    )


def create_tls_context(ca_file=None):
    """Use system trust or an operator-supplied, authenticated CA bundle."""
    context = ssl.create_default_context(cafile=ca_file)
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    return context


def verify_connection(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT DATABASE(), VERSION()")
        database, version = cursor.fetchone()
    if database != APPROVED_DATABASE:
        raise ConfigurationError("Connected database is not the approved study database.")
    return {"database": database, "mysql_version": version}
