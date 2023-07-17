[![Eclipse VOLTTRON™](https://img.shields.io/badge/Eclips%20VOLTTRON--red.svg)](https://eclipse-volttron.readthedocs.io/en/latest/)
![Python 3.10](https://img.shields.io/badge/python-3.10-blue.svg)
![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)
[![Run Pytests](https://github.com/eclipse-volttron/volttron-sqlite-tagging/actions/workflows/run-test.yml/badge.svg)](https://github.com/eclipse-volttron/volttron-sqlite-tagging/actions/workflows/run-test.yml)
[![pypi version](https://img.shields.io/pypi/v/volttron-sqlite-tagging.svg)](https://pypi.org/project/volttron-sqlite-tagging/)
![Passing?](https://github.com/VOLTTRON/volttron-sqlite-tagging/actions/workflows/run-tests.yml/badge.svg)

# SQLite Tagging Agent 

SQLite tagging agent provide APIs to tag both topic names(device points) and topic name prefixes (campus, building, 
unit/equipment, sub unit) and then query for relevant topics based on saved tag names and values. The SQLite tagging 
agent stores the tags in a sqlite3 database and hence provides a way to test this feature in VOLTTRON without any 
additional database install. However, sqlite3 is not an ideal database for key/value data that has many to many mapping. 
A database such as MongoDB or Postgresql would be better suited.

Tags used by this agent have to be pre-defined in a resource file at volttron_data/tagging_resources. The
agent validates against this predefined list of tags every time user add tags to topics. Tags can be added to one 
topic at a time or multiple topics by using a topic name pattern(regular expression). This agent uses tags from 
[project haystack](https://project-haystack.org/) and adds a few custom tags for campus and VOLTTRON point name.

Each tag has an associated value and users can query for topic names based tags and its values using a simplified 
sql-like query string. Queries can specify tag names with values or tags without values for boolean tags(markers). 
Queries can combine multiple conditions with keyword AND and OR, and use the keyword NOT to negate a conditions.

## Requirements

 - Python >= 3.10


## Dependencies and Limitations

1. When adding tags to topics this agent calls the platform.historian's (or a configured historian's) 
   get_topic_list and hence requires a platform.historian or configured historian to be running, but it doesn't require 
   the historian to use sqlite3 or any specific database. It requires historian to be running only for using this 
   api (add_tags) and does not require historian to be running for any other api. 
2. Resource files that provides the list of valid tags is mandatory and is present under data_model/tags.csv   
   within base tagging agent
3. Tagging agent only provides APIs query for topic names based on tags. Once the list of topic names is retrieved, 
   users should use the historian APIs to get the data corresponding to those topics. 
4. Current version of tagging agent does not support versioning of tag/values. When tags values set using tagging 
   agent's APIs update/overwrite any existing tag entries in the database
5. Since RDMS is not a natural fit for tagname=value kind of data, performance of queries will not be high if you have 
   several thousands of topics and several hundreds tags for each topic and perform complex queries. For intermediate 
   level data and query complexity, performance can be improved by increasing the page limit of sqlite.

## Installation

1. Create and activate a virtual environment.

   ```shell
    python -m venv env
    source env/bin/activate
    ```

2. Installing volttron-sqlite-tagging requires a running volttron instance.

    ```shell
    pip install volttron
    
    # Start platform with output going to volttron.log
    volttron -vv -l volttron.log &
    ```

3. Create an agent configuration file 
   SQLite tagging supports three parameters
    
    - connection -  This is a mandatory parameter with type indicating the type of database (i.e. sqlite) and params 
                    containing the path the database file.
    
    - table_prefix - Optional parameter to provide custom table names for topics, data, and metadata.
   
    - historian_vip_identity - Optional. Specify if you want tagging agent to query the historian with this vip 
                               identity. defaults to platform.historian. Historian is queried only by the add_topics api.
                               other apis do not use historian.
    
    The configuration can be in a json or yaml formatted file.

    Yaml Format:

    ```yaml
    connection:
      # type should be sqlite
      type: sqlite
      params:
        # Relative to the agents data directory
        database: "data/tagging.sqlite"
    
    # prefix for tagging data tables
    table_prefix: ""

    historian_vip_identity: my.test.historian
    ```
    
4. Install and start the volttron-sqlite-tagging agent.

    ```shell
    vctl install volttron-sqlite-taggig --agent-config <path to configuration> --start
    ```

5. View the status of the installed agent

    ```shell
    vctl status
    ```

## Development

Please see the following for contributing guidelines [contributing](https://github.com/eclipse-volttron/volttron-core/blob/develop/CONTRIBUTING.md).

Please see the following helpful guide about [developing modular VOLTTRON agents](https://github.com/eclipse-volttron/volttron-core/blob/develop/DEVELOPING_ON_MODULAR.md)

# Disclaimer Notice

This material was prepared as an account of work sponsored by an agency of the
United States Government.  Neither the United States Government nor the United
States Department of Energy, nor Battelle, nor any of their employees, nor any
jurisdiction or organization that has cooperated in the development of these
materials, makes any warranty, express or implied, or assumes any legal
liability or responsibility for the accuracy, completeness, or usefulness or any
information, apparatus, product, software, or process disclosed, or represents
that its use would not infringe privately owned rights.

Reference herein to any specific commercial product, process, or service by
trade name, trademark, manufacturer, or otherwise does not necessarily
constitute or imply its endorsement, recommendation, or favoring by the United
States Government or any agency thereof, or Battelle Memorial Institute. The
views and opinions of authors expressed herein do not necessarily state or
reflect those of the United States Government or any agency thereof.
