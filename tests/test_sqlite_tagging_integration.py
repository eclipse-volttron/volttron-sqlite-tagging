# -*- coding: utf-8 -*- {{{
# ===----------------------------------------------------------------------===
#
#                 Installable Component of Eclipse VOLTTRON
#
# ===----------------------------------------------------------------------===
#
# Copyright 2022 Battelle Memorial Institute
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#
# ===----------------------------------------------------------------------===
# }}}

import gevent
import pytest
from tagging.testing.integration_test_interface import TaggingTestInterface
import sqlite3
from pathlib import Path

db_connection = None


class TestSQLiteIntegration(TaggingTestInterface):

    @pytest.fixture(scope="module")
    def tagging_agent(self, volttron_instance):
        config = {
            "connection": {
                "type": "sqlite",
                "params": {
                    "database": volttron_instance.volttron_home + '/test_tagging.sqlite'
                }
            }
        }
        self.setup_sqlite(config)
        agent_path = Path(__file__).parents[1]
        tagging_agent_id = volttron_instance.install_agent(vip_identity='platform.tagging', agent_dir=agent_path,
                                                           config_file=config)
        volttron_instance.start_agent(tagging_agent_id)
        gevent.sleep(1)
        yield "platform.tagging"

        if volttron_instance.is_running() and volttron_instance.is_agent_running(tagging_agent_id):
            volttron_instance.stop_agent(tagging_agent_id)
            volttron_instance.remove_agent(tagging_agent_id)
            gevent.sleep(1)

    def setup_sqlite(self, config):
        global db_connection
        print("setup sqlite")
        connection_params = config['connection']['params']
        database_path = connection_params['database']
        print("connecting to sqlite path " + database_path)
        db_connection = sqlite3.connect(database_path)
        print("successfully connected to sqlite")

    def cleanup(self, truncate_tables, drop_tables=False):
        global db_connection
        cursor = db_connection.cursor()
        if truncate_tables is None:
            truncate_tables = self.select_all_sqlite_tables()

        if drop_tables:
            for table in truncate_tables:
                if table:
                    cursor.execute("DROP TABLE IF EXISTS " + table)
        else:
            for table in truncate_tables:
                cursor.execute("DELETE FROM " + table)
        db_connection.commit()
        cursor.close()

    def select_all_sqlite_tables(self):
        global db_connection
        cursor = db_connection.cursor()
        tables = []
        try:
            cursor.execute("SELECT name FROM sqlite_master WHERE type ='table' AND name NOT LIKE 'sqlite_%';")
            rows = cursor.fetchall()
            print(f"table names {rows}")
            tables = [columns[0] for columns in rows]
        except Exception as e:
            print("Error getting list of {}".format(e))
        finally:
            if cursor:
                cursor.close()
        return tables
