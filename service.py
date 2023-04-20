"""interface with prefect's python client api"""
import os
import requests

from prefect import flow
from prefect_airbyte import AirbyteConnection, AirbyteServer
from prefect_airbyte.flows import run_connection_sync
from prefect_sqlalchemy import DatabaseCredentials, SyncDriver
from prefect_gcp import GcpCredentials
from prefect_dbt.cli.configs import PostgresTargetConfigs
from prefect_dbt.cli.configs import BigQueryTargetConfigs
from prefect_dbt.cli.commands import DbtCoreOperation, ShellOperation
from prefect_dbt.cli import DbtCliProfile

from dotenv import load_dotenv

from helpers import cleaned_name_for_dbtblock
from exception import PrefectException

load_dotenv()


def prefect_delete(endpoint):
    """DELETE request to prefect server"""
    root = os.getenv("PREFECT_API_URL")
    res = requests.delete(f"{root}/{endpoint}", timeout=30)
    res.raise_for_status()


def _block_id(block):
    return str(block.dict()["_block_document_id"])


# ================================================================================================
async def get_airbyte_server_block_id(blockname) -> str | None:
    """look up an airbyte server block by name and return block_id"""
    try:
        block = await AirbyteServer.load(blockname)
        return _block_id(block)
    except ValueError:
        return None


async def create_airbyte_server_block(blockname) -> str:
    """Create airbyte server block in prefect"""

    airbyteservercblock = AirbyteServer(
        server_host=os.getenv("AIRBYTE_SERVER_HOST"),
        server_port=os.getenv("AIRBYTE_SERVER_PORT"),
        api_version=os.getenv("AIRBYTE_SERVER_APIVER"),
    )
    await airbyteservercblock.save(blockname)
    return _block_id(airbyteservercblock)


def update_airbyte_server_block(blockname):
    """We don't update server blocks"""
    raise PrefectException("not implemented")


def delete_airbyte_server_block(blockid):
    """Delete airbyte server block"""
    return prefect_delete(f"block_documents/{blockid}")


# ================================================================================================
async def get_airbyte_connection_block_id(blockname) -> str | None:
    """look up airbyte connection block by name and return block_id"""
    try:
        block = await AirbyteConnection.load(blockname)
        return _block_id(block)
    except ValueError:
        return None


async def create_airbyte_connection_block(
    conninfo,
) -> str:
    """Create airbyte connection block"""

    try:
        serverblock = await AirbyteServer.load(conninfo.serverBlockName)
    except ValueError as exc:
        raise PrefectException(
            f"could not find Airbyte Server block named {conninfo.serverBlockName}"
        ) from exc

    connection_block = AirbyteConnection(
        airbyte_server=serverblock,
        connection_id=conninfo.connectionId,
    )
    await connection_block.save(conninfo.connectionBlockName)

    return _block_id(connection_block)


def update_airbyte_connection_block(blockname):
    """We don't update connection blocks"""
    raise PrefectException("not implemented")


def delete_airbyte_connection_block(blockid):
    """Delete airbyte connection block in prefect"""
    return prefect_delete(f"block_documents/{blockid}")


# ================================================================================================
async def get_shell_block_id(blockname) -> str | None:
    """look up a shell operation block by name and return block_id"""
    try:
        block = await ShellOperation.load(blockname)
        return _block_id(block)
    except ValueError:
        return None


async def create_shell_block(shell):
    """Create a prefect shell block"""

    shell_operation_block = ShellOperation(
        commands=shell.commands, env=shell.env, working_dir=shell.workingDir
    )
    await shell_operation_block.save(shell.blockname)
    return _block_id(shell_operation_block)


def delete_shell_block(blockid):
    """Delete a prefect shell block"""
    return prefect_delete(f"block_documents/{blockid}")


# ================================================================================================
async def get_dbtcore_block_id(blockname) -> str | None:
    """look up a dbt core operation block by name and return block_id"""
    try:
        block = await DbtCoreOperation.load(blockname)
        return _block_id(block)
    except ValueError:
        return None


async def _create_dbt_cli_profile(profile, wtype: str, credentials: dict):
    """credentials are decrypted by now"""

    if wtype == "postgres":
        dbcredentials = DatabaseCredentials(
            driver=SyncDriver.POSTGRESQL_PSYCOPG2,
            username=credentials["username"],
            password=credentials["password"],
            database=credentials["database"],
            host=credentials["host"],
            port=credentials["port"],
        )
        target_configs = PostgresTargetConfigs(
            credentials=dbcredentials, schema=profile.target_configs_schema
        )

    elif wtype == "bigquery":
        dbcredentials = GcpCredentials(service_account_info=credentials)
        target_configs = BigQueryTargetConfigs(
            credentials=dbcredentials, schema=profile.target_configs_schema
        )
    else:
        raise PrefectException("unknown wtype: " + wtype)

    dbt_cli_profile = DbtCliProfile(
        name=profile.name, target=profile.target, target_configs=target_configs
    )
    await dbt_cli_profile.save(cleaned_name_for_dbtblock(profile.name), overwrite=True)
    return dbt_cli_profile


async def create_dbt_core_block(dbtcore, profile, wtype: str, credentials: dict):
    """Create a dbt core block in prefect"""

    dbt_cli_profile = await _create_dbt_cli_profile(profile, wtype, credentials)
    dbt_core_operation = DbtCoreOperation(
        commands=dbtcore.commands,
        env=dbtcore.env,
        working_dir=dbtcore.working_dir,
        profiles_dir=dbtcore.profiles_dir,
        project_dir=dbtcore.project_dir,
        dbt_cli_profile=dbt_cli_profile,
    )
    await dbt_core_operation.save(cleaned_name_for_dbtblock(dbtcore.block_name))

    return _block_id(dbt_core_operation)


def delete_dbt_core_block(block_id):
    """Delete a dbt core block in prefect"""
    return prefect_delete(f"block_documents/{block_id}")


# ================================================================================================
@flow
def run_airbyte_connection_prefect_flow(blockname):
    """Prefect flow to run airbyte connection"""
    airbyte_connection = AirbyteConnection.load(blockname)
    return run_connection_sync(airbyte_connection)


@flow
def run_dbtcore_prefect_flow(blockname):
    """Prefect flow to run dbt"""
    dbt_op = DbtCoreOperation.load(blockname)
    dbt_op.run()