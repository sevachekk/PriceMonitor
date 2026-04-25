from typing import Annotated
from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from settings.config import get_settings


settings = get_settings()

engine = create_async_engine(
    f"postgresql+asyncpg://{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}",
    echo=settings.DB_ECHO,
    pool_pre_ping=True,
    pool_recycle=300,
)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

class Base(DeclarativeBase):
    pass


FOREIGN_KEYS_TO_ENSURE = (
    {
        "table_name": "competitor_prices",
        "column_name": "product_id",
        "referenced_table": "products_catalogproduct",
        "referenced_column": "id",
        "on_delete": "CASCADE",
    },
    {
        "table_name": "competitor_prices",
        "column_name": "competitor_id",
        "referenced_table": "competitors",
        "referenced_column": "id",
        "on_delete": "CASCADE",
    },
    {
        "table_name": "alerts",
        "column_name": "product_id",
        "referenced_table": "products_catalogproduct",
        "referenced_column": "id",
        "on_delete": "CASCADE",
    },
    {
        "table_name": "alerts",
        "column_name": "competitor_id",
        "referenced_table": "competitors",
        "referenced_column": "id",
        "on_delete": "CASCADE",
    },
    {
        "table_name": "notifications",
        "column_name": "alert_id",
        "referenced_table": "alerts",
        "referenced_column": "id",
        "on_delete": "SET NULL",
    },
    {
        "table_name": "notifications",
        "column_name": "product_id",
        "referenced_table": "products_catalogproduct",
        "referenced_column": "id",
        "on_delete": "SET NULL",
    },
    {
        "table_name": "notifications",
        "column_name": "competitor_id",
        "referenced_table": "competitors",
        "referenced_column": "id",
        "on_delete": "SET NULL",
    },
)

ON_DELETE_TO_CODE = {
    "CASCADE": "c",
    "SET NULL": "n",
}


def _quote_ident(identifier: str) -> str:
    return identifier.replace('"', '""')


async def _ensure_foreign_key(
    session: AsyncSession,
    *,
    table_name: str,
    column_name: str,
    referenced_table: str,
    referenced_column: str,
    on_delete: str,
    schema_name: str = "public",
) -> None:
    constraint_name = f"{table_name}_{column_name}_fkey"
    expected_delete_code = ON_DELETE_TO_CODE[on_delete]

    constraint_query = text(
        """
        SELECT
            c.conname,
            c.confdeltype,
            ref_ns.nspname AS referenced_schema,
            ref_cls.relname AS referenced_table,
            ref_att.attname AS referenced_column
        FROM pg_constraint c
        JOIN pg_class src_cls ON src_cls.oid = c.conrelid
        JOIN pg_namespace src_ns ON src_ns.oid = src_cls.relnamespace
        JOIN unnest(c.conkey) WITH ORDINALITY AS src_key(attnum, ord) ON TRUE
        JOIN pg_attribute src_att
            ON src_att.attrelid = src_cls.oid
           AND src_att.attnum = src_key.attnum
        JOIN pg_class ref_cls ON ref_cls.oid = c.confrelid
        JOIN pg_namespace ref_ns ON ref_ns.oid = ref_cls.relnamespace
        JOIN unnest(c.confkey) WITH ORDINALITY AS ref_key(attnum, ord)
            ON ref_key.ord = src_key.ord
        JOIN pg_attribute ref_att
            ON ref_att.attrelid = ref_cls.oid
           AND ref_att.attnum = ref_key.attnum
        WHERE c.contype = 'f'
          AND src_ns.nspname = :schema_name
          AND src_cls.relname = :table_name
          AND src_att.attname = :column_name
        """
    )
    result = await session.execute(
        constraint_query,
        {
            "schema_name": schema_name,
            "table_name": table_name,
            "column_name": column_name,
        },
    )
    existing_constraints = result.mappings().all()

    if len(existing_constraints) == 1:
        existing_constraint = existing_constraints[0]
        if (
            existing_constraint["referenced_schema"] == schema_name
            and existing_constraint["referenced_table"] == referenced_table
            and existing_constraint["referenced_column"] == referenced_column
            and existing_constraint["confdeltype"] == expected_delete_code
        ):
            return

    quoted_schema = _quote_ident(schema_name)
    quoted_table = _quote_ident(table_name)
    quoted_column = _quote_ident(column_name)
    quoted_constraint = _quote_ident(constraint_name)
    quoted_referenced_table = _quote_ident(referenced_table)
    quoted_referenced_column = _quote_ident(referenced_column)

    for existing_constraint in existing_constraints:
        constraint_to_drop = _quote_ident(existing_constraint["conname"])
        await session.execute(
            text(
                f'ALTER TABLE "{quoted_schema}"."{quoted_table}" '
                f'DROP CONSTRAINT "{constraint_to_drop}"'
            )
        )

    await session.execute(
        text(
            f'ALTER TABLE "{quoted_schema}"."{quoted_table}" '
            f'ADD CONSTRAINT "{quoted_constraint}" '
            f'FOREIGN KEY ("{quoted_column}") '
            f'REFERENCES "{quoted_schema}"."{quoted_referenced_table}" ("{quoted_referenced_column}") '
            f"ON DELETE {on_delete}"
        )
    )


async def _ensure_foreign_keys(session: AsyncSession) -> None:
    for foreign_key in FOREIGN_KEYS_TO_ENSURE:
        await _ensure_foreign_key(session, **foreign_key)

async def get_async_session():
    async with async_session() as session:
        yield session

CurrSession = Annotated[AsyncSession, Depends(get_async_session)]

async def init_db():
    async with engine.begin() as conn:
        metadata = Base.metadata

        # Отразим только необходимую таблицу (быстрее и безопаснее)
        def _reflect(sync_conn):
            metadata.reflect(sync_conn, only=['products_catalogproduct'])

        await conn.run_sync(_reflect)

        # Теперь metadata содержит products_catalogproduct, можно создавать остальные таблицы
        await conn.run_sync(Base.metadata.create_all)
    
    async with async_session() as session:
        from services.admin import ensure_platform_settings, ensure_source_policies
        from services.admin_auth import ensure_bootstrap_super_admin

        await _ensure_foreign_keys(session)
        await session.commit()
        await ensure_bootstrap_super_admin(session)
        await ensure_platform_settings(session)
        await ensure_source_policies(session)
        
