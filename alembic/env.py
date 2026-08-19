from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from app.configs import DATABASE_URL
from app.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# LangGraph creates and migrates these itself via PostgresSaver.setup(). Without the
# filter, autogenerate emits a drop for every one of them.
LANGGRAPH_TABLE_PREFIX = "checkpoint"

# Expression and DESC indexes render correctly but compare poorly, so autogenerate
# proposes dropping and recreating them on every run. They are owned by the baseline.
HAND_MANAGED_INDEXES = {
    "users_email_lower_idx",
    "plan_requests_user_created_idx",
    "agent_invocations_agent_started_idx",
}


def include_object(object_, name, type_, reflected, compare_to):
    if type_ == "table":
        return not name.startswith(LANGGRAPH_TABLE_PREFIX)

    if type_ == "index":
        if name in HAND_MANAGED_INDEXES:
            return False
        table = getattr(object_, "table", None)
        if table is not None and table.name.startswith(LANGGRAPH_TABLE_PREFIX):
            return False

    return True


def run_migrations_offline() -> None:
    context.configure(
        url=str(make_url(DATABASE_URL).set(drivername="postgresql+psycopg")),
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")

    if connection is not None:
        # Supplied by app.db.migrate, which already holds the advisory lock.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = create_engine(
        make_url(DATABASE_URL).set(drivername="postgresql+psycopg"),
        poolclass=NullPool,
        connect_args={"prepare_threshold": None},
    )

    with engine.connect() as conn:
        context.configure(
            connection=conn,
            target_metadata=target_metadata,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
