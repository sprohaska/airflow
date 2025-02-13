#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""This module contains SFTP operator."""
from __future__ import annotations

import os
import warnings
from pathlib import Path
from typing import Any, Sequence

from airflow.exceptions import AirflowException
from airflow.models import BaseOperator
from airflow.providers.sftp.hooks.sftp import SFTPHook
from airflow.providers.ssh.hooks.ssh import SSHHook


class SFTPOperation:
    """Operation that can be used with SFTP"""

    PUT = 'put'
    GET = 'get'


class SFTPOperator(BaseOperator):
    """
    SFTPOperator for transferring files from remote host to local or vice a versa.
    This operator uses sftp_hook to open sftp transport channel that serve as basis
    for file transfer.

    :param ssh_conn_id: :ref:`ssh connection id<howto/connection:ssh>`
        from airflow Connections. `ssh_conn_id` will be ignored if `ssh_hook`
        or `sftp_hook` is provided.
    :param sftp_hook: predefined SFTPHook to use
        Either `sftp_hook` or `ssh_conn_id` needs to be provided.
    :param ssh_hook: Deprecated - predefined SSHHook to use for remote execution
        Use `sftp_hook` instead.
    :param remote_host: remote host to connect (templated)
        Nullable. If provided, it will replace the `remote_host` which was
        defined in `sftp_hook`/`ssh_hook` or predefined in the connection of `ssh_conn_id`.
    :param local_filepath: local file path to get or put. (templated)
    :param remote_filepath: remote file path to get or put. (templated)
    :param operation: specify operation 'get' or 'put', defaults to put
    :param confirm: specify if the SFTP operation should be confirmed, defaults to True
    :param create_intermediate_dirs: create missing intermediate directories when
        copying from remote to local and vice-versa. Default is False.

        Example: The following task would copy ``file.txt`` to the remote host
        at ``/tmp/tmp1/tmp2/`` while creating ``tmp``,``tmp1`` and ``tmp2`` if they
        don't exist. If the parameter is not passed it would error as the directory
        does not exist. ::

            put_file = SFTPOperator(
                task_id="test_sftp",
                ssh_conn_id="ssh_default",
                local_filepath="/tmp/file.txt",
                remote_filepath="/tmp/tmp1/tmp2/file.txt",
                operation="put",
                create_intermediate_dirs=True,
                dag=dag
            )

    """

    template_fields: Sequence[str] = ('local_filepath', 'remote_filepath', 'remote_host')

    def __init__(
        self,
        *,
        ssh_hook: SSHHook | None = None,
        sftp_hook: SFTPHook | None = None,
        ssh_conn_id: str | None = None,
        remote_host: str | None = None,
        local_filepath: str,
        remote_filepath: str,
        operation: str = SFTPOperation.PUT,
        confirm: bool = True,
        create_intermediate_dirs: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.ssh_hook = ssh_hook
        self.sftp_hook = sftp_hook
        self.ssh_conn_id = ssh_conn_id
        self.remote_host = remote_host
        self.local_filepath = local_filepath
        self.remote_filepath = remote_filepath
        self.operation = operation
        self.confirm = confirm
        self.create_intermediate_dirs = create_intermediate_dirs

        if not (self.operation.lower() == SFTPOperation.GET or self.operation.lower() == SFTPOperation.PUT):
            raise TypeError(
                f"Unsupported operation value {self.operation}, "
                f"expected {SFTPOperation.GET} or {SFTPOperation.PUT}."
            )

        # TODO: remove support for ssh_hook in next major provider version in hook and operator
        if self.ssh_hook is not None and self.sftp_hook is not None:
            raise AirflowException(
                'Both `ssh_hook` and `sftp_hook` are defined. Please use only one of them.'
            )

        if self.ssh_hook is not None:
            if not isinstance(self.ssh_hook, SSHHook):
                self.log.info('ssh_hook is invalid. Trying ssh_conn_id to create SFTPHook.')
                self.sftp_hook = SFTPHook(ssh_conn_id=self.ssh_conn_id)
            if self.sftp_hook is None:
                warnings.warn(
                    'Parameter `ssh_hook` is deprecated'
                    'Please use `sftp_hook` instead.'
                    'The old parameter `ssh_hook` will be removed in a future version.',
                    DeprecationWarning,
                    stacklevel=2,
                )
                self.sftp_hook = SFTPHook(ssh_hook=self.ssh_hook)

    def execute(self, context: Any) -> str | None:
        file_msg = None
        try:
            if self.ssh_conn_id:
                if self.sftp_hook and isinstance(self.sftp_hook, SFTPHook):
                    self.log.info("ssh_conn_id is ignored when sftp_hook/ssh_hook is provided.")
                else:
                    self.log.info(
                        'sftp_hook/ssh_hook not provided or invalid. Trying ssh_conn_id to create SFTPHook.'
                    )
                    self.sftp_hook = SFTPHook(ssh_conn_id=self.ssh_conn_id)

            if not self.sftp_hook:
                raise AirflowException("Cannot operate without sftp_hook or ssh_conn_id.")

            if self.remote_host is not None:
                self.log.info(
                    "remote_host is provided explicitly. "
                    "It will replace the remote_host which was defined "
                    "in sftp_hook or predefined in connection of ssh_conn_id."
                )
                self.sftp_hook.remote_host = self.remote_host

            if self.operation.lower() == SFTPOperation.GET:
                local_folder = os.path.dirname(self.local_filepath)
                if self.create_intermediate_dirs:
                    Path(local_folder).mkdir(parents=True, exist_ok=True)
                file_msg = f"from {self.remote_filepath} to {self.local_filepath}"
                self.log.info("Starting to transfer %s", file_msg)
                self.sftp_hook.retrieve_file(self.remote_filepath, self.local_filepath)
            else:
                remote_folder = os.path.dirname(self.remote_filepath)
                if self.create_intermediate_dirs:
                    self.sftp_hook.create_directory(remote_folder)
                file_msg = f"from {self.local_filepath} to {self.remote_filepath}"
                self.log.info("Starting to transfer file %s", file_msg)
                self.sftp_hook.store_file(self.remote_filepath, self.local_filepath, confirm=self.confirm)

        except Exception as e:
            raise AirflowException(f"Error while transferring {file_msg}, error: {str(e)}")

        return self.local_filepath
