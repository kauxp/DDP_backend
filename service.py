"""interface with prefect's python client api"""
import os
import requests


from prefect.deployments import Deployment
from prefect.server.schemas.schedules import CronSchedule
from prefect_airbyte import AirbyteConnection, AirbyteServer

from prefect_sqlalchemy import DatabaseCredentials, SyncDriver
from prefect_gcp import GcpCredentials
from prefect_dbt.cli.configs import PostgresTargetConfigs
from prefect_dbt.cli.configs import BigQueryTargetConfigs
from prefect_dbt.cli.commands import DbtCoreOperation, ShellOperation
from prefect_dbt.cli import DbtCliProfile

from dotenv import load_dotenv

from helpers import cleaned_name_for_dbtblock
from exception import PrefectException
from schemas import (
    AirbyteServerCreate,
    AirbyteConnectionCreate,
    PrefectShellSetup,
    DbtCoreCreate,
    DeploymentCreate,
    RunFlow,
)
from flows import (
    deployment_schedule_flow,
    run_airbyte_connection_flow,
    run_dbtcore_flow,
)

load_dotenv()

FLOW_RUN_FAILED = "FAILED"
FLOW_RUN_COMPLETED = "COMPLETED"
FLOW_RUN_SCHEDULED = "SCHEDULED"


def prefect_post(endpoint, payload):
    """POST request to prefect server"""
    root = os.getenv("PREFECT_API_URL")
    res = requests.post(f"{root}/{endpoint}", timeout=30, json=payload)
    res.raise_for_status()
    return res.json()


def prefect_get(endpoint):
    """GET request to prefect server"""
    root = os.getenv("PREFECT_API_URL")
    res = requests.get(f"{root}/{endpoint}", timeout=30)
    res.raise_for_status()
    return res.json()


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


async def create_airbyte_server_block(payload: AirbyteServerCreate) -> str:
    """Create airbyte server block in prefect"""

    airbyteservercblock = AirbyteServer(
        server_host=payload.serverHost,
        server_port=payload.serverPort,
        api_version=payload.apiVersion,
    )
    await airbyteservercblock.save(payload.blockName)
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


async def get_airbyte_connection_block(blockid):
    """look up and return block data for an airbyte connection"""
    result = prefect_get(f"block_documents/{blockid}")
    return result


async def create_airbyte_connection_block(
    conninfo: AirbyteConnectionCreate,
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


async def create_shell_block(shell: PrefectShellSetup):
    """Create a prefect shell block"""

    shell_operation_block = ShellOperation(
        commands=shell.commands, env=shell.env, working_dir=shell.workingDir
    )
    await shell_operation_block.save(shell.blockName)
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


async def _create_dbt_cli_profile(payload: DbtCoreCreate):
    """credentials are decrypted by now"""

    if payload.wtype == "postgres":
        dbcredentials = DatabaseCredentials(
            driver=SyncDriver.POSTGRESQL_PSYCOPG2,
            username=payload.credentials["username"],
            password=payload.credentials["password"],
            database=payload.credentials["database"],
            host=payload.credentials["host"],
            port=payload.credentials["port"],
        )
        target_configs = PostgresTargetConfigs(
            credentials=dbcredentials, schema=payload.profile.target_configs_schema
        )

    elif payload.wtype == "bigquery":
        dbcredentials = GcpCredentials(service_account_info=payload.credentials)
        target_configs = BigQueryTargetConfigs(
            credentials=dbcredentials, schema=payload.profile.target_configs_schema
        )
    else:
        raise PrefectException("unknown wtype: " + payload.wtype)

    dbt_cli_profile = DbtCliProfile(
        name=payload.profile.name,
        target=payload.profile.target,
        target_configs=target_configs,
    )
    await dbt_cli_profile.save(
        cleaned_name_for_dbtblock(payload.profile.name), overwrite=True
    )
    return dbt_cli_profile


async def create_dbt_core_block(payload: DbtCoreCreate):
    """Create a dbt core block in prefect"""

    dbt_cli_profile = await _create_dbt_cli_profile(payload)
    dbt_core_operation = DbtCoreOperation(
        commands=payload.commands,
        env=payload.env,
        working_dir=payload.working_dir,
        profiles_dir=payload.profiles_dir,
        project_dir=payload.project_dir,
        dbt_cli_profile=dbt_cli_profile,
    )
    await dbt_core_operation.save(
        cleaned_name_for_dbtblock(payload.blockName), overwrite=True
    )

    return _block_id(dbt_core_operation)


def delete_dbt_core_block(block_id):
    """Delete a dbt core block in prefect"""
    return prefect_delete(f"block_documents/{block_id}")


# ================================================================================================
def run_airbyte_connection_prefect_flow(payload: RunFlow):
    """Run an Airbyte Connection sync"""

    return run_airbyte_connection_flow(payload)


def run_dbtcore_prefect_flow(payload: RunFlow):
    """Run a dbt core flow"""

    return run_dbtcore_flow(payload)


async def post_deployment(payload: DeploymentCreate) -> None:
    """create a deployment from a flow and a schedule"""
    deployment = Deployment.build_from_flow(
        flow=deployment_schedule_flow.with_options(name=payload.flow_name),
        name=payload.deployment_name,
        work_queue_name="ddp",
        tags=[payload.org_slug],
    )
    deployment.parameters = {
        "airbyte_blocks": payload.connection_blocks,
        "dbt_blocks": payload.dbt_blocks,
    }
    deployment.schedule = CronSchedule(cron=payload.cron)
    await deployment.apply()


def get_flow_runs_by_deployment_id(deployment_id, limit):
    """Fetch flow runs of a deployment that are FAILED/COMPLETED,
    sorted by descending start time of each run"""
    query = {
        "sort": "START_TIME_DESC",
        "deployments": {"id": {"any_": [deployment_id]}},
        "flow_runs": {
            "operator": "and_",
            "state": {"type": {"any_": [FLOW_RUN_COMPLETED, FLOW_RUN_FAILED]}},
        },
    }

    if limit > 0:
        query["limit"] = limit

    flow_runs = []

    for flow_run in prefect_post("flow_runs/filter", query):
        flow_runs.append(
            {
                "tags": flow_run["tags"],
                "startTime": flow_run["start_time"],
                "status": flow_run["state"]["type"],
            }
        )

    return flow_runs


def get_deployments_by_org_slug(org_slug):
    """fetch all deployments by org"""
    res = prefect_post(
        "deployments/filter",
        {"deployments": {"tags": {"all_": [org_slug]}}},
    )

    deployments = []

    for deployment in res:
        deployments.append(
            {
                "name": deployment["name"],
                "id": deployment["id"],
                "tags": deployment["tags"],
                "cron": deployment["schedule"]["cron"],
            }
        )

    return deployments