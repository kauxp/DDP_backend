"""
functions to work with pipelies/dataflows
do not raise http errors here
"""

from ddpui.models.tasks import OrgTask, DataflowOrgTask, TaskLock, TaskLockStatus
from ddpui.models.org import Org, OrgPrefectBlockv1, OrgDataFlowv1
from ddpui.utils.custom_logger import CustomLogger
from ddpui.ddpprefect.schema import (
    PrefectDbtTaskSetup,
    PrefectShellTaskSetup,
    PrefectAirbyteSyncTaskSetup,
)
from ddpui.ddpprefect import (
    AIRBYTECONNECTION,
    DBTCORE,
    SECRET,
    SHELLOPERATION,
    prefect_service,
)
from ddpui.utils.constants import (
    AIRBYTE_SYNC_TIMEOUT,
    TASK_GITPULL,
    TASK_AIRBYTESYNC,
)
from ddpui.ddpdbt.schema import DbtProjectParams

logger = CustomLogger("ddpui")

####################### big config dictionaries ##################################


def setup_airbyte_sync_task_config(
    org_task: OrgTask, server_block: OrgPrefectBlockv1, seq: int = 1
):
    """constructs the prefect payload for an airbyte sync"""
    return PrefectAirbyteSyncTaskSetup(
        seq=seq,
        slug=org_task.task.slug,
        type=AIRBYTECONNECTION,
        airbyte_server_block=server_block.block_name,
        connection_id=org_task.connection_id,
        timeout=AIRBYTE_SYNC_TIMEOUT,
        orgtask_uuid=str(org_task.uuid),
    )


def setup_dbt_core_task_config(
    org_task: OrgTask,
    cli_profile_block: OrgPrefectBlockv1,
    dbt_project_params: DbtProjectParams,
    seq: int = 1,
):
    """constructs the prefect payload for a dbt job"""
    return PrefectDbtTaskSetup(
        seq=seq,
        slug=org_task.task.slug,
        commands=[
            f"{dbt_project_params.dbt_binary} {org_task.get_task_parameters()} --target {dbt_project_params.target}"
        ],
        type=DBTCORE,
        env={},
        working_dir=dbt_project_params.project_dir,
        profiles_dir=f"{dbt_project_params.project_dir}/profiles/",
        project_dir=dbt_project_params.project_dir,
        cli_profile_block=cli_profile_block.block_name,
        cli_args=[],
        orgtask_uuid=str(org_task.uuid),
    )


def setup_git_pull_shell_task_config(
    org_task: OrgTask,
    project_dir: str,
    gitpull_secret_block: OrgPrefectBlockv1,
    seq: int = 1,
):
    """constructs the prefect payload for a git pull"""
    shell_env = {"secret-git-pull-url-block": ""}

    if gitpull_secret_block is not None:
        shell_env["secret-git-pull-url-block"] = gitpull_secret_block.block_name

    return PrefectShellTaskSetup(
        commands=[f"git {org_task.get_task_parameters()}"],
        working_dir=project_dir,
        env=shell_env,
        slug=org_task.task.slug,
        type=SHELLOPERATION,
        seq=seq,
        orgtask_uuid=str(org_task.uuid),
    )


#################################################################################


# def pipeline_sync_tasks(
#     org: Org,
#     connections: list[PrefectFlowAirbyteConnection2],
#     server_block: OrgPrefectBlockv1,
# ):
#     """Returns a list of org tasks with their configs"""
#     task_configs = []
#     org_tasks = []  # org tasks found related to the connections
#     seq = 0

#     connections.sort(key=lambda conn: conn.seq)
#     for connection in connections:
#         logger.info(connection)
#         org_task = OrgTask.objects.filter(org=org, connection_id=connection.id).first()
#         if org_task is None:
#             logger.info(
#                 f"connection id {connection.id} not found in org tasks; ignoring this airbyte sync"
#             )
#             continue
#         # map this org task to dataflow
#         org_tasks.append(org_task)

#         logger.info(
#             f"connection id {connection.id} found in org tasks; pushing to pipeline"
#         )
#         seq += 1
#         task_configs.append(
#             setup_airbyte_sync_task_config(org_task, server_block, seq).to_json()
#         )

#     return (org_tasks, task_configs), None


# def pipeline_dbt_git_tasks(
#     org: Org,
#     cli_block: OrgPrefectBlockv1,
#     dbt_project_params: DbtProjectParams,
#     start_seq: int = 0,
# ):
#     """Returns a list of org tasks with their config"""
#     task_configs = []
#     org_tasks = []  # org tasks found related to the dbt, git

#     # add only the default org task
#     for org_task in OrgTask.objects.filter(
#         org=org, task__type__in=["dbt", "git"], task__is_system=True
#     ).all():
#         logger.info(f"found transform task {org_task.task.slug}; pushing to pipeline")
#         # map this org task to dataflow
#         org_tasks.append(org_task)

#         task_config = setup_dbt_core_task_config(
#             org_task, cli_block, dbt_project_params
#         ).to_json()

#         # update task_config its a git pull task
#         if org_task.task.slug == TASK_GITPULL:
#             gitpull_secret_block = OrgPrefectBlockv1.objects.filter(
#                 org=org, block_type=SECRET, block_name__contains="git-pull"
#             ).first()

#             task_config = setup_git_pull_shell_task_config(
#                 org_task, dbt_project_params.project_dir, gitpull_secret_block
#             ).to_json()

#         # update sequence
#         task_config["seq"] = start_seq + TRANSFORM_TASKS_SEQ[org_task.task.slug]

#         task_configs.append(task_config)

#     return (org_tasks, task_configs), None


def pipeline_with_orgtasks(
    org: Org,
    org_tasks: list[OrgTask],
    server_block: OrgPrefectBlockv1 = None,
    cli_block: OrgPrefectBlockv1 = None,
    dbt_project_params: DbtProjectParams = None,
    start_seq: int = 0,
):
    """
    Returns a list of task configs for a pipeline;
    This assumes the list of orgtasks is in the correct sequence
    """
    task_configs = []

    for org_task in org_tasks:
        task_config = None
        if org_task.task.slug == TASK_AIRBYTESYNC:
            task_config = setup_airbyte_sync_task_config(
                org_task, server_block
            ).to_json()
        elif org_task.task.slug == TASK_GITPULL:
            gitpull_secret_block = OrgPrefectBlockv1.objects.filter(
                org=org, block_type=SECRET, block_name__contains="git-pull"
            ).first()

            if not gitpull_secret_block:
                logger.info(
                    f"secret block for {org_task.task.slug} not found in org prefect blocks;"
                )
            task_config = setup_git_pull_shell_task_config(
                org_task, dbt_project_params.project_dir, gitpull_secret_block
            ).to_json()
        else:
            task_config = setup_dbt_core_task_config(
                org_task, cli_block, dbt_project_params
            ).to_json()

        if task_config:
            task_configs.append(task_config)
            task_config["seq"] = start_seq
            start_seq += 1

    return task_configs, None


def fetch_pipeline_lock(dataflow: OrgDataFlowv1):
    """
    fetch the lock status of an dataflow/deployment
    """
    org_task_ids = DataflowOrgTask.objects.filter(dataflow=dataflow).values_list(
        "orgtask_id", flat=True
    )
    lock = TaskLock.objects.filter(orgtask_id__in=org_task_ids).first()
    if lock:
        lock_status = TaskLockStatus.QUEUED
        if lock.flow_run_id:
            flow_run = prefect_service.get_flow_run(lock.flow_run_id)
            if flow_run and flow_run["state_type"] in ["SCHEDULED", "PENDING"]:
                lock_status = TaskLockStatus.QUEUED
            elif flow_run and flow_run["state_type"] == "RUNNING":
                lock_status = TaskLockStatus.RUNNING
            else:
                lock_status = TaskLockStatus.COMPLETED

        return {
            "lockedBy": lock.locked_by.user.email,
            "lockedAt": lock.locked_at,
            "flowRunId": lock.flow_run_id,
            "status": (
                lock_status
                if lock.locking_dataflow == dataflow
                else TaskLockStatus.LOCKED
            ),
        }

    return None
