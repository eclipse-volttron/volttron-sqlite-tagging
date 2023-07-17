SQLite Tagging Agent
====================

SQLite tagging agent provide APIs to tag both topic names(device points) and topic name prefixes (campus, building,
unit/equipment, sub unit) and then query for relevant topics based on saved tag names and values. The SQLite tagging
agent stores the tags in a sqlite3 database and hence provides a way to test this feature in VOLTTRON without any
additional database install. It performs well enough for small to medium size tag store. However, sqlite3 is not an
ideal database for key/value data that has many to many mapping. A database such as MongoDB or Postgresql would be
better suited.

This agent depends on the library `volttron-lib-tagging <https://pypi.org/project/volttron-lib-tagging/>`_ extends the class
`BaseTaggingAgent <https://github.com/eclipse-volttron/volttron-lib-tagging/blob/develop/src/tagging/base/base_tagging.py#:~:text=class%20BaseTaggingAgent>`_

Tags used by this agent have to be pre-defined in a resource file at volttron_data/tagging_resources. The
agent validates against this predefined list of tags every time user add tags to topics. Tags can be added to one
topic at a time or multiple topics by using a topic name pattern(regular expression). This agent uses version 3 tags from
`project haystack <https://project-haystack.org/>`_ and adds a few custom tags for campus and VOLTTRON point name.

Each tag has an associated value and users can query for topic names based tags and its values using a simplified
sql-like query string. Queries can specify tag names with values or tags without values for boolean tags(markers).
Queries can combine multiple conditions with keyword AND and OR, and use the keyword NOT to negate a conditions.

Dependencies and Limitations
----------------------------

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


Configuration
-------------

SQLite tagging supports three parameters

    - connection -  This is a mandatory parameter with type indicating the type of database (i.e. sqlite) and params
      containing the path the database file.

    - tables_def - Optional parameter to provide custom table names for topics, data, and metadata.

    - historian_vip_identity - Optional. Specify if you want tagging agent to query the historian with this vip
      identity. defaults to platform.historian. Historian is queried only by the add_topics api.
      other apis do not use historian.

    The configuration can be in a json or yaml formatted file.

    ::

        connection:
          # type should be sqlite
          type: sqlite
          params:
            # Relative to the agents data directory
            database: "data/tagging.sqlite"

        # optional prefix for tagging data tables
        # default is ""
        table_prefix: ""
        # optional historian vip identity. defaults to platform.historian
        historian_vip_identity: my.test.historian

