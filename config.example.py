"""Local database configuration template.

Copy this file to config.py and adjust the values for your environment.
Never commit config.py or real database credentials.
"""

import os


MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_USER = os.getenv("MYSQL_USER", "commerceops")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "commerceops-dev")
MYSQL_DB = os.getenv("MYSQL_DB", "ecommerce_db")
