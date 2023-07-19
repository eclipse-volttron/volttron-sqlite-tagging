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
import contextlib
import csv
import errno
import logging
import os
import re
import sqlite3
import sys
from collections import OrderedDict

from gevent.local import local

from tagging.base.base_tagging import BaseTaggingAgent
from volttron import utils
from volttron.client.messaging.health import STATUS_BAD, Status
from volttron.utils import ClientContext

__version__ = "0.1.0"

utils.setup_logging()
_log = logging.getLogger(__name__)

TAGGING_AGENT_SETUP_FAILED = 'TAGGING AGENT SETUP FAILED'


# Register a better datetime parser in sqlite3.
utils.fix_sqlite3_datetime()


def tagging_agent(config_path, **kwargs):
    """
    This method is called by the :py:func:`service.tagging.main` to
    parse the passed config file or configuration dictionary object, validate
    the configuration entries, and create an instance of SQLTaggingService

    :param config_path: could be a path to a configuration file or can be a
                        dictionary object
    :param kwargs: additional keyword arguments if any
    :return: an instance of :py:class:`service.tagging.SQLTaggingService`
    """
    _log.debug("kwargs before init: {}".format(kwargs))
    if isinstance(config_path, dict):
        config_dict = config_path
    else:
        config_dict = utils.load_config(config_path)

    _log.debug("config_dict before init: {}".format(config_dict))

    if not config_dict.get('connection') or \
            not config_dict.get('connection').get('params') or \
            not config_dict.get('connection').get('params').get('database'):
        raise ValueError("Missing database connection parameters. Agent "
                         "configuration should contain database connection "
                         "parameters with the details about type of database"
                         "and name of database. Please refer to sample "
                         "configuration file in Agent's source directory.")

    utils.update_kwargs_with_config(kwargs, config_dict)
    return SQLiteTaggingAgent(**kwargs)


class SQLiteTaggingAgent(BaseTaggingAgent):
    """This is a tagging service agent that writes data to a SQLite database.
    """
    def __init__(self, connection, table_prefix=None, **kwargs):
        """Initialise the tagging service.

        :param connection: dictionary object containing the database
                           connection details
        :param table_prefix: optional prefix to be used for all tag tables
        :param kwargs: additional keyword arguments. (optional identity and
                       topic_replace_list used by parent classes)
        """

        super(SQLiteTaggingAgent, self).__init__(**kwargs)
        self.connection = connection
        self.tags_table = "tags"
        self.tag_refs_table = "tag_refs"
        self.categories_table = "categories"
        self.topic_tags_table = "topic_tags"
        self.category_tags_table = "category_tags"
        if table_prefix:
            self.tags_table = table_prefix + "_" + self.tags_table
            self.tag_refs_table = table_prefix + "_" + self.tag_refs_table
            self.categories_table = table_prefix + "_" + self.categories_table
            self.topic_tags_table = table_prefix + "_" + self.topic_tags_table
            self.category_tags_table = table_prefix + "_" + self.category_tags_table
        self.sqlite_utils = SqlLiteFuncts(self.connection['params'])

    def setup(self):
        """
        Read resource files and load list of valid tags, categories,
        tags grouped by categories, list of reference tags and its
        parent.
        :return:
        """
        _log.debug("Setup of sqlite tagging agent")
        err_message = ""
        table_names = []
        try:
            stmt = "SELECT name FROM sqlite_master " \
                "WHERE type='table';"
            name_list = self.sqlite_utils.select(stmt, None, fetch_all=True)
            table_names = [name[0] for name in name_list]
            _log.debug(table_names)
        except Exception as e:
            err_message = "Unable to query list of existing tables from the " \
                          "database. Exception: {}. Stopping tagging " \
                          "service agent".format(e.args)
        table_name = ""
        try:
            table_name = self.tags_table
            if self.tags_table in table_names:
                _log.info("{} table exists. Assuming initial values have been "
                          "loaded".format(table_name))
            else:
                self._init_tags()

            table_name = self.tag_refs_table
            if self.tag_refs_table in table_names:
                _log.info("{} table exists. Assuming initial values have been "
                          "loaded".format(table_name))
            else:
                self._init_tag_refs()

            table_name = self.topic_tags_table
            if self.topic_tags_table in table_names:
                _log.info("{} table exists. Assuming initial values "
                          "have been loaded".format(table_name))
            else:
                self._init_topic_tags()

            table_name = self.categories_table
            if self.categories_table in table_names:
                _log.info("{} table exists. Assuming initial values "
                          "have been loaded".format(table_name))
            else:
                self._init_categories()

            table_name = self.category_tags_table
            if self.category_tags_table in table_names:
                _log.info("{} table exists. Assuming initial values "
                          "have been loaded".format(table_name))
            else:
                self._init_category_tags()

        except Exception as e:
            err_message = "Initialization of " + table_name + \
                          " table failed with exception: {}" \
                          "Stopping tagging service agent. ".format(str(e))
        if err_message:
            _log.error(err_message)
            self.vip.health.set_status(STATUS_BAD,
                                       "Initialization of tagging service "
                                       "failed")
            status = Status.from_json(self.vip.health.get_status_json())
            self.vip.health.send_alert(TAGGING_AGENT_SETUP_FAILED, status)
            self.core.stop()

    def load_valid_tags(self):
        # Now cache list of tags and kind/type for validation during insert
        cursor = self.sqlite_utils.select(
            "SELECT name, kind from " + self.tags_table, fetch_all=False)
        for record in cursor:
            self.valid_tags[record[0]] = record[1]

    def load_tag_refs(self):
        # Now cache ref tags and its parent
        cursor = self.sqlite_utils.select(
            "SELECT tag, parent from " + self.tag_refs_table, fetch_all=False)
        for record in cursor:
            self.tag_refs[record[0]] = record[1]

    def _init_tags(self):
        file_path = self.resource_sub_dir + '/tags.csv'
        _log.debug("Loading file :" + file_path)
        self.sqlite_utils.execute_stmt("CREATE TABLE {}"
                                       "(name VARCHAR PRIMARY KEY, "
                                       "kind VARCHAR NOT NULL, "
                                       "description VARCHAR)".format(self.tags_table))
        to_db = []
        with open(file_path, 'r', encoding='utf-8') as content_file:
            dr = csv.DictReader(content_file)
            for row in dr:
                to_db.append((row['name'], row['kind'], row['description']))
        self.sqlite_utils.execute_many(
            "INSERT INTO {} (name, kind, description) "
            "VALUES (?, ?, ?);".format(self.tags_table),
            to_db)
        self.sqlite_utils.commit()

    def _init_tag_refs(self):
        file_path = self.resource_sub_dir + '/tag_refs.csv'
        _log.debug("Loading file :" + file_path)
        self.sqlite_utils.execute_stmt(
            "CREATE TABLE {} "
            "(tag VARCHAR NOT NULL, "
            " parent VARCHAR NOT NULL,"
            "PRIMARY KEY (tag, parent))".format(self.tag_refs_table))

        with open(file_path, 'r') as content_file:
            csv_str = content_file.read()
        # csv.DictReader uses first line in file for column headings
        # by default
        dr = csv.DictReader(csv_str.splitlines())  # comma is default delimiter
        to_db = [(i['tag'], i['parent_tag']) for i in dr]
        self.sqlite_utils.execute_many(
            "INSERT INTO {} (tag, parent) "
            "VALUES (?, ?);".format(self.tag_refs_table),
            to_db)
        self.sqlite_utils.commit()

    def _init_categories(self):
        file_path = self.resource_sub_dir + '/categories.csv'
        _log.debug("Loading file :" + file_path)
        self.sqlite_utils.execute_stmt(
            "CREATE TABLE {}"
            "(name VARCHAR PRIMARY KEY NOT NULL,"
            "description VARCHAR)".format(self.categories_table))
        _log.debug("created categories table")

        with open(file_path, 'r') as content_file:
            csv_str = content_file.read()
        dr = csv.DictReader(csv_str.splitlines())
        to_db = [(i['name'], i['description']) for i in dr]
        _log.debug("Categories in: {}".format(to_db))
        self.sqlite_utils.execute_many(
            "INSERT INTO {} (name, description) "
            "VALUES (?, ?);".format(self.categories_table), to_db)
        self.sqlite_utils.commit()

    def _init_category_tags(self):
        file_path = self.resource_sub_dir + '/category_tags.txt'
        _log.debug("Loading file :" + file_path)
        self.sqlite_utils.execute_stmt(
            "CREATE TABLE {} "
            "(category VARCHAR NOT NULL,"
            "tag VARCHAR NOT NULL,"
            "PRIMARY KEY (category, tag))".format(self.category_tags_table))
        _log.debug("created {} table".format(self.category_tags_table))
        # TODO look for decoding issues here
        with open(file_path, 'r', encoding='utf-8') as content_file:
            txt_str = content_file.read()
        to_db = []
        if txt_str:
            current_category = ""
            tags = set()
            for line in txt_str.splitlines():
                if not line or line.startswith("##"):
                    continue
                if line.startswith("#") and line.endswith("#"):
                    new_category = line.strip()[1:-1]
                    if len(tags) > 0:
                        to_db.extend([(current_category, x) for x in tags])
                    current_category = new_category
                    tags = set()
                else:
                    temp = line.split(":")   # ignore description
                    tags.update(re.split(" +", temp[0]))

            # insert last category after loop
            if len(tags) > 0:
                to_db.extend([(current_category, x) for x in tags])
            self.sqlite_utils.execute_many(
                "INSERT INTO {} (category, tag) "
                "VALUES (?, ?);".format(self.category_tags_table), to_db)
            self.sqlite_utils.commit()
        else:
            _log.warning("No category to tags mapping to initialize. No such file " + file_path)

    def _init_topic_tags(self):
        self.sqlite_utils.execute_stmt(
            "CREATE TABLE {} (topic_prefix TEXT NOT NULL, "
            "tag STRING NOT NULL, "
            "value STRING, "
            "PRIMARY KEY (topic_prefix, tag))".format(
                self.topic_tags_table, self.tags_table))
        self.sqlite_utils.execute_stmt(
            "CREATE INDEX IF NOT EXISTS idx_tag ON " +
            self.topic_tags_table + "(tag ASC);")
        self.sqlite_utils.commit()

    def query_categories(self, include_description=False, skip=0, count=None, order="FIRST_TO_LAST"):

        query = '''SELECT name, description FROM ''' \
                + self.categories_table + ''' 
                {order_by} 
                {limit} 
                {offset}'''
        order_by = ' ORDER BY name ASC'
        if order == 'LAST_TO_FIRST':
            order_by = ' ORDER BY name DESC'
        args = []

        # can't have an offset without a limit
        # -1 = no limit and allows the user to
        # provide just an offset
        if count is None:
            count = -1

        limit_statement = 'LIMIT ?'
        args.append(count)

        offset_statement = ''
        if skip > 0:
            offset_statement = 'OFFSET ?'
            args.append(skip)
        real_query = query.format(limit=limit_statement,
                                  offset=offset_statement,
                                  order_by=order_by)
        _log.debug("Real Query: " + real_query)
        _log.debug(args)
        cursor = self.sqlite_utils.select(real_query, args, fetch_all=False)
        result = OrderedDict()
        for row in cursor:
            _log.debug(row[0])
            result[row[0]] = row[1]
        _log.debug(list(result.keys()))
        _log.debug(list(result.values()))
        cursor.close()
        if include_description:
            return list(result.items())
        else:
            return list(result.keys())

    def query_tags_by_category(self, category, include_kind=False,
                               include_description=False, skip=0, count=None,
                               order="FIRST_TO_LAST"):
        query = 'SELECT name, kind, description FROM {tag} as t, ' \
                '{category_tag} as c ' \
                'WHERE ' \
                't.name = c.tag AND c.category = "{category}" ' \
                '{order_by} ' \
                '{limit} ' \
                '{offset}'
        order_by = 'ORDER BY name ASC'
        if order == 'LAST_TO_FIRST':
            order_by = ' ORDER BY name DESC'
        args = []

        _log.debug("After orderby. skip={}".format(skip))
        # can't have an offset without a limit
        # -1 = no limit and allows the user to
        # provide just an offset
        if count is None:
            count = -1

        limit_statement = 'LIMIT ?'
        args.append(count)

        offset_statement = ''
        if skip > 0:
            offset_statement = 'OFFSET ?'
            args.append(skip)
        _log.debug("before real querye")
        real_query = query.format(
            tag=self.tags_table,
            category_tag=self.category_tags_table,
            category=category,
            limit=limit_statement,
            offset=offset_statement,
            order_by=order_by)
        _log.debug("Real Query: " + real_query)
        _log.debug(args)
        cursor = None
        try:
            cursor = self.sqlite_utils.select(real_query, args,
                                              fetch_all=False)
            result = []
            for row in cursor:
                _log.debug(row[0])
                record = [row[0]]
                if include_kind:
                    record.append(row[1])
                if include_description:
                    record.append(row[2])
                if include_description or include_kind:
                    result.append(record)
                else:
                    result.append(row[0])
            return result
        finally:
            if cursor:
                cursor.close()

    def query_tags_by_topic(self, topic_prefix, include_kind=False,
                            include_description=False, skip=0, count=None,
                            order="FIRST_TO_LAST"):

        query = 'SELECT name, value, kind, description FROM {tags} as t1, ' \
                '{topic_tags} as t2 ' \
                'WHERE ' \
                't1.name = t2.tag ' \
                'AND t2.topic_prefix = "{topic_prefix}" ' \
                '{order_by} ' \
                '{limit} ' \
                '{offset}'
        order_by = 'ORDER BY name ASC'
        if order == 'LAST_TO_FIRST':
            order_by = ' ORDER BY name DESC'
        args = []

        # can't have an offset without a limit
        # -1 = no limit and allows the user to
        # provide just an offset
        if count is None:
            count = -1

        limit_statement = 'LIMIT ?'
        args.append(count)

        offset_statement = ''
        if skip > 0:
            offset_statement = 'OFFSET ?'
            args.append(skip)
        _log.debug("before real query")
        real_query = query.format(
            tags=self.tags_table, topic_tags=self.topic_tags_table,
            topic_prefix=topic_prefix, limit=limit_statement,
            offset=offset_statement, order_by=order_by)
        _log.debug("Real Query: " + real_query)
        _log.debug(args)
        cursor = None
        try:
            cursor = self.sqlite_utils.select(real_query, args,
                                              fetch_all=False)
            result = []
            for row in cursor:
                _log.debug(row[0])
                record = [row[0], row[1]]
                if include_kind:
                    record.append(row[2])
                if include_description:
                    record.append(row[3])
                result.append(record)

            return result
        finally:
            if cursor:
                cursor.close()

    def insert_topic_tags(self, tags, update_version=False):
        t = dict()
        to_db = []
        result = dict()
        result['info'] = dict()
        result['error'] = dict()
        _log.debug("IN INSERT tags {}".format(tags))
        for topic_pattern, topic_tags in list(tags.items()):
            for tag_name, tag_value in list(topic_tags.items()):
                if tag_name not in self.valid_tags:
                    raise ValueError("Invalid tag name:{}".format(tag_name))
                if tag_name == 'id':
                    _log.warning("id tags are auto generated by the system "
                                 "topic_prefix servers as unique identifier for"
                                 "an entity. id value sent({}) will not be "
                                 "stored".format(tag_value))
                    topic_tags.pop('id', None)
                    continue
                # TODO: Validate and convert values based on tag kind/type
                # for example, for Marker tags set value as true even if
                # value passed is None.
                # tag_value = get_tag_value(tag_value,
                #                          self.valid_tags[tag_name])

            _log.debug("topic pattern is {}".format(topic_pattern))
            prefixes = self.get_matching_topic_prefixes(topic_pattern)
            if not prefixes:
                result['error'][topic_pattern] = "No matching topic found"
                continue
            result['info'][topic_pattern] = []
            for prefix in prefixes:
                to_db.extend((prefix, t, v) for t, v in topic_tags.items())
                # Add id explicitly
                to_db.append((prefix, 'id', prefix))
                result['info'][topic_pattern].append(prefix)
            if len(result['info'][topic_pattern]) == 1 and topic_pattern == result['info'][topic_pattern][0]:
                # means value sent was actually some pattern so add
                # info to tell user the list of topic prefix that matched
                # the pattern sent
                _log.debug(
                    "topic passed is exact name. Not pattern. "
                    "removing from result info: {}".format(topic_pattern))
                result['info'].pop(topic_pattern)

        if to_db:
            self.sqlite_utils.execute_many(
                "REPLACE INTO {} (topic_prefix, tag, value) "
                "VALUES (?, ?, ?);".format(self.topic_tags_table), to_db)
            self.sqlite_utils.commit()
        return result

    def query_topics_by_tags(self, ast, skip=0, count=None, order=None):

        query = SqlLiteFuncts.get_tagging_query_from_ast(
            self.topic_tags_table, ast, self.tag_refs)
        order_by = ' \nORDER BY topic_prefix ASC'
        if order == 'LAST_TO_FIRST':
            order_by = ' \nORDER BY topic_prefix DESC'

        # can't have an offset without a limit
        # -1 = no limit and allows the user to
        # provide just an offset
        if count is None:
            count = -1

        limit_statement = ' \nLIMIT ' + str(count)

        offset_statement = ''
        if skip > 0:
            offset_statement = ' \nOFFSET ' + str(skip)

        real_query = query + order_by + limit_statement + offset_statement
        _log.error("#Real Query: \n" + real_query)
        conn = None
        if "REGEXP" in real_query:
            cursor, conn = self.sqlite_utils.regex_select(real_query, None,
                                                          fetch_all=False,
                                                          cache_size=-4000)
        else:
            self.sqlite_utils.set_cache(-4000)
            cursor = self.sqlite_utils.select(real_query, fetch_all=False)
        result = []
        if cursor:
            result = [r[0] for r in cursor]
            cursor.close()
        if conn:
            conn.close()
        _log.debug("#Query result: {}".format(result))
        return result


@contextlib.contextmanager
def closing(obj):
    try:
        yield obj
    finally:
        try:
            obj.close()
        except BaseException as exc:
            # if exc.__class__.__module__ == 'exceptions':
            if exc.__class__.__module__ == 'builtins':
                # Don't ignore built-in exceptions because they likely indicate a bug that should stop execution.
                # psycopg2.Error subclasses Exception, so the module must also be checked.
                raise
            _log.exception('An exception was raised while closing the cursor and is being ignored.')


class SqlLiteFuncts:

    def __init__(self, connect_params):
        database = connect_params.get('database', "tagging.sqlite")
        if database == ':memory:':
            self.__database = database
        else:
            self.__database = os.path.expandvars(os.path.expanduser(database))
            db_dir = os.path.dirname(self.__database)

            # If the db does not exist create it in case we are started
            # before the tagging agent.
            try:
                if db_dir == '':
                    if ClientContext.is_secure_mode():
                        data_dir = os.path.basename(os.getcwd()) + ".agent-data"
                        db_dir = os.path.join(os.getcwd(), data_dir)
                    else:
                        db_dir = './data'
                    self.__database = os.path.join(db_dir, self.__database)
                os.makedirs(db_dir)
            except OSError as exc:
                if exc.errno != errno.EEXIST or not os.path.isdir(db_dir):
                    raise

        connect_params['database'] = self.__database

        if 'detect_types' not in connect_params:
            connect_params['detect_types'] = sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        if 'timeout' not in connect_params.keys():
            connect_params['timeout'] = 10
        self.__connect = lambda: sqlite3.connect(**connect_params)
        self.__connection = None
        self.stash = local()

    def cursor(self):

        self.stash.cursor = None
        if self.__connection is not None and not getattr(self.__connection, "closed", False):
            try:
                self.stash.cursor = self.__connection.cursor()
                return self.stash.cursor
            except Exception:
                _log.warning("An exception occurred while creating a cursor. Will try establishing connection again")
        self.__connection = None
        try:
            self.__connection = self.__connect()
        except Exception as e:
            _log.error("Could not connect to database. Raise ConnectionError")
            raise ConnectionError(e).with_traceback(sys.exc_info()[2])
        if self.__connection is None:
            raise ConnectionError("Unknown error. Could not connect to database")

        # if any exception happens here have it go to the caller.
        self.stash.cursor = self.__connection.cursor()

        return self.stash.cursor

    def select(self, query, args=None, fetch_all=True):
        """
        Execute a select statement
        :param query: select statement
        :param args: arguments for the where clause
        :param fetch_all: Set to True if function should return retrieve all
        the records from cursors and return it. Set to False to return cursor.
        :return: resultant rows if fetch_all is True else returns the cursor
        It is up to calling method to close the cursor
        """
        if not args:
            args = ()
        cursor = self.cursor()
        try:
            cursor.execute(query, args)
        except Exception:
            cursor.close()
            raise
        if fetch_all:
            with closing(cursor):
                return cursor.fetchall()
        return cursor

    def commit(self):
        """
        Commit a transaction

        :return: True if successful, False otherwise
        """
        if self.__connection is not None:
            try:
                self.__connection.commit()
                return True
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e):
                    _log.error("EXCEPTION: SQLITE3 Database is locked. This error could occur when there are multiple "
                               "simultaneous read and write requests, making individual request to wait more than the "
                               "default timeout period. If you are using sqlite for frequent reads and write, please "
                               "configure a higher timeout in agent configuration under \nconfig[\"connection\"]"
                               "[\"params\"][\"timeout\"] Default value is 10. Timeout units is seconds")
                raise
        _log.warning('connection was null during commit phase.')
        return False

    def execute_stmt(self, stmt, args=None, commit=False):
        """
        Execute a sql statement
        :param stmt: the statement to execute
        :param args: optional arguments
        :param commit: True if transaction should be committed. Defaults to False
        :return: count of the number of affected rows
        """
        if args is None:
            args = ()
        with closing(self.cursor()) as cursor:
            cursor.execute(stmt, args)
            if commit:
                self.commit()
            return cursor.rowcount

    def execute_many(self, stmt, args, commit=False):
        """
        Execute a sql statement with multiple args
        :param stmt: the statement to execute
        :param args: optional arguments
        :param commit: True if transaction should be committed. Defaults to False
        :return: count of the number of affected rows
        """
        with closing(self.cursor()) as cursor:
            cursor.executemany(stmt, args)
            if commit:
                self.commit()
            return cursor.rowcount

    @staticmethod
    def regexp(expr, item):
        _log.debug("item {} matched against expr {}".format(item, expr))
        return re.search(expr, item, re.IGNORECASE) is not None

    def set_cache(self, cache_size):
        self.execute_stmt("PRAGMA CACHE_SIZE={}".format(cache_size))

    def regex_select(self, query, args, fetch_all=True, cache_size=None):
        conn = None
        cursor = None
        try:
            conn = sqlite3.connect(self.__database, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)

            if conn is None:
                _log.error("Unable to connect to sqlite database {} ".format(self.__database))
                return []
            conn.create_function("REGEXP", 2, SqlLiteFuncts.regexp)
            if cache_size:
                conn.execute("PRAGMA CACHE_SIZE={}".format(cache_size))
            _log.debug("REGEXP query {}  ARGS: {}".format(query, args))
            cursor = conn.cursor()
            if args is not None:
                cursor.execute(query, args)
            else:
                _log.debug("executing query")
                cursor.execute(query)
            if fetch_all:
                rows = cursor.fetchall()
                _log.debug("Regex returning {}".format(rows))
                return rows
            else:
                return cursor, conn
        except Exception as e:
            _log.error("Exception querying database based on regular expression:{}".format(e.args))
        finally:
            if fetch_all:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()

    @staticmethod
    def get_tagging_query_from_ast(topic_tags_table, tup, tag_refs):
        """
        Get a query condition syntax tree and generate sqlite query to query
        topic names by tags. It calls the get_compound_query to parse the
        abstract syntax tree tuples and then fixes the precedence

        Example:
        # User input query string :

        .. code-block::

        campus.geoPostalCode="20500" and equip and boiler and "equip_tag 7" > 4

        # Example output sqlite query

        .. code-block::

        SELECT topic_prefix from test_topic_tags WHERE tag="campusRef"
         and value  IN(
          SELECT topic_prefix from test_topic_tags WHERE tag="campus" and
          value=1
          INTERSECT
          SELECT topic_prefix  from test_topic_tags WHERE tag="geoPostalCode"
          and value="20500"
         )
        INTERSECT
        SELECT topic_prefix from test_tags WHERE tag="equip" and value=1
        INTERSECT
        SELECT topic_prefix from test_tags WHERE tag="boiler" and value=1
        INTERSECT
        SELECT topic_prefix from test_tags WHERE tag = "equip_tag 7" and
        value > 4

        :param topic_tags_table: table to query
        :param tup: parsed query string (abstract syntax tree)
        :param tag_refs: dictionary of ref tags and its parent tag
        :return: sqlite query
        :rtype str
        """
        query = SqlLiteFuncts._get_compound_query(topic_tags_table, tup, tag_refs)
        # Verify for parent tag finally. if present convert to subquery
        # Process parent tag
        # Convert
        # WHERE tag='campusRef.geoPostalCode' AND value="20500"
        # to
        # where tag='campusRef' and value  IN (
        #  SELECT topic_prefix FROM test_topic_tags
        #    WHERE tag='campus' AND value=1
        #  INTERSECT
        #  SELECT topic_prefix  FROM test_topic_tags
        #    WHERE tag='geoPostalCode'  and value="20500"
        # )

        search_pattern = r"WHERE\s+tag='(.+)\.(.+)'\s+AND\s+value\s+(.+)($|\n)"
        results = re.findall(search_pattern, query, flags=re.IGNORECASE)
        # Example result :<type 'list'>: [('campusRef', 'tag1', '= 2', '\n'),
        #                                 ('siteRef', 'tag2', '= 3 ', '\n')]
        # Loop through and replace comparison operation with sub query
        for result in results:
            parent = tag_refs[result[0]]
            replace_pattern = r"WHERE tag = '\1' AND value IN \n  (" \
                              r"SELECT topic_prefix " \
                              r"FROM {table} WHERE tag = '{parent}' AND " \
                              r"value = 1\n  " \
                              r"INTERSECT\n  " \
                              r"SELECT topic_prefix FROM {table} WHERE " \
                              r"tag = '\2' " \
                              r"AND " \
                              r"value \3 \4)".format(table=topic_tags_table,
                                                     parent=parent)
            query = re.sub(search_pattern, replace_pattern, query, count=1, flags=re.I)

        _log.debug("Returning sqlite query condition {}".format(query))
        return query

    @staticmethod
    def _get_compound_query(topic_tags_table, tup, tag_refs, root=True):
        """
        Get a query condition syntax tree and generate sqlite query to query
        topic names by tags

        Example:
        # User input query string :
        campus.geoPostalCode="20500" and equip and boiler and "equip_tag 7" > 4


        SELECT topic_prefix FROM test_topic_tags WHERE tag="campusRef"
         and value  IN(
          SELECT topic_prefix FROM test_topic_tags WHERE tag="campus" AND
            value=1
          INTERSECT
          SELECT topic_prefix  FROM test_topic_tags WHERE tag="geoPostalCode"
            AND value="20500"
         )
        INTERSECT
        SELECT topic_prefix FROM test_tags WHERE tag="equip" AND value=1
        INTERSECT
        SELECT topic_prefix FROM test_tags WHERE tag="boiler" AND value=1
        INTERSECT
        SELECT topic_prefix FROM test_tags WHERE tag = "equip_tag 7" AND
          value > 4

        :param topic_tags_table: table to query
        :param tup: parsed query string (abstract syntax tree)
        :param tag_refs: dictionary of ref tags and its parent tag
        :param root: Boolean to indicate if it is the top most tuple in the
        abstract syntax tree.
        :return: sqlite query
        :rtype str
        """

        # Instead of using sqlite LIKE operator we use python regular expression and sqlite REGEXP operator
        reserved_words = {'and': 'INTERSECT', "or": 'UNION', 'not': 'NOT', 'like': 'REGEXP'}
        prefix = 'SELECT topic_prefix FROM {} WHERE '.format(topic_tags_table)
        if tup is None:
            return tup
        if not isinstance(tup[1], tuple):
            left = repr(tup[1])  # quote the tag
        else:
            left = SqlLiteFuncts._get_compound_query(topic_tags_table, tup[1], tag_refs, False)
        if not isinstance(tup[2], tuple):
            if isinstance(tup[2], str):
                right = repr(tup[2])
            elif isinstance(tup[2], bool):
                right = 1 if tup[2] else 0
            else:
                right = tup[2]
        else:
            right = SqlLiteFuncts._get_compound_query(topic_tags_table, tup[2], tag_refs, False)

        assert isinstance(tup[0], str)

        lower_tup0 = tup[0].lower()
        operator = lower_tup0
        if lower_tup0 in reserved_words:
            operator = reserved_words[lower_tup0]

        if operator == 'NOT':
            query = SqlLiteFuncts._negate_condition(right, topic_tags_table)
        elif operator == 'INTERSECT' or operator == 'UNION':
            if root:
                query = "{left}\n{operator}\n{right}".format(left=left, operator=operator, right=right)
            else:
                query = 'SELECT topic_prefix FROM ({left} \n{operator}\n{right})'.format(
                    left=left, operator=operator, right=right)
        else:
            query = "{prefix} tag={tag} AND value {operator} {value}".format(
                prefix=prefix, tag=left, operator=operator, value=right)

        return query

    @staticmethod
    def _negate_condition(condition, table_name):
        """
        change NOT(bool_expr AND bool_expr) to NOT(bool_expr) OR NOT(bool_expr)
        recursively. In sqlite syntax:
        TO negate the following sql query:

        SELECT * FROM
          (SELECT * FROM
            (SELECT topic_prefix FROM topic_tags WHERE  tag='tag3' AND value > 1
            INTERSECT
            SELECT topic_prefix FROM topic_tags WHERE  tag='tag2' AND value > 2)
          UNION
          SELECT topic_prefix FROM topic_tags WHERE  tag='tag4' AND value < 2)

        We have to change it to:

        SELECT * FROM
          (SELECT * FROM
            (SELECT topic_prefix FROM topic_tags WHERE topic_prefix NOT IN
              (SELECT topic_prefix FROM topic_tags WHERE tag='tag3' AND
                value > 1)
            UNION
            SELECT topic_prefix FROM topic_tags WHERE topic_prefix NOT IN
             (SELECT topic_prefix FROM topic_tags WHERE  tag='tag2' AND
                value > 2))
          INTERSECT
          SELECT topic_prefix FROM topic_tags WHERE topic_prefix NOT IN(
            SELECT topic_prefix FROM topic_tags WHERE  tag='tag4' AND
             value < 2))

        :param condition: select query that needs to be negated. It could be a
        compound query.
        :return: negated select query
        :rtype str
        """
        _log.debug("Query condition to negate: {}".format(condition))
        # Change and to or and or to and
        condition = condition.replace('INTERSECT\n', 'UNION_1\n')
        condition = condition.replace('UNION\n', 'INTERSECT\n')
        condition = condition.replace('UNION_1\n', 'UNION\n')
        # Now negate all SELECT... value<operator><value> with
        # SELECT topic_prefix FROM topic_tags WHERE topic_prefix NOT IN (SELECT....value<operator><value>)

        search_pattern = r'(SELECT\s+topic_prefix\s+FROM\s+' + table_name + \
                         r'\s+WHERE\s+tag=\'.*\'\s+AND\s+value.*($|\n))'

        replace_pattern = r'SELECT topic_prefix FROM ' + table_name + r' WHERE topic_prefix NOT IN (\1)\2'
        c = re.search(search_pattern, condition)
        condition = re.sub(search_pattern,
                           replace_pattern,
                           condition,
                           flags=re.I
                           )
        _log.debug("Condition after negation: {}".format(condition))
        return condition


def main():
    """ Main entry point for the agent.
    """
    try:
        utils.vip_main(tagging_agent, version=__version__)
    except Exception as e:
        print(e)
        _log.exception('unhandled exception')


if __name__ == '__main__':
    # Entry point for script
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
