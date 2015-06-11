#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import collections
import csv
import json
import logging
import pyscp
import re

###############################################################################
# Global Constants And Variables
###############################################################################

log = logging.getLogger(__name__)

###############################################################################

if __name__ == '__main__':
    pyscp.utils.default_logging()
    sn = pyscp.core.SnapshotConnector(
        'www.scp-wiki.net',
        '/home/anqxyr/heap/_scp/scp-wiki.2015-06-11.db')
